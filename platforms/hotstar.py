import re
import json
import urllib.parse
import concurrent.futures
import requests
import yt_dlp
from platforms.base import slugify, COMMON_HEADERS, HOTSTAR_EP_RE, has_episode_number, episode_sort_key

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
        """Extracts (slug, show_id, serial_name, canonical_url) from ANY Hotstar link."""
        clean = url.split("?")[0].rstrip("/")

        match = re.search(r"hotstar\.com/(?:[a-z]{2}/)?shows/([^/]+)/(\d+)", clean)
        if match:
            slug, show_id = match.group(1), match.group(2)
            serial_name = " ".join(w.capitalize() for w in slug.split("-"))
            canonical_url = f"https://www.hotstar.com/in/shows/{slug}/{show_id}"
            return slug, show_id, serial_name, canonical_url

        match_short = re.search(r"hotstar\.com/(?:[a-z]{2}/)?(\d+)(?:/watch)?", clean)
        if match_short:
            content_id = match_short.group(1)
            canonical_url = f"https://www.hotstar.com/in/shows/{content_id}"
            return content_id, content_id, f"Show {content_id}", canonical_url

        return None

    @classmethod
    def build_watch_link(cls, show_slug: str, show_id: str, ep_name: str, ep_id: str, raw_url: str = None) -> str:
        """
        Builds the canonical Hotstar episode URL:
            https://www.hotstar.com/in/shows/<show-slug>/<show_id>/<episode-slug>/<episode_id>/watch

        Rules (these fix the wrong-link bugs):
        - A raw URL is only trusted if it belongs to THIS show (same show_id) and carries a
          real 8-12 digit episode id. It is then re-emitted in canonical form.
        - If we do not have a real episode id we fall back to the show page, never to a
          made-up watch link.
        """
        show_page = f"https://www.hotstar.com/in/shows/{show_slug}/{show_id}"

        if raw_url:
            m = HOTSTAR_EP_RE.search(raw_url)
            if m and m.group(2) == str(show_id) and m.group(4) != str(show_id):
                return f"https://www.hotstar.com/in/shows/{m.group(1)}/{m.group(2)}/{m.group(3)}/{m.group(4)}/watch"

        ep_id = str(ep_id or "")
        if not ep_id.isdigit() or len(ep_id) < 8 or ep_id == str(show_id):
            return show_page

        ep_slug = slugify(ep_name or "")
        if not ep_slug or ep_slug in ("episode", "latest-episode", "new-episode"):
            ep_slug = "episode"
        return f"https://www.hotstar.com/in/shows/{show_slug}/{show_id}/{ep_slug}/{ep_id}/watch"

    @classmethod
    def verify_episode_page(cls, watch_url: str, ep_number: str) -> bool | None:
        """
        Best-effort check that a watch URL really is the requested episode.
        True = confirmed, False = page loaded but number not found, None = could not load page.
        """
        try:
            resp = cls._make_http_get(watch_url, {**COMMON_HEADERS, "Referer": "https://www.hotstar.com/"})
            if resp.status_code != 200:
                return None
            head = resp.text[:60000]
            meta = re.findall(r"<title[^>]*>([\s\S]*?)</title>|property=\"og:title\" content=\"([^\"]*)\"", head)
            blob = " ".join(a or b for a, b in meta) + " " + watch_url
            return has_episode_number(blob, ep_number)
        except Exception:
            return None

    @classmethod
    def _make_http_get(cls, url: str, headers: dict):
        if HAS_CURL_CFFI:
            try:
                return cffi_requests.get(url, headers=headers, impersonate="chrome124", timeout=15)
            except Exception as e:
                print(f"[!] curl_cffi error ({e}), falling back to requests")
        return requests.get(url, headers=headers, timeout=15)

    @classmethod
    def _fetch_from_sitemaps(cls, show_slug: str, show_id: str) -> list[dict]:
        """
        Discovers official Hotstar episode URLs directly from Hotstar's public XML sitemaps
        and enriches them with genuine episode metadata (titles, episode numbers, etc.)
        via the Hotstar catalog multi-content API. Bypasses all cloud IP restrictions.
        """
        sitemap_urls = [f"https://www.hotstar.com/in/new-sitemap-EPISODE-{i}.xml" for i in range(1, 10)]
        slug_map = {}
        pattern = rf'shows/{re.escape(show_slug)}/{re.escape(str(show_id))}/([^/"\s]+)/(\d{{8,12}})/watch'

        def fetch_sitemap(url):
            try:
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    return re.findall(pattern, r.text)
            except Exception:
                pass
            return []

        with concurrent.futures.ThreadPoolExecutor(max_workers=9) as ex:
            for res in ex.map(fetch_sitemap, sitemap_urls):
                for ep_slug, ep_id in res:
                    if ep_id != str(show_id):
                        slug_map[ep_id] = ep_slug

        if not slug_map:
            return []

        # Sort IDs prioritizing recent 2026 content blocks (1641..., 1700...)
        all_ids = list(slug_map.keys())
        all_ids.sort(key=lambda x: (x.startswith("1641"), x.startswith("1700"), x), reverse=True)
        target_ids = all_ids[:200]

        headers = {
            "x-country-code": "IN",
            "x-platform-code": "JIO",
            "User-Agent": "Hotstar;in.startv.hotstar/3.3.0 (Android/8.1.0)",
            "Accept": "application/json",
        }

        episodes = []

        def fetch_chunk(chunk):
            chunk_eps = []
            try:
                api_url = f"https://api.hotstar.com/o/v1/multi/get/content?ids={','.join(chunk)}"
                r = requests.get(api_url, headers=headers, timeout=10)
                if r.status_code == 200:
                    results_map = r.json().get("body", {}).get("results", {}).get("map", {})
                    for c_id, item in results_map.items():
                        if isinstance(item, dict):
                            ep_no = str(item.get("episodeNo") or "")
                            title = item.get("title") or f"Episode {ep_no}"
                            season_no = str(item.get("seasonNo") or "1")
                            ep_slug = slug_map.get(str(c_id)) or slugify(title) or "episode"
                            watch_url = f"https://www.hotstar.com/in/shows/{show_slug}/{show_id}/{ep_slug}/{c_id}/watch"
                            thumb = None
                            if isinstance(item.get("images"), dict):
                                thumb = item["images"].get("h") or item["images"].get("v")
                            elif isinstance(item.get("image"), str):
                                thumb = item.get("image")

                            chunk_eps.append({
                                "id": str(c_id),
                                "title": f"Episode {ep_no} - {title}" if ep_no and ep_no not in str(title) else str(title),
                                "episode_name": title,
                                "episode_number": ep_no,
                                "season_number": season_no,
                                "thumbnail": thumb,
                                "url": watch_url,
                            })
            except Exception:
                pass
            return chunk_eps

        chunks = [target_ids[i:i + 40] for i in range(0, len(target_ids), 40)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
            for chunk_eps in ex.map(fetch_chunk, chunks):
                episodes.extend(chunk_eps)

        if episodes:
            return sorted(episodes, key=episode_sort_key, reverse=True)
        return []

    @classmethod
    def search_episode_online(cls, show_slug: str, show_id: str, ep_number: str) -> dict | None:
        """
        Finds the exact Hotstar episode title and genuine 10-digit watch URL.
        1. Checks the official Hotstar catalog and sitemaps.
        2. Falls back to multi-engine public internet search.
        """
        show_url = f"https://www.hotstar.com/in/shows/{show_slug}/{show_id}"
        episodes = cls.fetch_episodes(show_url)
        for ep in episodes:
            stored_num = str(ep.get("episode_number") or "")
            if stored_num == str(ep_number) or has_episode_number(ep.get("title", ""), ep_number):
                return ep

        from platforms.web_search import search_exact_episode_from_internet
        show_name = show_slug.replace("-", " ").title()
        return search_exact_episode_from_internet(show_name, show_slug, show_id, ep_number, "Hotstar")

    @classmethod
    def fetch_episodes(cls, show_url: str) -> list[dict]:
        clean_url = show_url.split("?")[0].rstrip("/")
        if clean_url.endswith("/watch"):
            clean_url = clean_url[:-6]

        parsed = cls.parse_url(clean_url)
        show_slug = parsed[0] if parsed else "show"
        show_id = parsed[1] if parsed else ""

        # Strategy 1: Official Sitemaps + Multi-Get Content Metadata (Direct, accurate, bypasses all geo-blocks)
        if show_slug and show_id:
            try:
                sitemap_episodes = cls._fetch_from_sitemaps(show_slug, show_id)
                if sitemap_episodes:
                    return sitemap_episodes
            except Exception as e:
                print(f"[!] Hotstar sitemap discovery warning: {e}")

        headers = {
            **COMMON_HEADERS,
            "Referer": "https://www.hotstar.com/",
            "X-Country-Code": "IN",
            "X-Platform-Code": "WEB",
        }

        entries = []
        seen_ids = set()

        # Strategy 2: Webpage Scrape
        try:
            resp = cls._make_http_get(clean_url, headers)
            if resp.status_code == 200:
                html = resp.text

                # Parse __NEXT_DATA__
                next_match = re.search(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>', html)
                if next_match:
                    try:
                        data = json.loads(next_match.group(1))

                        def belongs_to_show(obj: dict) -> bool:
                            """Only accept episodes of THIS show (ignore recommendation/'More like this' rows)."""
                            for key in ("showId", "showContentId", "showContentID", "show_id", "parentContentId"):
                                if obj.get(key) is not None:
                                    return str(obj[key]) == str(show_id)
                            link_blob = " ".join(str(obj.get(k, "")) for k in ("url", "deeplink", "deepLink", "pageUrl", "path"))
                            m = HOTSTAR_EP_RE.search(link_blob)
                            if m:
                                return m.group(2) == str(show_id)
                            return False

                        def search_items(obj):
                            if isinstance(obj, dict):
                                c_id = str(obj.get("contentId") or obj.get("id") or obj.get("content_id") or obj.get("assetId") or "")
                                title = obj.get("title") or obj.get("episodeTitle") or obj.get("name")
                                if c_id and c_id.isdigit() and 8 <= len(c_id) <= 12 and c_id != str(show_id) \
                                        and title and c_id not in seen_ids:
                                    is_ep = (
                                        obj.get("episodeNo") is not None
                                        or obj.get("episodeNumber") is not None
                                        or obj.get("assetType") in ["EPISODE", "SHOW_EPISODE"]
                                        or "episode" in str(obj.get("entityType", "")).lower()
                                    )
                                    if is_ep and belongs_to_show(obj):
                                        seen_ids.add(c_id)
                                        ep_num = str(obj.get("episodeNo") or obj.get("episodeNumber") or "")
                                        thumb = None
                                        if isinstance(obj.get("images"), dict):
                                            thumb = obj["images"].get("h") or obj["images"].get("v")
                                        elif isinstance(obj.get("image"), str):
                                            thumb = obj.get("image")

                                        ep_slug = slugify(str(title)) or "episode"
                                        entries.append({
                                            "id": c_id,
                                            "title": f"Episode {ep_num} - {title}" if ep_num and ep_num not in str(title) else str(title),
                                            "episode_number": ep_num,
                                            "thumbnail": thumb,
                                            "season_number": str(obj.get("seasonNo") or obj.get("seasonNumber") or "1"),
                                            "url": f"https://www.hotstar.com/in/shows/{show_slug}/{show_id}/{ep_slug}/{c_id}/watch"
                                        })
                                for v in obj.values():
                                    search_items(v)
                            elif isinstance(obj, list):
                                for item in obj:
                                    search_items(item)

                        search_items(data)
                    except Exception as json_err:
                        print(f"[!] Error reading Hotstar __NEXT_DATA__: {json_err}")

                # Extract direct watch links from HTML - ONLY links under this show's id
                link_pattern = rf'/(?:[a-z]{{2}}/)?shows/[^/"\s]+/{re.escape(str(show_id))}/([^/"\s]+)/(\d{{8,12}})/watch'
                for ep_slug, ep_id in re.findall(link_pattern, html):
                    if ep_id not in seen_ids and ep_id != str(show_id):
                        seen_ids.add(ep_id)
                        clean_title = ep_slug.replace("-", " ").title()
                        entries.append({
                            "id": ep_id,
                            "title": clean_title,
                            "url": f"https://www.hotstar.com/in/shows/{show_slug}/{show_id}/{ep_slug}/{ep_id}/watch"
                        })

                if entries:
                    return sorted(entries, key=episode_sort_key, reverse=True)
        except Exception as e:
            print(f"[!] Hotstar scraper error: {e}")

        # Strategy 2: API Gateway
        if show_id:
            try:
                api_url = f"https://api.hotstar.com/o/v1/multi/get/content?ids={show_id}"
                resp = cls._make_http_get(api_url, {**headers, "Accept": "application/json"})
                if resp.status_code == 200:
                    api_data = resp.json()
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
                                    "url": f"https://www.hotstar.com/in/shows/{show_slug}/{show_id}/{slugify(str(title)) or 'episode'}/{c_id}/watch"
                                })
                    if entries:
                        return sorted(entries, key=episode_sort_key, reverse=True)
            except Exception as e:
                print(f"[!] Hotstar API error: {e}")

        # Strategy 3: yt-dlp (silently handles datacenter IP 475 restrictions)
        class QuietYtdlLogger:
            def debug(self, msg): pass
            def warning(self, msg): pass
            def error(self, msg): pass

        ydl_opts = {
            "extract_flat": "in_playlist",
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "logger": QuietYtdlLogger(),
            "http_headers": headers
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(clean_url, download=False)
                res = info.get("entries", []) if info else []
                if res:
                    return res
            except Exception:
                pass

        # Strategy 4: Multi-Engine Web Search Index Crawler (DuckDuckGo Lite + Bing + Yahoo)
        # Bypasses cloud datacenter IP blocks, Akamai restrictions, and foreign IP 475 errors
        try:
            from platforms.web_search import search_all_episodes_from_internet
            show_name = show_slug.replace("-", " ").title()
            online_episodes = search_all_episodes_from_internet(show_name, show_slug, show_id, "Hotstar")
            if online_episodes:
                return sorted(online_episodes, key=episode_sort_key, reverse=True)
        except Exception as e:
            print(f"[!] Hotstar online episode discovery warning: {e}")

        return []
