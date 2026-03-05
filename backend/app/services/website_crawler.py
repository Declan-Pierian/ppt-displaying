"""Crawl a website using Playwright (sync API) and BeautifulSoup.

Enhanced crawler that uses multiple discovery strategies:
1. Sitemap.xml parsing (finds all pages the site declares)
2. Navigation link extraction (menus, header, footer)
3. Page body link extraction with scrolling (lazy-loaded content)
4. Breadth-first recursive crawl across all discovered pages

Runs Playwright in a SUBPROCESS to avoid Windows asyncio event loop conflicts.
"""

import os
import sys
import json
import logging
import subprocess
import re
from urllib.parse import urlparse, urljoin

logger = logging.getLogger(__name__)


def _normalise_url(url: str) -> str:
    """Strip fragment and trailing slash for dedup. Keep query params."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    base = f"{parsed.scheme}://{parsed.netloc}{path}"
    if parsed.query:
        base += f"?{parsed.query}"
    return base


def _is_same_domain(base_url: str, candidate: str) -> bool:
    """Check if candidate URL belongs to the same domain (incl. subdomains)."""
    try:
        base_host = urlparse(base_url).netloc.lower().replace("www.", "")
        cand_host = urlparse(candidate).netloc.lower().replace("www.", "")
        # Exact match or subdomain
        return cand_host == base_host or cand_host.endswith("." + base_host)
    except Exception:
        return False


_SKIP_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
    ".css", ".js", ".zip", ".tar", ".gz", ".mp4", ".mp3", ".avi",
    ".mov", ".woff", ".woff2", ".ttf", ".eot", ".xml", ".json",
    ".rss", ".atom", ".txt", ".csv", ".xls", ".xlsx", ".doc", ".docx",
}

_SKIP_PATH_PATTERNS = (
    "/wp-json", "/feed", "/xmlrpc", "/wp-login", "/wp-admin",
    "/cart", "/checkout", "/account", "/login", "/signup", "/register",
    "/api/", "/_next/", "/static/", "/assets/",
    "#", "javascript:", "mailto:", "tel:",
)


def _is_page_url(url: str) -> bool:
    """Return True if the URL looks like a navigable page (not an asset)."""
    parsed = urlparse(url)
    if not parsed.scheme.startswith("http"):
        return False
    ext = os.path.splitext(parsed.path)[1].lower()
    if ext in _SKIP_EXTENSIONS:
        return False
    url_lower = url.lower()
    for pat in _SKIP_PATH_PATTERNS:
        if pat in url_lower:
            return False
    return True


def _extract_page_content(html: str) -> dict:
    """Use BeautifulSoup to extract rich structured content from HTML."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(["script", "style", "noscript", "svg"]):
        tag.decompose()

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    meta_desc = ""
    meta = soup.find("meta", attrs={"name": "description"})
    if not meta:
        meta = soup.find("meta", attrs={"property": "og:description"})
    if meta and meta.get("content"):
        meta_desc = meta["content"].strip()

    # Extract ALL headings with their following content
    sections = []
    seen_headings = set()
    for heading in soup.find_all(["h1", "h2", "h3", "h4"]):
        heading_text = heading.get_text(strip=True)
        if not heading_text or heading_text in seen_headings:
            continue
        seen_headings.add(heading_text)

        following_text = []
        for sibling in heading.find_next_siblings():
            if sibling.name in ("h1", "h2", "h3", "h4"):
                break
            text = sibling.get_text(strip=True)
            if text and len(text) > 10:
                following_text.append(text[:300])
            if len(following_text) >= 6:
                break

        sections.append({
            "heading": heading_text,
            "level": heading.name,
            "content": following_text,
        })

    # Key paragraphs from main/article or body
    key_paragraphs = []
    main_container = soup.find("main") or soup.find("article") or soup.find("body")
    if main_container:
        for p in main_container.find_all(["p", "li"]):
            text = p.get_text(strip=True)
            if len(text) > 30:
                key_paragraphs.append(text[:300])
            if len(key_paragraphs) >= 15:
                break

    # Navigation links
    nav_items = []
    for nav in soup.find_all(["nav", "header"]):
        for a in nav.find_all("a"):
            label = a.get_text(strip=True)
            if label and 2 < len(label) < 50:
                nav_items.append(label)

    # Cards / feature items (common in product pages)
    cards = []
    card_selectors = soup.find_all(
        class_=re.compile(r"card|feature|product|item|service|benefit", re.I)
    )
    for card in card_selectors[:20]:
        card_text = card.get_text(strip=True)
        if 20 < len(card_text) < 500:
            cards.append(card_text[:300])

    # Lists
    list_items = []
    for ul in soup.find_all(["ul", "ol"]):
        for li in ul.find_all("li", recursive=False):
            text = li.get_text(strip=True)
            if 10 < len(text) < 200:
                list_items.append(text)
            if len(list_items) >= 20:
                break

    return {
        "title": title,
        "meta_description": meta_desc,
        "sections": sections,
        "key_paragraphs": key_paragraphs,
        "nav_items": list(dict.fromkeys(nav_items))[:15],
        "cards": cards[:10],
        "list_items": list_items[:15],
    }


