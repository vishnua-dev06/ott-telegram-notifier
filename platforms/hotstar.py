import re
import json
import requests
import yt_dlp
from platforms.base import slugify, COMMON_HEADERS


class HotstarPlatform:
    NAME = "Hotstar"
    DOMAINS = ["hotstar.com"]

    @classmethod
    def can_handle(cls, url: str) -> bool:
        return any(d in url.lower() for d in cls.DOMAINS)

    @classmethod
    def parse_url(cls, url: str) -> tuple[str, str, str] | None:
        """Extract (slug, show_id, serial_name) from Hotstar show link."""
        match = re.search(r"hotstar\.com/(?:[a-z]{2}/)?shows/([^/]+)/(\d+)", url)
        if match:
            slug, show_id = match.group(1), match.group(2)
            serial_name = " ".join(w.capitalize() for w in slug.split("-"))
            return slug, show_id, serial_name
        return None

    @classmethod
    def build_watch_link(cls, show_slug: str, show_id: str, ep_name: str, ep_id: str, raw_url: str = None) -> str:
        if raw_url and raw_url.startswith("http"):
            return raw_url
        ep_slug = slugify(ep_name)
        if ep_slug:
            return f"https://www.hotstar.com/in/shows/{show_slug}/{show_id}/{ep_slug}/{ep_id}/watch"
        return f"https://www.hotstar.com/in/shows/{show_slug}/{show_id}/{ep_id}/watch"

    @classmethod
    def fetch_episodes(cls, show_url: str) -> list[dict]:
        """Scrapes episodes using direct Next.js webpage parser (avoids 475 geo-block), with yt-dlp fallback."""
        headers = {**COMMON_HEADERS, "Referer": "https://www.hotstar.com/"}
        try:
            resp = requests.get(show_url, headers=headers, timeout=15)
            if resp.status_code == 200:
                html = resp.text
                entries = []
                seen_ids = set()

                # 1. Parse Next.js __NEXT_DATA__
                next_match = re.search(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>', html)
                if next_match:
                    try:
                        data = json.loads(next_match.group(1))

                        def search_items(obj):
                            if isinstance(obj, dict):
                                c_id = str(obj.get("contentId") or obj.get("id") or "")
                                title = obj.get("title") or obj.get("episodeTitle") or obj.get("name")
                                if c_id and c_id.isdigit() and len(c_id) >= 8 and title and c_id not in seen_ids:
                                    is_ep = (
                                        obj.get("episodeNo") is not None
                                        or obj.get("episodeNumber") is not None
                                        or "watch" in str(obj.get("url", ""))
                                        or obj.get("assetType") in ["EPISODE", "SHOW_EPISODE"]
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
                                        })
                                for v in obj.values():
                                    search_items(v)
                            elif isinstance(obj, list):
                                for item in obj:
                                    search_items(item)

                        search_items(data)
                    except Exception:
                        pass

                # 2. Extract direct watch links from HTML
                link_matches = re.findall(r'href="([^"]*?/shows/[^/]+/\d+/([^/]+)/(\d{8,12})/watch)"', html)
                for full_link, ep_slug, ep_id in link_matches:
                    if ep_id not in seen_ids:
                        seen_ids.add(ep_id)
                        clean_title = ep_slug.replace("-", " ").title()
                        entries.append({
                            "id": ep_id,
                            "title": clean_title,
                            "url": f"https://www.hotstar.com{full_link}" if full_link.startswith("/") else full_link
                        })

                if entries:
                    return entries
        except Exception as e:
            print(f"[!] Hotstar web scraper error: {e}")

        # Fallback to yt-dlp
        ydl_opts = {
            "extract_flat": "in_playlist",
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "http_headers": {**COMMON_HEADERS, "Referer": "https://www.hotstar.com/"}
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(show_url, download=False)
                return info.get("entries", []) if info else []
            except Exception as e:
                print(f"[!] yt-dlp Hotstar fallback error: {e}")
                return []

