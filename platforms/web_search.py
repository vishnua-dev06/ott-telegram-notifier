import base64
import html
import re
import urllib.parse
import requests
from platforms.base import HOTSTAR_EP_RE, has_episode_number

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
}


def decode_bing_u(u_val: str) -> str | None:
    """Decodes Bing's encoded destination URL from u=a1<BASE64> parameter."""
    try:
        raw = u_val
        if raw.startswith("a1"):
            raw = raw[2:]
        raw = raw.replace("-", "+").replace("_", "/")
        rem = len(raw) % 4
        if rem:
            raw += "=" * (4 - rem)
        decoded = base64.b64decode(raw).decode("utf-8", errors="ignore")
        if decoded.startswith("http://") or decoded.startswith("https://"):
            return decoded
    except Exception:
        pass
    return None


def search_duckduckgo_lite(query: str) -> list[tuple[str, str]]:
    """
    Queries DuckDuckGo Lite via POST.
    Returns a list of (title, destination_url).
    """
    results = []
    try:
        url = "https://lite.duckduckgo.com/lite/"
        resp = requests.post(url, data={"q": query}, headers=HEADERS, timeout=9)
        if resp.status_code == 200:
            # Matches <a class="result-link" href="...">Title</a>
            matches = re.findall(
                r'<a[^>]*class=[\'"]result-link[\'"][^>]*href=[\'"]([^\'"]+)[\'"][^>]*>([\s\S]*?)<\/a>',
                resp.text
            )
            for link, raw_title in matches:
                clean_title = html.unescape(re.sub(r'<[^>]+>', '', raw_title)).strip()
                # DuckDuckGo sometimes wraps in /l/?kh=-1&uddg=...
                if "uddg=" in link:
                    m = re.search(r'uddg=([^&]+)', link)
                    if m:
                        link = urllib.parse.unquote(m.group(1))
                link = link.split("?")[0]
                results.append((clean_title, link))
    except Exception as e:
        print(f"[!] DuckDuckGo Lite search error: {e}")
    return results


def search_duckduckgo_html(query: str) -> list[str]:
    """Queries DuckDuckGo HTML and extracts destination URLs."""
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    links = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        if resp.status_code == 200:
            matches = re.findall(r'uddg=(https%3A%2F%2F[^&"\']+)', resp.text)
            for m in matches:
                decoded = urllib.parse.unquote(m).split("?")[0]
                links.append(decoded)
    except Exception as e:
        print(f"[!] DuckDuckGo HTML search error: {e}")
    return links


def search_bing(query: str) -> list[str]:
    """Queries Bing HTML and unpacks base64 destination URLs."""
    url = f"https://www.bing.com/search?q={urllib.parse.quote(query)}"
    links = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        if resp.status_code == 200:
            # Extract direct links if present
            direct = re.findall(r'href="(https://www\.(?:hotstar|zee5|sonyliv|sunnxt|manoramamax)\.com/[^"<>]+)"', resp.text)
            for d in direct:
                links.append(d.split("?")[0])

            # Extract base64 u= params
            u_matches = re.findall(r'(?:[?&]|&amp;)u=([a-zA-Z0-9_\-]+)', resp.text)
            for u in u_matches:
                decoded = decode_bing_u(u)
                if decoded and any(domain in decoded for domain in ["hotstar.com", "zee5.com", "sonyliv.com", "sunnxt.com", "manoramamax.com"]):
                    links.append(decoded.split("?")[0])
    except Exception as e:
        print(f"[!] Bing search error: {e}")
    return links


def search_yahoo(query: str) -> list[str]:
    """Queries Yahoo Search and extracts redirect URLs."""
    url = f"https://search.yahoo.com/search?p={urllib.parse.quote(query)}"
    links = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        if resp.status_code == 200:
            matches = re.findall(r'/RU=([^/]+)/', resp.text)
            for m in matches:
                decoded = urllib.parse.unquote(m).split("?")[0]
                if any(domain in decoded for domain in ["hotstar.com", "zee5.com", "sonyliv.com", "sunnxt.com", "manoramamax.com"]):
                    links.append(decoded)
    except Exception as e:
        print(f"[!] Yahoo search error: {e}")
    return links


DOMAINS = {
    "hotstar": "hotstar.com",
    "zee5": "zee5.com",
    "sonyliv": "sonyliv.com",
    "sunnxt": "sunnxt.com",
    "manoramamax": "manoramamax.com",
}


def _extract_ep_number(title: str, url: str) -> str | None:
    """Extracts the episode number from a result title or URL (never from a long content id)."""
    match = re.search(r'(?:Episode|Ep|E)[.\s:-]*(\d{1,5})(?!\d)', title or "", re.IGNORECASE)
    if match:
        return match.group(1)
    match_url = re.search(r'episode-(\d{1,5})(?!\d)', url or "", re.IGNORECASE)
    if match_url:
        return match_url.group(1)
    match_num = re.search(r'(?<!\d)(\d{2,4})(?!\d)', title or "")
    if match_num:
        return match_num.group(1)
    return None


