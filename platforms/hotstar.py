import re
import json
import yt_dlp
from platforms.base import slugify, COMMON_HEADERS

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    import requests as cffi_requests
    HAS_CURL_CFFI = False


class HotstarPlatform:
    NAME = "Hotstar"
    DOMAINS = ["hotstar.com"]

    @classmethod
    def can_handle(cls, url: str) -> bool:
        return any(d in url.lower() for d in cls.DOMAINS)

    @classmethod
    def parse_url(cls, url: str) -> tuple[str, str, str, str] | None:
        """
        Extracts (slug, show_id, serial_name, canonical_url) from ANY Hotstar link.
        Automatically converts unsupported watch links like:
          https://www.hotstar.com/in/shows/bigg-boss/17932/watch
        Into canonical series URLs:
          https://www.hotstar.com/in/shows/bigg-boss/17932
        """
        clean = url.split("?")[0].rstrip("/")

        # Match /shows/<slug>/<show_id>(/watch or /any/subpath)?
        match = re.search(r"hotstar\.com/(?:[a-z]{2}/)?shows/([^/]+)/(\d+)", clean)
        if match:
            slug, show_id = match.group(1), match.group(2)
            serial_name = " ".join(w.capitalize() for w in slug.split("-"))
            canonical_url = f"https://www.hotstar.com/in/shows/{slug}/{show_id}"
            return slug, show_id, serial_name, canonical_url

        # Match short ID format: /<id>/watch
        match_short = re.search(r"hotstar\.com/(?:[a-z]{2}/)?(\d+)(?:/watch)?", clean)
        if match_short:
            content_id = match_short.group(1)
            canonical_url = f"https://www.hotstar.com/in/shows/{content_id}"
            return content_id, content_id, f"Show {content_id}", canonical_url

        return None

    @classmethod
    def build_watch_link(cls, show_slug: str, show_id: str, ep_name: str, ep_id: str, raw_url: str = None) -> str:
        if raw_url and raw_url.startswith("http") and "/watch" in raw_url:
            return raw_url
        ep_slug = slugify(ep_name)
        if ep_slug:
            return f"https://www.hotstar.com/in/shows/{show_slug}/{show_id}/{ep_slug}/{ep_id}/watch"
        return f"https://www.hotstar.com/in/shows/{show_slug}/{show_id}/{ep_id}/watch"

    @classmethod
    def _make_http_get(cls, url: str, headers: dict):
        """HTTP GET with Chrome TLS impersonation (bypasses Akamai/Cloudflare 403 & 475)."""
        if HAS_CURL_CFFI:
            try:
                return cffi_requests.get(url, headers=headers, impersonate="chrome124", timeout=15)
            except Exception as e:
                print(f"[!] curl_cffi error ({e}), falling back to standard requests")
        import requests
        return requests.get(url, headers=headers, timeout=15)

    @classmethod
    def fetch_episodes(cls, show_url: str) -> list[dict]:
        """
        Multi-strategy episode extractor:
        1. Direct Next.js webpage scrape with Chrome TLS impersonation
        2. Hotstar internal layout API
        3. yt-dlp fallback
        """
        clean_url = show_url.split("?")[0].rstrip("/")
        if clean_url.endswith("/watch"):
            clean_url = clean_url[:-6]

        parsed = cls.parse_url(clean_url)
        show_slug = parsed[0] if parsed else "show"
        show_id = parsed[1] if parsed else ""

        headers = {
            **COMMON_HEADERS,
            "Referer": "https://www.hotstar.com/",
            "X-Country-Code": "IN",
            "X-Platform-Code": "WEB",
        }

        entries = []
        seen_ids = set()

        # ================= STRATEGY 1: Webpage Scrape =================
        try:
            resp = cls._make_http_get(clean_url, headers)
            if resp.status_code == 200:
                html = resp.text

                # 1. Parse Next.js __NEXT_DATA__
                next_match = re.search(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>', html)
                if next_match:
                    try:
                        data = json.loads(next_match.group(1))

                        def search_items(obj):
                            if isinstance(obj, dict):
                                c_id = str(obj.get("contentId") or obj.get("id") or obj.get("content_id") or obj.get("assetId") or "")
                                title = obj.get("title") or obj.get("episodeTitle") or obj.get("name")
                                if c_id and c_id.isdigit() and len(c_id) >= 6 and title and c_id not in seen_ids:
                                    is_ep = (
                                        obj.get("episodeNo") is not None
                                        or obj.get("episodeNumber") is not None
                                        or "watch" in str(obj.get("url", ""))
                                        or obj.get("assetType") in ["EPISODE", "SHOW_EPISODE"]
                                        or "episode" in str(obj.get("entityType", "")).lower()
                                        or "/watch" in str(obj)
                                    )
                                    if is_ep:
                                        seen_ids.add(c_id)
                                        ep_num = str(obj.get("episodeNo") or obj.get("episodeNumber") or "")
                                        thumb = None
                                        if isinstance(obj.get("images"), dict):
                                            thumb = obj["images"].get("h") or obj["images"].get("v")
                                        elif isinstance(obj.get("image"), str):
                                            thumb = obj.get("image")

                                        entries.append({
                                            "id": c_id,
                                            "title": f"Episode {ep_num} - {title}" if ep_num and ep_num not in str(title) else str(title),
                                            "thumbnail": thumb,
                                            "season_number": str(obj.get("seasonNo") or obj.get("seasonNumber") or "1"),
                                            "url": f"https://www.hotstar.com/in/shows/{show_slug}/{show_id}/{c_id}/watch"
                                        })
                                for v in obj.values():
                                    search_items(v)
                            elif isinstance(obj, list):
                                for item in obj:
                                    search_items(item)

                        search_items(data)
                    except Exception as json_err:
                        print(f"[!] Error reading Hotstar __NEXT_DATA__: {json_err}")

                # 2. Extract direct watch links anywhere in HTML (inside script or attributes)
                link_matches = re.findall(r'/(?:[a-z]{2}/)?shows/[^/"\s]+/\d+/([^/"\s]+)/(\d+)/watch', html)
                for ep_slug, ep_id in link_matches:
                    if ep_id not in seen_ids:
                        seen_ids.add(ep_id)
                        clean_title = ep_slug.replace("-", " ").title()
                        entries.append({
                            "id": ep_id,
                            "title": clean_title,
                            "url": f"https://www.hotstar.com/in/shows/{show_slug}/{show_id}/{ep_slug}/{ep_id}/watch"
                        })

                # 3. Extract numeric watch links
                num_matches = re.findall(r'/(\d{8,12})/watch', html)
                for ep_id in num_matches:
                    if ep_id not in seen_ids:
                        seen_ids.add(ep_id)
                        entries.append({
                            "id": ep_id,
                            "title": f"Episode {ep_id}",
                            "url": f"https://www.hotstar.com/{ep_id}/watch"
                        })

                if entries:
                    print(f"[✓] Strategy 1 (Webpage): Extracted {len(entries)} episodes from {show_slug}")
                    return entries
            else:
                print(f"[!] Hotstar webpage returned HTTP {resp.status_code}")
        except Exception as e:
            print(f"[!] Strategy 1 error: {e}")

        # ================= STRATEGY 2: Hotstar Content API =================
        if show_id:
            try:
                api_url = f"https://api.hotstar.com/o/v1/multi/get/content?ids={show_id}"
                api_headers = {**headers, "Accept": "application/json"}
                resp = cls._make_http_get(api_url, api_headers)
                if resp.status_code == 200:
                    api_data = resp.json()
                    # Parse contents
                    items = []
                    if isinstance(api_data, dict):
                        response_body = api_data.get("body", {}) or api_data
                        results = response_body.get("results", {}) or response_body
                        items = results.get("items", []) or results.get("map", {}).values()

                    for item in items:
                        if isinstance(item, dict):
                            c_id = str(item.get("contentId") or item.get("id") or "")
                            title = item.get("title") or item.get("name")
                            if c_id and c_id not in seen_ids and title:
                                seen_ids.add(c_id)
                                ep_num = str(item.get("episodeNo") or "")
                                entries.append({
                                    "id": c_id,
                                    "title": f"Episode {ep_num} - {title}" if ep_num and ep_num not in str(title) else str(title),
                                    "season_number": str(item.get("seasonNo") or "1"),
                                    "url": f"https://www.hotstar.com/{c_id}/watch"
                                })
                    if entries:
                        print(f"[✓] Strategy 2 (API): Extracted {len(entries)} episodes for {show_slug}")
                        return entries
            except Exception as e:
                print(f"[!] Strategy 2 error: {e}")

        # ================= STRATEGY 3: yt-dlp Fallback =================
        ydl_opts = {
            "extract_flat": "in_playlist",
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "http_headers": headers
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(clean_url, download=False)
                res = info.get("entries", []) if info else []
                if res:
                    print(f"[✓] Strategy 3 (yt-dlp): Extracted {len(res)} episodes for {show_slug}")
                return res
            except Exception as e:
                print(f"[!] Strategy 3 error: {e}")
                return []
