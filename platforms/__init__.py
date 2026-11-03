import urllib.parse
from platforms.hotstar import HotstarPlatform
from platforms.zee5 import Zee5Platform
from platforms.sonyliv import SonyLIVPlatform
from platforms.sunnxt import SunNXTPlatform
from platforms.manoramamax import ManoramaMAXPlatform

PLATFORMS = [
    HotstarPlatform,
    Zee5Platform,
    SonyLIVPlatform,
    SunNXTPlatform,
    ManoramaMAXPlatform,
]

PLATFORM_MAP = {p.NAME.lower(): p for p in PLATFORMS}


def detect_platform(url: str) -> str:
    """Detect platform name from URL."""
    for p in PLATFORMS:
        if p.can_handle(url):
            return p.NAME
    return "OTT"


def get_platform_handler(platform_name: str):
    """Retrieve platform class handler."""
    return PLATFORM_MAP.get(platform_name.lower(), HotstarPlatform)


def parse_show_url(url: str) -> tuple[str, str, str, str] | None:
    """
    Auto-detects platform and extracts (show_slug, show_id, serial_name, platform_name).
    """
    for p in PLATFORMS:
        if p.can_handle(url):
            res = p.parse_url(url)
            if res:
                slug, show_id, name = res
                return slug, show_id, name, p.NAME

    # Generic fallback
    parsed = urllib.parse.urlparse(url)
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if parts:
        slug = parts[-1]
        name = " ".join(w.capitalize() for w in slug.split("-"))
        return slug, slug, name, "OTT"
    return None


def fetch_episodes(show_url: str, platform_name: str) -> list[dict]:
    """Fetches episode list from the appropriate platform module."""
    handler = get_platform_handler(platform_name)
    return handler.fetch_episodes(show_url)


def build_watch_link(show_slug: str, show_id: str, ep_name: str, ep_id: str, platform_name: str, raw_url: str = None) -> str:
    """Constructs canonical watch URL for the appropriate platform."""
    handler = get_platform_handler(platform_name)
    return handler.build_watch_link(show_slug, show_id, ep_name, ep_id, raw_url=raw_url)


def get_supported_platforms() -> list[str]:
    """Returns list of all supported OTT platforms."""
    return [p.NAME for p in PLATFORMS]
