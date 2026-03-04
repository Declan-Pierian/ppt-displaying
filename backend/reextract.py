"""Re-extract all existing presentations with the updated pipeline."""

import os
import sys
import json
import shutil

# Add parent dir to path so we can import app modules
sys.path.insert(0, os.path.dirname(__file__))

from app.config import settings
from app.models.database import SessionLocal
from app.models.presentation import Presentation
from app.services.extraction.pipeline import extract_presentation


def main():
    db = SessionLocal()
    try:
        presentations = db.query(Presentation).all()
        print(f"Found {len(presentations)} presentation(s) to re-extract.\n")

        for pres in presentations:
            print(f"--- Re-extracting: {pres.title} (ID={pres.id}) ---")

            # Find the original PPTX file
            upload_path = os.path.join(settings.STORAGE_DIR, "uploads", str(pres.id), "original.pptx")
            if not os.path.exists(upload_path):
                print(f"  SKIP: Original file not found at {upload_path}")
                continue

            # Clear old media files (don't rmtree — OneDrive may lock the folder)
            media_dir = os.path.join(settings.STORAGE_DIR, "presentations", str(pres.id), "media")
            if os.path.exists(media_dir):
                for root, dirs, files in os.walk(media_dir, topdown=False):
                    for f in files:
                        try:
                            os.remove(os.path.join(root, f))
                        except Exception:
                            pass
                    for d in dirs:
                        try:
                            os.rmdir(os.path.join(root, d))
                        except Exception:
                            pass
            os.makedirs(media_dir, exist_ok=True)

            # Re-extract
            try:
                result = extract_presentation(upload_path, pres.id, media_dir)

                slide_data_path = os.path.join(settings.STORAGE_DIR, "presentations", str(pres.id), "slides.json")
                with open(slide_data_path, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)

                pres.status = "ready"
                pres.slide_count = len(result["slides"])
                pres.slide_width_emu = result["slide_width_emu"]
                pres.slide_height_emu = result["slide_height_emu"]
                pres.title = result.get("title") or pres.title

                db.commit()

                # Count extracted items
                total_shapes = sum(len(s["shapes"]) for s in result["slides"])
                bg_images = sum(1 for s in result["slides"] if s["background"].get("type") == "image")
                media_files = os.listdir(media_dir)

                slide_images = sum(1 for s in result["slides"] if s.get("slide_image"))
                print(f"  OK: {len(result['slides'])} slides, {total_shapes} shapes, {bg_images} bg images, {slide_images} rendered images")
                print(f"  Media files: {len(media_files)} ({', '.join(media_files[:10])}{'...' if len(media_files) > 10 else ''})")

            except Exception as e:
                print(f"  FAILED: {e}")
                import traceback
                traceback.print_exc()
                pres.status = "failed"
                pres.error_message = str(e)
                db.commit()

        print("\nDone!")
    finally:
        db.close()


if __name__ == "__main__":
    main()
