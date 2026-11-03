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
    for p in PLATFORMS:
        if p.can_handle(url):
            return p.NAME
    return "OTT"


def get_platform_handler(platform_name: str):
    return PLATFORM_MAP.get(platform_name.lower(), HotstarPlatform)


def parse_show_url(url: str) -> tuple[str, str, str, str, str] | None:
    """
    Auto-detects platform and converts ANY link (even watch links) into:
    (show_slug, show_id, serial_name, platform_name, canonical_url)
    """
    for p in PLATFORMS:
        if p.can_handle(url):
            res = p.parse_url(url)
            if res:
                # Some platforms might return 3 or 4 values
                if len(res) == 4:
                    slug, show_id, name, canonical_url = res
                else:
                    slug, show_id, name = res[:3]
                    canonical_url = url.split("?")[0].rstrip("/")
                    if canonical_url.endswith("/watch"):
                        canonical_url = canonical_url[:-6]
                return slug, show_id, name, p.NAME, canonical_url

    # Generic fallback
    clean_url = url.split("?")[0].rstrip("/")
    if clean_url.endswith("/watch"):
        clean_url = clean_url[:-6]

    parsed = urllib.parse.urlparse(clean_url)
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if parts:
        slug = parts[-1]
        name = " ".join(w.capitalize() for w in slug.split("-"))
        return slug, slug, name, "OTT", clean_url

    return None


def fetch_episodes(show_url: str, platform_name: str) -> list[dict]:
    clean_url = show_url.split("?")[0].rstrip("/")
    if clean_url.endswith("/watch"):
        clean_url = clean_url[:-6]
    handler = get_platform_handler(platform_name)
    return handler.fetch_episodes(clean_url)


def build_watch_link(show_slug: str, show_id: str, ep_name: str, ep_id: str, platform_name: str, raw_url: str = None) -> str:
    handler = get_platform_handler(platform_name)
    return handler.build_watch_link(show_slug, show_id, ep_name, ep_id, raw_url=raw_url)


def get_supported_platforms() -> list[str]:
    return [p.NAME for p in PLATFORMS]