def _try_fetch_sitemap(page, base_url: str) -> list[str]:
    """Try to fetch and parse sitemap.xml for URL discovery."""
    urls = []
    sitemap_urls = [
        f"{base_url}/sitemap.xml",
        f"{base_url}/sitemap_index.xml",
        f"{base_url}/sitemap",
    ]
    for sitemap_url in sitemap_urls:
        try:
            response = page.goto(sitemap_url, wait_until="domcontentloaded", timeout=10000)
            if response and response.status == 200:
                content = page.content()
                # Extract <loc> tags from XML
                loc_matches = re.findall(r"<loc>\s*(.*?)\s*</loc>", content)
                urls.extend(loc_matches)
                if urls:
                    print(f"INFO:Found {len(urls)} URLs in sitemap: {sitemap_url}", file=sys.stderr, flush=True)
                    break
        except Exception:
            continue
    return urls


def _discover_links_aggressive(page, base_url: str, visited: set, known: set) -> list[str]:
    """Aggressively extract all same-domain links from current page."""
    new_links = []
    try:
        # Scroll to bottom to trigger lazy-loaded content
        page.evaluate("""
            async () => {
                const delay = ms => new Promise(r => setTimeout(r, ms));
                for (let i = 0; i < 5; i++) {
                    window.scrollBy(0, window.innerHeight);
                    await delay(300);
                }
                window.scrollTo(0, 0);
            }
        """)
        page.wait_for_timeout(1000)

        # Method 1: All <a href> links (resolved by browser)
        links = page.eval_on_selector_all(
            "a[href]",
            "elements => elements.map(e => e.href)",
        )

        # Method 2: Also get href attributes from onclick/data-href etc.
        extra_links = page.eval_on_selector_all(
            "[data-href], [data-url], [data-link]",
            """elements => elements.map(e =>
                e.getAttribute('data-href') ||
                e.getAttribute('data-url') ||
                e.getAttribute('data-link') || ''
            )""",
        )
        links.extend(extra_links)

        for link in links:
            if not link or not link.startswith("http"):
                continue
            norm = _normalise_url(link)
            if (
                norm not in visited
                and norm not in known
                and _is_same_domain(base_url, norm)
                and _is_page_url(norm)
            ):
                new_links.append(norm)
                known.add(norm)

    except Exception as e:
        print(f"WARN:Link discovery error: {e}", file=sys.stderr, flush=True)

    return new_links