def _hotstar_episode(title: str, link: str, show_slug: str, show_id: str) -> dict | None:
    """
    Turns a search result into an episode dict ONLY if the URL is a real episode of this show:
    /shows/<slug>/<show_id>/<ep-slug>/<ep_id>  with the SAME show_id and a different 8-12 digit ep id.
    """
    m = HOTSTAR_EP_RE.search(link)
    if not m:
        return None
    _slug, link_show_id, ep_slug, ep_id = m.groups()
    if link_show_id != str(show_id) or ep_id == str(show_id):
        return None
    ep_num = _extract_ep_number(title, ep_slug) or ""
    ep_name = ep_slug.replace("-", " ").title()
    return {
        "id": ep_id,
        "title": f"Episode {ep_num} - {ep_name}" if ep_num else ep_name,
        "episode_name": ep_name,
        "episode_number": ep_num,
        "url": f"https://www.hotstar.com/in/shows/{show_slug}/{show_id}/{ep_slug}/{ep_id}/watch",
        "season_number": "1",
        "_result_title": title,
    }


def _generic_episode(title: str, link: str, show_slug: str, domain: str) -> dict | None:
    """Zee5 / SonyLIV / SunNXT / ManoramaMAX: link must be on the right domain and mention the show."""
    if domain not in link or not any(x in link for x in ("watch", "details", "shows", "detail", "programs", "tv-shows")):
        return None
    if show_slug and show_slug.lower() not in link.lower():
        return None
    ep_num = _extract_ep_number(title, link) or ""
    return {
        "id": link,
        "title": title or (f"Episode {ep_num}" if ep_num else "Episode"),
        "episode_name": title or f"Episode {ep_num}",
        "episode_number": ep_num,
        "url": link,
        "season_number": "1",
        "_result_title": title,
    }


def _collect_results(queries_ddg: list[str], queries_bing: list[str], queries_yahoo: list[str], platform: str) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    for q in queries_ddg:
        results.extend(search_duckduckgo_lite(q))
    for q in queries_bing:
        results.extend((f"Episode on {platform}", l) for l in search_bing(q))
    for q in queries_yahoo:
        results.extend((f"Episode on {platform}", l) for l in search_yahoo(q))
    return results


def search_all_episodes_from_internet(show_name: str, show_slug: str, show_id: str, platform: str) -> list[dict]:
    """Discovers indexed episodes of THIS show through public search engines."""
    plat = platform.lower()
    domain = DOMAINS.get(plat, "hotstar.com")
    raw = _collect_results(
        [f"site:{domain} {show_name}"],
        [f"site:{domain} {show_name} episode"],
        [f"site:{domain} {show_name} watch"],
        platform,
    )
    episodes, seen = [], set()
    for title, link in raw:
        ep = (_hotstar_episode(title, link, show_slug, show_id) if plat == "hotstar"
              else _generic_episode(title, link, show_slug, domain))
        if ep and ep["id"] not in seen:
            seen.add(ep["id"])
            episodes.append(ep)
    return episodes


def search_exact_episode_from_internet(show_name: str, show_slug: str, show_id: str,
                                       ep_number: str, platform: str) -> dict | None:
    """
    Finds the live watch URL of ONE specific episode.
    A result is accepted only if (a) the URL belongs to this show and (b) the episode number
    appears as a whole number in the result title / URL slug. Otherwise returns None so the
    caller shows the show page instead of a wrong episode.
    """
    plat = platform.lower()
    domain = DOMAINS.get(plat, "hotstar.com")
    queries = [
        f"site:{domain} {show_name} Episode {ep_number}",
        f"site:{domain} {show_name} {ep_number}",
        f"site:{domain} {show_slug} {ep_number}",
    ]

    def accept(ep: dict | None) -> dict | None:
        if not ep:
            return None
        blob = f"{ep.get('_result_title', '')} {ep['url']}"
        # strip the numeric ids from the URL before matching the episode number
        blob = re.sub(r"/\d{8,12}", "", blob)
        if has_episode_number(blob, ep_number):
            ep["episode_number"] = ep_number
            if not re.search(r"(?<!\d)" + re.escape(ep_number) + r"(?!\d)", ep["title"]):
                ep["title"] = f"Episode {ep_number} - {ep['title']}"
            ep.pop("_result_title", None)
            return ep
        return None

    for q in queries:
        candidates = list(search_duckduckgo_lite(q)) + [(f"Episode on {platform}", l) for l in search_bing(q)]
        for title, link in candidates:
            ep = (_hotstar_episode(title, link, show_slug, show_id) if plat == "hotstar"
                  else _generic_episode(title, link, show_slug, domain))
            hit = accept(ep)
            if hit:
                return hit

    # Broad crawl fallback (same strict rules)
    for ep in search_all_episodes_from_internet(show_name, show_slug, show_id, platform):
        hit = accept(ep)
        if hit:
            return hit
    return None
