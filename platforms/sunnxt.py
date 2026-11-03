import re
import yt_dlp
from platforms.base import COMMON_HEADERS


class SunNXTPlatform:
    NAME = "SunNXT"
    DOMAINS = ["sunnxt.com"]

    @classmethod
    def can_handle(cls, url: str) -> bool:
        return any(d in url.lower() for d in cls.DOMAINS)

    @classmethod
    def parse_url(cls, url: str) -> tuple[str, str, str] | None:
        """Extract (slug, show_id, serial_name) from SunNXT show link."""
        match = re.search(r"sunnxt\.com/([^/]+)/([a-zA-Z0-9_-]+)", url)
        if match:
            slug, show_id = match.group(1), match.group(2)
            serial_name = " ".join(w.capitalize() for w in slug.split("-"))
            return slug, show_id, serial_name
        return None

    @classmethod
    def build_watch_link(cls, show_slug: str, show_id: str, ep_name: str, ep_id: str, raw_url: str = None) -> str:
        if raw_url and raw_url.startswith("http"):
            return raw_url
        return f"https://www.sunnxt.com/detail/{ep_id}"

    @classmethod
    def fetch_episodes(cls, show_url: str) -> list[dict]:
        ydl_opts = {
            "extract_flat": "in_playlist",
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "http_headers": {**COMMON_HEADERS, "Referer": show_url}
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(show_url, download=False)
                return info.get("entries", []) if info else []
            except Exception as e:
                print(f"[!] SunNXT extractor error: {e}")
                return []
