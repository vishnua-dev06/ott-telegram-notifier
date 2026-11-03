import re

COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def slugify(text: str) -> str:
    """Convert text into a clean URL-friendly slug."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def parse_episode_details(raw_title: str) -> tuple[str, str]:
    """
    Extracts episode number and clean episode name.
    Example: 'E1116 - Nandana Arrives to Arrest Abhi' -> ('1116', 'Nandana Arrives to Arrest Abhi')
    """
    match = re.search(r"(?:^|\b)(?:E|Ep|Episode)?\s*(\d{1,5})\s*[-:|–—]\s*(.*)$", raw_title, re.IGNORECASE)
    if match:
        return match.group(1).strip(), match.group(2).strip()

    fallback_num = re.search(r"\b(\d{1,5})\b", raw_title)
    ep_num = fallback_num.group(1) if fallback_num else "Latest"
    return ep_num, raw_title.strip()


def extract_thumbnail_url(ep_entry: dict) -> str | None:
    """Extracts highest quality thumbnail from metadata dictionary."""
    thumb = ep_entry.get("thumbnail")
    if thumb and isinstance(thumb, str) and thumb.startswith("http"):
        return thumb

    thumbs = ep_entry.get("thumbnails")
    if thumbs and isinstance(thumbs, list):
        for t in reversed(thumbs):
            if isinstance(t, dict) and t.get("url"):
                return t["url"]

    poster = ep_entry.get("poster")
    if poster and isinstance(poster, str) and poster.startswith("http"):
        return poster

    return None



# ---------------------------------------------------------------------------
# Link-correctness helpers (shared by all platforms)
# ---------------------------------------------------------------------------
# Matches both  .../shows/<show-slug>/<show_id>/<ep-slug>/<ep_id>/watch  and without /watch
HOTSTAR_EP_RE = re.compile(
    r"hotstar\.com/(?:[a-z]{2}/)?shows/([^/?#\s\"']+)/(\d+)/([^/?#\s\"']+)/(\d{8,12})(?:/watch)?"
)


def has_episode_number(text: str, ep_number: str) -> bool:
    """
    True only when `ep_number` appears as a *whole* number (not inside a longer
    number such as a 10-digit content id). '1116' matches 'Episode 1116' but not
    '1641039866' or '11160'.
    """
    if not text or not ep_number:
        return False
    return re.search(rf"(?<!\d){re.escape(str(ep_number))}(?!\d)", str(text)) is not None


def episode_sort_key(ep: dict) -> int:
    """Sort key so the highest episode number comes first (real 'latest')."""
    raw = str(ep.get("episode_number") or "")
    if not raw.isdigit():
        raw, _ = parse_episode_details(str(ep.get("title", "")))
    return int(raw) if str(raw).isdigit() else -1
