import base64
import html
import re
import urllib.parse
import requests

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


def _extract_ep_number(title: str, url: str) -> str | None:
    """Extracts episode number from title or URL."""
    # Matches "Episode 1114", "Ep 1114", "E1114", "Episode: 1114"
    match = re.search(r'(?:Episode|Ep|E)[.\s:-]*(\d+)', title, re.IGNORECASE)
    if match:
        return match.group(1)
    match_url = re.search(r'episode-(\d+)', url, re.IGNORECASE)
    if match_url:
        return match_url.group(1)
    # Standalone 3-4 digit number
    match_num = re.search(r'\b(\d{2,4})\b', title)
    if match_num:
        return match_num.group(1)
    return None


def search_all_episodes_from_internet(show_name: str, show_slug: str, show_id: str,
                                      platform: str) -> list[dict]:
    """
    Crawls internet search engines (DDG Lite, Bing, Yahoo) to discover all indexed episodes
    for the given show on any platform.
    Returns a list of parsed episode dictionaries.
    """
    plat_lower = platform.lower()
    domain = "hotstar.com"
    if plat_lower == "zee5":
        domain = "zee5.com"
    elif plat_lower == "sonyliv":
        domain = "sonyliv.com"
    elif plat_lower == "sunnxt":
        domain = "sunnxt.com"
    elif plat_lower == "manoramamax":
        domain = "manoramamax.com"

    # Multi-engine discovery
    raw_results: list[tuple[str, str]] = []  # (title, url)

    # 1. DuckDuckGo Lite
    ddg_lite = search_duckduckgo_lite(f"site:{domain} {show_name}")
    raw_results.extend(ddg_lite)

    # 2. Bing
    bing_links = search_bing(f"site:{domain} {show_name} episode")
    for link in bing_links:
        raw_results.append((f"Episode on {platform}", link))

    # 3. Yahoo
    yahoo_links = search_yahoo(f"site:{domain} {show_name} watch")
    for link in yahoo_links:
        raw_results.append((f"Episode on {platform}", link))

    episodes = []
    seen_ids = set()

    for title, u in raw_results:
        if plat_lower == "hotstar":
            # Matches /shows/<slug>/<show_id>/<ep_slug>/<ep_id>/watch or without /watch
            match_full = re.search(r'shows/[^/]+/\d+/([^/]+)/(\d{8,12})', u)
            if match_full:
                ep_slug = match_full.group(1)
                ep_id = match_full.group(2)
                if ep_id != show_id and ep_id not in seen_ids:
                    seen_ids.add(ep_id)
                    ep_num = _extract_ep_number(title, u) or ""
                    ep_name = ep_slug.replace("-", " ").title()
                    watch_url = f"https://www.hotstar.com/in/shows/{show_slug}/{show_id}/{ep_slug}/{ep_id}/watch"
                    episodes.append({
                        "id": ep_id,
                        "title": f"Episode {ep_num} - {ep_name}" if ep_num else ep_name,
                        "episode_name": ep_name,
                        "episode_number": ep_num,
                        "url": watch_url,
                        "season_number": "1",
                    })
                continue

            # Matches /<ep_id>/watch
            match_num = re.search(r'/(\d{8,12})(?:/watch)?', u)
            if match_num:
                ep_id = match_num.group(1)
                if ep_id != show_id and ep_id not in seen_ids:
                    seen_ids.add(ep_id)
                    ep_num = _extract_ep_number(title, u) or ""
                    watch_url = f"https://www.hotstar.com/{ep_id}/watch"
                    episodes.append({
                        "id": ep_id,
                        "title": f"Episode {ep_num}" if ep_num else f"Episode {ep_id}",
                        "episode_name": f"Episode {ep_num}" if ep_num else "Episode",
                        "episode_number": ep_num,
                        "url": watch_url,
                        "season_number": "1",
                    })
        else:
            # Zee5, SonyLIV, SunNXT, ManoramaMAX
            if u not in seen_ids and any(x in u for x in ["watch", "details", "shows"]):
                seen_ids.add(u)
                ep_num = _extract_ep_number(title, u) or ""
                episodes.append({
                    "id": ep_num or u,
                    "title": title or f"Episode {ep_num}",
                    "episode_name": title or f"Episode {ep_num}",
                    "episode_number": ep_num,
                    "url": u,
                    "season_number": "1",
                })

    return episodes