def _crawl_impl(
    url: str,
    presentation_id: int,
    media_dir: str,
    max_pages: int = 0,
) -> dict:
    """Core crawl logic — must run in its own process on Windows."""
    from playwright.sync_api import sync_playwright

    HARD_CAP = 50
    screenshots_dir = os.path.join(media_dir, "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)

    base_url = url.rstrip("/")
    effective_limit = max_pages if max_pages > 0 else HARD_CAP

    visited = set()
    known = set()
    pages_data = []
    urls_to_visit = [_normalise_url(base_url)]
    known.add(urls_to_visit[0])

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        # ── Phase 0: Try sitemap.xml for URL discovery ──
        print("INFO:Trying sitemap.xml discovery...", file=sys.stderr, flush=True)
        sitemap_urls = _try_fetch_sitemap(page, base_url)
        for surl in sitemap_urls:
            norm = _normalise_url(surl)
            if (
                norm not in known
                and _is_same_domain(base_url, norm)
                and _is_page_url(norm)
            ):
                urls_to_visit.append(norm)
                known.add(norm)

        # ── Phase 1: Crawl pages ──
        idx = 0
        while urls_to_visit and idx < effective_limit:
            page_url = urls_to_visit.pop(0)
            norm = _normalise_url(page_url)
            if norm in visited:
                continue
            visited.add(norm)

            try:
                page.goto(page_url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(2000)  # Let JS fully render

                # Discover more links (aggressive: scroll + multiple methods)
                new_links = _discover_links_aggressive(page, base_url, visited, known)
                urls_to_visit.extend(new_links)

                # Screenshot (viewport only, not full page)
                screenshot_filename = f"page_{idx + 1}.png"
                screenshot_path = os.path.join(screenshots_dir, screenshot_filename)
                page.screenshot(path=screenshot_path, full_page=False)

                # Extract content
                html = page.content()
                content = _extract_page_content(html)
                page_title = page.title() or content.get("title", "")

                pages_data.append({
                    "page_index": idx,
                    "page_number": idx + 1,
                    "page_url": page_url,
                    "page_title": page_title,
                    "screenshot_path": f"media/screenshots/{screenshot_filename}",
                    "content": content,
                })
                idx += 1
                total_est = min(len(urls_to_visit) + idx, effective_limit)
                print(
                    f"PROGRESS:{idx}:{max(total_est, idx)}:Captured page {idx}: {page_url[:70]}",
                    file=sys.stderr, flush=True,
                )

            except Exception as e:
                print(f"WARN:Failed to capture {page_url}: {e}", file=sys.stderr, flush=True)
                continue

        browser.close()

    print(f"INFO:Crawl complete. {len(pages_data)} pages captured, {len(known)} URLs discovered.", file=sys.stderr, flush=True)

    # Build result
    site_title = pages_data[0]["page_title"] if pages_data else urlparse(url).netloc

    result = {
        "presentation_id": presentation_id,
        "title": site_title,
        "source_url": url,
        "slide_width_emu": 12192000,
        "slide_height_emu": 6858000,
        "total_pages_crawled": len(pages_data),
        "slides": [],
    }

    for pd in pages_data:
        result["slides"].append({
            "slide_index": pd["page_index"],
            "slide_number": pd["page_number"],
            "page_url": pd["page_url"],
            "page_title": pd["page_title"],
            "screenshot_path": pd["screenshot_path"],
            "content": pd["content"],
            "background": {"type": "none"},
            "shapes": [],
            "notes": None,
        })

    return result


def crawl_website(
    url: str,
    presentation_id: int,
    media_dir: str,
    max_pages: int = 0,
    progress_callback=None,
) -> dict:
    """Crawl a website by launching Playwright in a SEPARATE PROCESS."""
    config = {
        "url": url,
        "presentation_id": presentation_id,
        "media_dir": media_dir,
        "max_pages": max_pages,
    }
    config_path = os.path.join(media_dir, "_crawl_config.json")
    result_path = os.path.join(media_dir, "_crawl_result.json")

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f)

    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    proc = subprocess.Popen(
        [sys.executable, "-m", "app.services.website_crawler", config_path, result_path],
        cwd=backend_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    for line in proc.stderr:
        line = line.strip()
        if line.startswith("PROGRESS:") and progress_callback:
            parts = line.split(":", 3)
            if len(parts) >= 4:
                try:
                    current = int(parts[1])
                    total = int(parts[2])
                    message = parts[3]
                    progress_callback(current, total, message)
                except (ValueError, IndexError):
                    pass
        elif line.startswith("WARN:"):
            logger.warning("Crawler: %s", line[5:])
        elif line.startswith("INFO:"):
            logger.info("Crawler: %s", line[5:])

    proc.wait(timeout=600)

    if proc.returncode != 0:
        stderr_remaining = proc.stderr.read() if proc.stderr else ""
        raise RuntimeError(f"Crawler subprocess failed (exit code {proc.returncode}): {stderr_remaining}")

    if not os.path.exists(result_path):
        raise RuntimeError("Crawler subprocess did not produce a result file")

    with open(result_path, "r", encoding="utf-8") as f:
        result = json.load(f)

    for path in (config_path, result_path):
        try:
            os.remove(path)
        except OSError:
            pass

    return result


# ── CLI entry point: called by the subprocess ──
if __name__ == "__main__":
    config_path = sys.argv[1]
    result_path = sys.argv[2]

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    result = _crawl_impl(
        url=config["url"],
        presentation_id=config["presentation_id"],
        media_dir=config["media_dir"],
        max_pages=config.get("max_pages", 0),
    )

    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)

    print(f"OK:Crawled {len(result['slides'])} pages", file=sys.stderr, flush=True)