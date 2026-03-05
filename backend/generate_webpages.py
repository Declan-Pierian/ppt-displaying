"""Generate HTML webpages for existing presentations using Claude API.

Usage:
    python generate_webpages.py           # Generate for ALL presentations
    python generate_webpages.py 3         # Generate for presentation ID 3
    python generate_webpages.py 3 5       # Generate for presentations 3 and 5
"""

import sys
import os
import json
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from app.config import settings
from app.services.html_generator import generate_webpage


def main():
    pres_dir_root = os.path.join(settings.STORAGE_DIR, "presentations")

    if not os.path.exists(pres_dir_root):
        print("No presentations directory found.")
        return

    # Determine which presentations to process
    if len(sys.argv) > 1:
        pres_ids = [int(x) for x in sys.argv[1:]]
    else:
        pres_ids = sorted(
            int(d)
            for d in os.listdir(pres_dir_root)
            if os.path.isdir(os.path.join(pres_dir_root, d)) and d.isdigit()
        )

    if not pres_ids:
        print("No presentations found.")
        return

    print(f"Will generate webpages for {len(pres_ids)} presentation(s): {pres_ids}")
    print(f"Using model: {settings.CLAUDE_MODEL}")
    print(f"API key: {settings.CLAUDE_API_KEY[:20]}..." if settings.CLAUDE_API_KEY else "API key: NOT SET")
    print()

    for pres_id in pres_ids:
        pres_dir = os.path.join(pres_dir_root, str(pres_id))
        slides_json = os.path.join(pres_dir, "slides.json")
        media_dir = os.path.join(pres_dir, "media")

        if not os.path.exists(slides_json):
            print(f"  [{pres_id}] SKIP -- no slides.json found")
            continue

        # Check if already generated
        existing = os.path.join(pres_dir, "webpage.html")
        if os.path.exists(existing):
            size = os.path.getsize(existing)
            print(f"  [{pres_id}] Already has webpage.html ({size:,} bytes) -- regenerating...")

        # Load title
        with open(slides_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        title = data.get("title", "Untitled")
        slide_count = len(data.get("slides", []))

        print(f"  [{pres_id}] \"{title}\" ({slide_count} slides) -- generating...")
        start = time.time()

        try:
            result = generate_webpage(pres_id, slides_json, media_dir, pres_dir)
            elapsed = time.time() - start

            if result:
                size = os.path.getsize(result)
                print(f"  [{pres_id}] SUCCESS -- {size:,} bytes in {elapsed:.1f}s")
                print(f"           -> {result}")
            else:
                print(f"  [{pres_id}] SKIPPED -- generator returned None (check API key)")
        except Exception as e:
            elapsed = time.time() - start
            print(f"  [{pres_id}] FAILED in {elapsed:.1f}s -- {e}")

        print()


if __name__ == "__main__":
    main()
