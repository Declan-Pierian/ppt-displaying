"""Crawl a website using Playwright (sync API) and BeautifulSoup.

Enhanced crawler that uses multiple discovery strategies:
1. Sitemap.xml parsing (finds all pages the site declares)
2. Robots.txt sitemap references
3. Navigation link extraction (menus, header, footer)
4. Page body link extraction with scrolling (lazy-loaded content)
5. Common URL pattern guessing (about, contact, services, etc.)
6. Breadth-first recursive crawl across all discovered pages

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

# Common page paths to try when other discovery methods find few pages
_COMMON_PATHS = [
    "/about", "/about-us", "/contact", "/contact-us",
    "/services", "/products", "/features", "/solutions",
    "/pricing", "/team", "/careers", "/blog",
    "/faq", "/help", "/support", "/privacy", "/terms",
    "/portfolio", "/work", "/case-studies", "/clients",
    "/partners", "/resources", "/news", "/events",
    "/technology", "/platform", "/industries",
]


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


def _extract_page_content(html: str, page_url: str = "") -> dict:
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
        class_=re.compile(r"card|feature|product|item|service|benefit|solution|offering", re.I)
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

    # Hero / banner text
    hero_text = []
    for selector in [
        soup.find(class_=re.compile(r"hero|banner|jumbotron|masthead", re.I)),
        soup.find(id=re.compile(r"hero|banner", re.I)),
    ]:
        if selector:
            for el in selector.find_all(["h1", "h2", "p", "span"]):
                text = el.get_text(strip=True)
                if text and len(text) > 5:
                    hero_text.append(text[:200])

    # ── Extract meaningful images WITH their associated content ──
    # Strategy: for each <img>, walk up the DOM to find its containing
    # "card" or "item" block, then extract ALL text from that block.
    # This preserves the image ↔ person/product/feature association.
    images = []
    seen_srcs = set()

    _skip_img_patterns = (
        "data:image/gif", "data:image/svg", "data:image/png;base64,iVBOR",
        "pixel", "spacer", "blank", "transparent", "1x1",
        "facebook.com", "twitter.com", "google-analytics", "doubleclick",
        "gravatar.com/avatar", ".svg", "wp-emoji", "emoji", "smilies",
        "loading", "spinner", "placeholder",
    )

    def _is_item_container(tag):
        """Heuristic: is this tag a meaningful content container (card, item, person)?"""
        if tag.name not in ("div", "li", "article", "section", "a", "figure", "td"):
            return False
        cls = " ".join(tag.get("class", []))
        # Common card/item class patterns
        if re.search(r'card|member|team|person|profile|staff|employee|'
                      r'item|product|feature|service|post|entry|col|'
                      r'grid-item|portfolio|testimonial|author|speaker',
                      cls, re.I):
            return True
        # Or if the container has both an image and some text (generic card)
        has_img = tag.find("img") is not None
        text_len = len(tag.get_text(strip=True))
        if has_img and 10 < text_len < 600:
            return True
        return False

    def _find_content_container(img_tag):
        """Walk up from an <img> to find its meaningful content container."""
        current = img_tag.parent
        depth = 0
        while current and depth < 6:
            if current.name in ("body", "html", "main", "header", "footer"):
                break
            if _is_item_container(current):
                return current
            current = current.parent
            depth += 1
        # Fallback: return immediate parent if it has some text
        parent = img_tag.parent
        if parent and len(parent.get_text(strip=True)) > 5:
            return parent
        return None

    def _extract_container_texts(container) -> dict:
        """Extract structured text from a content container."""
        result = {"name": "", "role": "", "description": ""}

        # Try to find a heading (person name, product name, etc.)
        heading = container.find(["h1", "h2", "h3", "h4", "h5", "h6"])
        if heading:
            result["name"] = heading.get_text(strip=True)[:120]

        # Try to find a role/subtitle — typically a <p>, <span>, or <small> right after heading
        # or elements with class containing "title", "role", "position", "subtitle"
        role_el = container.find(
            class_=re.compile(r'title|role|position|subtitle|designation|job', re.I)
        )
        if role_el:
            result["role"] = role_el.get_text(strip=True)[:100]

        # If no heading found, try <strong> or first text element
        if not result["name"]:
            strong = container.find("strong")
            if strong:
                result["name"] = strong.get_text(strip=True)[:120]

        # If still no name, use the first meaningful line of text
        if not result["name"]:
            for el in container.find_all(["span", "p", "div", "a"], recursive=True):
                txt = el.get_text(strip=True)
                if 3 < len(txt) < 80 and not txt.startswith("http"):
                    result["name"] = txt
                    break

        # Get remaining description text (exclude what we already captured)
        all_text = container.get_text(separator="\n", strip=True)
        lines = [l.strip() for l in all_text.split("\n") if l.strip()]
        desc_parts = []
        for line in lines:
            if line == result["name"] or line == result["role"]:
                continue
            if 5 < len(line) < 200:
                desc_parts.append(line)
        result["description"] = " | ".join(desc_parts[:3])

        return result

    def _get_best_src(img_tag):
        """Get the best image source URL from an img tag, trying multiple attributes."""
        # Priority: src, data-src, data-lazy-src, data-original, srcset (first entry)
        for attr in ("src", "data-src", "data-lazy-src", "data-original",
                      "data-bg", "data-image"):
            val = img_tag.get(attr, "").strip()
            if val and not val.startswith("data:"):
                return val

        # Try srcset — pick the largest image
        srcset = img_tag.get("srcset", "").strip()
        if srcset:
            entries = [e.strip().split()[0] for e in srcset.split(",") if e.strip()]
            if entries:
                return entries[-1]  # Last entry is typically the largest

        # Fallback to src even if it's data: (will be filtered later)
        return img_tag.get("src", "").strip()

    for img_tag in soup.find_all("img"):
        src = _get_best_src(img_tag)
        if not src or src.startswith("data:image/gif") or src.startswith("data:image/svg"):
            continue

        # Skip tiny images
        w = img_tag.get("width", "")
        h = img_tag.get("height", "")
        try:
            if w and int(str(w).replace("px", "")) < 40:
                continue
            if h and int(str(h).replace("px", "")) < 40:
                continue
        except (ValueError, TypeError):
            pass

        # Resolve to absolute URL
        if page_url and not src.startswith(("http://", "https://")):
            src = urljoin(page_url, src)

        if not src.startswith(("http://", "https://")):
            continue
        if src in seen_srcs:
            continue

        src_lower = src.lower()
        if any(pat in src_lower for pat in _skip_img_patterns):
            continue

        seen_srcs.add(src)
        alt = img_tag.get("alt", "").strip()

        # Walk up DOM to find content container & extract associated text
        container = _find_content_container(img_tag)
        assoc_text = {"name": "", "role": "", "description": ""}
        if container:
            assoc_text = _extract_container_texts(container)

        # Use alt text as fallback for name
        if not assoc_text["name"] and alt:
            assoc_text["name"] = alt

        images.append({
            "src": src,
            "alt": alt,
            "name": assoc_text["name"],
            "role": assoc_text["role"],
            "description": assoc_text["description"],
        })

        if len(images) >= 60:  # Allow many images for team pages etc.
            break

    # ── Also extract CSS background-image URLs from people/team containers ──
    if len(images) < 60:
        for el in soup.find_all(style=re.compile(r'background(?:-image)?\s*:', re.I)):
            if len(images) >= 60:
                break
            style = el.get("style", "")
            bg_match = re.search(r'url\(["\']?(https?://[^"\')\s]+)["\']?\)', style)
            if not bg_match:
                continue
            bg_src = bg_match.group(1)
            if bg_src in seen_srcs:
                continue
            bg_lower = bg_src.lower()
            if any(pat in bg_lower for pat in _skip_img_patterns):
                continue
            # Only include if it's in a meaningful container
            container = _find_content_container(el) or el
            assoc_text = _extract_container_texts(container)
            if not assoc_text["name"]:
                # Skip background images without associated text
                continue
            seen_srcs.add(bg_src)
            images.append({
                "src": bg_src,
                "alt": "",
                "name": assoc_text["name"],
                "role": assoc_text["role"],
                "description": assoc_text["description"],
            })

    return {
        "title": title,
        "meta_description": meta_desc,
        "sections": sections,
        "key_paragraphs": key_paragraphs,
        "nav_items": list(dict.fromkeys(nav_items))[:15],
        "cards": cards[:10],
        "list_items": list_items[:15],
        "hero_text": hero_text[:5],
        "images": images,
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


def _try_fetch_robots_sitemaps(page, base_url: str) -> list[str]:
    """Try to discover sitemap URLs from robots.txt."""
    sitemap_urls = []
    try:
        response = page.goto(f"{base_url}/robots.txt", wait_until="domcontentloaded", timeout=10000)
        if response and response.status == 200:
            content = page.content()
            # Extract Sitemap: directives
            for match in re.findall(r"Sitemap:\s*(\S+)", content, re.IGNORECASE):
                sitemap_urls.append(match.strip())
            if sitemap_urls:
                print(f"INFO:Found {len(sitemap_urls)} sitemap refs in robots.txt", file=sys.stderr, flush=True)
    except Exception:
        pass
    return sitemap_urls


def _try_common_paths(page, base_url: str, visited: set, known: set) -> list[str]:
    """Try common page paths to discover pages not linked from navigation."""
    new_urls = []
    for path in _COMMON_PATHS:
        candidate = _normalise_url(f"{base_url}{path}")
        if candidate in visited or candidate in known:
            continue
        try:
            response = page.goto(candidate, wait_until="domcontentloaded", timeout=8000)
            if response and 200 <= response.status < 400:
                # Verify it's actually a different page (not a redirect to homepage)
                final_url = _normalise_url(page.url)
                if final_url not in visited and final_url not in known:
                    new_urls.append(candidate)
                    known.add(candidate)
                    print(f"INFO:Discovered common path: {path}", file=sys.stderr, flush=True)
        except Exception:
            continue
    return new_urls


def _discover_links_aggressive(page, base_url: str, visited: set, known: set) -> list[str]:
    """Aggressively extract all same-domain links from current page."""
    new_links = []
    try:
        # Scroll through the entire page to trigger lazy-loaded content
        page.evaluate("""
            async () => {
                const delay = ms => new Promise(r => setTimeout(r, ms));
                const totalHeight = document.body.scrollHeight;
                const step = window.innerHeight;
                for (let pos = 0; pos < totalHeight; pos += step) {
                    window.scrollTo(0, pos);
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

        # Method 2: Data attributes
        extra_links = page.eval_on_selector_all(
            "[data-href], [data-url], [data-link]",
            """elements => elements.map(e =>
                e.getAttribute('data-href') ||
                e.getAttribute('data-url') ||
                e.getAttribute('data-link') || ''
            )""",
        )
        links.extend(extra_links)

        # Method 3: onclick handlers with URLs
        onclick_links = page.eval_on_selector_all(
            "[onclick]",
            """elements => {
                const urls = [];
                elements.forEach(e => {
                    const onclick = e.getAttribute('onclick') || '';
                    const match = onclick.match(/(?:location|href|navigate).*?['"]([^'"]+)['"]/);
                    if (match) urls.push(match[1]);
                });
                return urls;
            }""",
        )
        for link in onclick_links:
            if link.startswith("/"):
                parsed = urlparse(base_url)
                link = f"{parsed.scheme}://{parsed.netloc}{link}"
            links.append(link)

        # Method 4: Footer links (often contain important pages)
        footer_links = page.eval_on_selector_all(
            "footer a[href], .footer a[href], [role='contentinfo'] a[href]",
            "elements => elements.map(e => e.href)",
        )
        links.extend(footer_links)

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


def _crawl_one_page(url: str, presentation_id: int, media_dir: str) -> dict:
    """Capture exactly ONE page — no discovery, no loops, no other pages.

    This is a completely separate code path from the multi-page crawler.
    It opens the browser, visits the single URL, screenshots it, extracts
    content, closes the browser, and returns.
    """
    from playwright.sync_api import sync_playwright

    print(f"INFO:=== SINGLE PAGE MODE === Capturing ONLY: {url}", file=sys.stderr, flush=True)

    screenshots_dir = os.path.join(media_dir, "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)

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

        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)

        # Scroll through the entire page to trigger lazy-loaded images/content
        page.evaluate("""
            async () => {
                const delay = ms => new Promise(r => setTimeout(r, ms));
                const totalHeight = document.body.scrollHeight;
                const step = window.innerHeight;
                for (let pos = 0; pos < totalHeight; pos += step) {
                    window.scrollTo(0, pos);
                    await delay(400);
                }
                // Scroll back to top
                window.scrollTo(0, 0);
            }
        """)
        page.wait_for_timeout(2000)  # Wait for lazy images to load after scrolling

        # Screenshot
        screenshot_path = os.path.join(screenshots_dir, "page_1.png")
        page.screenshot(path=screenshot_path, full_page=False)

        # Extract content
        html = page.content()
        content = _extract_page_content(html, page_url=url)
        page_title = page.title() or content.get("title", "")

        print(f"PROGRESS:1:1:Captured single page: {url[:70]}", file=sys.stderr, flush=True)

        browser.close()

    print(f"INFO:Single-page crawl complete. 1 page captured.", file=sys.stderr, flush=True)

    return {
        "presentation_id": presentation_id,
        "title": page_title or urlparse(url).netloc,
        "source_url": url,
        "slide_width_emu": 12192000,
        "slide_height_emu": 6858000,
        "total_pages_crawled": 1,
        "slides": [{
            "slide_index": 0,
            "slide_number": 1,
            "page_url": url,
            "page_title": page_title,
            "screenshot_path": "media/screenshots/page_1.png",
            "content": content,
            "background": {"type": "none"},
            "shapes": [],
            "notes": None,
        }],
    }


def _crawl_impl(
    url: str,
    presentation_id: int,
    media_dir: str,
    max_pages: int = 0,
    single_page: bool = False,
) -> dict:
    """Core crawl logic — must run in its own process on Windows."""

    # ── SINGLE PAGE: use the dedicated simple function ──
    if single_page or max_pages == 1:
        return _crawl_one_page(url, presentation_id, media_dir)

    # ── MULTI-PAGE: full discovery + BFS crawl ──
    from playwright.sync_api import sync_playwright

    HARD_CAP = 50
    screenshots_dir = os.path.join(media_dir, "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)

    base_url = url.rstrip("/")
    effective_limit = max_pages if max_pages > 0 else HARD_CAP

    print(
        f"INFO:_crawl_impl FULL-SITE mode: max_pages={max_pages}, "
        f"effective_limit={effective_limit}, url={url}",
        file=sys.stderr, flush=True,
    )

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

        # ── Phase 0: Discovery — sitemap, robots.txt ──
        print("INFO:Phase 0 — URL discovery via sitemap, robots.txt...", file=sys.stderr, flush=True)

        # Try robots.txt for sitemap references
        robots_sitemaps = _try_fetch_robots_sitemaps(page, base_url)
        for sm_url in robots_sitemaps:
            try:
                response = page.goto(sm_url, wait_until="domcontentloaded", timeout=10000)
                if response and response.status == 200:
                    content = page.content()
                    loc_matches = re.findall(r"<loc>\s*(.*?)\s*</loc>", content)
                    for loc_url in loc_matches:
                        norm = _normalise_url(loc_url)
                        if norm not in known and _is_same_domain(base_url, norm) and _is_page_url(norm):
                            urls_to_visit.append(norm)
                            known.add(norm)
            except Exception:
                continue

        # Try standard sitemap.xml
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

        print(f"INFO:Discovery found {len(known)} URLs so far", file=sys.stderr, flush=True)

        # ── Phase 1: Crawl pages (BFS) ──
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

                # Discover more links from this page
                new_links = _discover_links_aggressive(page, base_url, visited, known)
                urls_to_visit.extend(new_links)

                # Screenshot (viewport only, not full page)
                screenshot_filename = f"page_{idx + 1}.png"
                screenshot_path = os.path.join(screenshots_dir, screenshot_filename)
                page.screenshot(path=screenshot_path, full_page=False)

                # Extract content
                html = page.content()
                content = _extract_page_content(html, page_url=page_url)
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

        # ── Phase 2: If we found very few pages, try common paths ──
        if idx < 5 and idx < effective_limit:
            print("INFO:Few pages found, trying common URL patterns...", file=sys.stderr, flush=True)
            common_urls = _try_common_paths(page, base_url, visited, known)
            for common_url in common_urls:
                if idx >= effective_limit:
                    break
                norm = _normalise_url(common_url)
                if norm in visited:
                    continue
                visited.add(norm)

                try:
                    page.goto(common_url, wait_until="networkidle", timeout=20000)
                    page.wait_for_timeout(1500)

                    screenshot_filename = f"page_{idx + 1}.png"
                    screenshot_path = os.path.join(screenshots_dir, screenshot_filename)
                    page.screenshot(path=screenshot_path, full_page=False)

                    html = page.content()
                    content = _extract_page_content(html, page_url=common_url)
                    page_title = page.title() or content.get("title", "")

                    pages_data.append({
                        "page_index": idx,
                        "page_number": idx + 1,
                        "page_url": common_url,
                        "page_title": page_title,
                        "screenshot_path": f"media/screenshots/{screenshot_filename}",
                        "content": content,
                    })
                    idx += 1
                    print(
                        f"PROGRESS:{idx}:{max(len(common_urls) + idx, idx)}:Captured page {idx}: {common_url[:70]}",
                        file=sys.stderr, flush=True,
                    )
                except Exception as e:
                    print(f"WARN:Failed to capture common path {common_url}: {e}", file=sys.stderr, flush=True)
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
    single_page: bool = False,
) -> dict:
    """Crawl a website by launching Playwright in a SEPARATE PROCESS."""
    logger.info(
        "crawl_website called: single_page=%s, max_pages=%d, url=%s",
        single_page, max_pages, url,
    )
    config = {
        "url": url,
        "presentation_id": presentation_id,
        "media_dir": media_dir,
        "max_pages": max_pages,
        "single_page": single_page,
    }
    config_path = os.path.join(media_dir, "_crawl_config.json")
    result_path = os.path.join(media_dir, "_crawl_result.json")

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f)
    logger.info("Crawl config written: %s", json.dumps(config))

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

    sp = config.get("single_page", False)
    mp = config.get("max_pages", 0)
    print(
        f"INFO:Subprocess starting: single_page={sp}, max_pages={mp}, url={config['url']}",
        file=sys.stderr, flush=True,
    )

    # DEFENSIVE: if single_page is True, force max_pages to 1
    if sp:
        mp = 1
        print("INFO:Single-page mode forced max_pages=1", file=sys.stderr, flush=True)

    result = _crawl_impl(
        url=config["url"],
        presentation_id=config["presentation_id"],
        media_dir=config["media_dir"],
        max_pages=mp,
        single_page=sp,
    )

    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)

    print(f"OK:Crawled {len(result['slides'])} pages", file=sys.stderr, flush=True)