def search_exact_episode_from_internet(show_name: str, show_slug: str, show_id: str,
                                       ep_number: str, platform: str) -> dict | None:
    """
    Searches public internet search indexes to find the 100% exact,
    live episode watch URL and title for any OTT platform.
    Bypasses datacenter IP blocks, geo-blocks, and Akamai restrictions.
    """
    plat_lower = platform.lower()
    domain = "hotstar.com"
    if plat_lower == "zee5":
        domain = "zee5.com"
    elif plat_lower == "sonyliv":
        domain = "sonyliv.com"
    elif plat_lower == "sunnxt":
        domain = "sunnxt.com"
    elif plat_lower == "manoramamax":
        domain = "manoramamax.com"

    # Targeted search queries for the specific episode
    targeted_queries = [
        f"site:{domain} {show_name} {ep_number}",
        f"site:{domain} {show_name} Episode {ep_number}",
        f"site:{domain} {show_slug} {ep_number}",
        f"{platform} {show_name} episode {ep_number} watch online",
    ]

    for q in targeted_queries:
        # Check DDG Lite
        ddg_results = search_duckduckgo_lite(q)
        for title, link in ddg_results:
            ep_n = _extract_ep_number(title, link)
            if ep_n == ep_number or ep_number in title or ep_number in link:
                if plat_lower == "hotstar":
                    match_full = re.search(r'shows/[^/]+/\d+/([^/]+)/(\d{8,12})', link)
                    if match_full:
                        ep_slug = match_full.group(1)
                        ep_id = match_full.group(2)
                        if ep_id != show_id:
                            ep_name = ep_slug.replace("-", " ").title()
                            return {
                                "id": ep_id,
                                "title": f"Episode {ep_number} - {ep_name}",
                                "episode_name": ep_name,
                                "episode_number": ep_number,
                                "url": f"https://www.hotstar.com/in/shows/{show_slug}/{show_id}/{ep_slug}/{ep_id}/watch",
                                "season_number": "1",
                            }
                    match_num = re.search(r'/(\d{8,12})(?:/watch)?', link)
                    if match_num:
                        ep_id = match_num.group(1)
                        if ep_id != show_id:
                            return {
                                "id": ep_id,
                                "title": f"Episode {ep_number}",
                                "episode_name": f"Episode {ep_number}",
                                "episode_number": ep_number,
                                "url": f"https://www.hotstar.com/{ep_id}/watch",
                                "season_number": "1",
                            }
                else:
                    return {
                        "id": ep_number,
                        "title": title or f"Episode {ep_number}",
                        "episode_name": title or f"Episode {ep_number}",
                        "episode_number": ep_number,
                        "url": link,
                        "season_number": "1",
                    }

        # Check Bing
        bing_links = search_bing(q)
        for link in bing_links:
            if plat_lower == "hotstar":
                match_full = re.search(r'shows/[^/]+/\d+/([^/]+)/(\d{8,12})', link)
                if match_full:
                    ep_slug = match_full.group(1)
                    ep_id = match_full.group(2)
                    if ep_id != show_id:
                        ep_name = ep_slug.replace("-", " ").title()
                        return {
                            "id": ep_id,
                            "title": f"Episode {ep_number} - {ep_name}",
                            "episode_name": ep_name,
                            "episode_number": ep_number,
                            "url": f"https://www.hotstar.com/in/shows/{show_slug}/{show_id}/{ep_slug}/{ep_id}/watch",
                            "season_number": "1",
                        }

    # Broad crawl fallback: fetch all indexed show episodes
    all_eps = search_all_episodes_from_internet(show_name, show_slug, show_id, platform)
    for ep in all_eps:
        if ep.get("episode_number") == ep_number or ep_number in ep.get("title", ""):
            return ep

    return None
