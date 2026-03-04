"""Export each slide of a PPTX as a high-res PNG image.

Supports two rendering back-ends:
  1. PowerPoint COM automation (win32com / pywin32) -- pixel-perfect fidelity.
  2. LibreOffice headless  ->  PDF  ->  images (pdf2image) -- cross-platform fallback.

The public entry-point is ``export_slide_images()`` which auto-detects the
best available renderer and returns a list of paths to the generated PNGs.
"""

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Renderer detection
# ---------------------------------------------------------------------------

def detect_renderer() -> str:
    """Return the best available slide renderer.

    Returns
    -------
    str
        ``"powerpoint"`` if PowerPoint COM automation is available,
        ``"libreoffice"`` if *soffice* is found on ``PATH``,
        ``"none"`` otherwise.
    """
    # 1. Try PowerPoint COM (Windows only)
    try:
        import win32com.client  # noqa: F401
        import pythoncom  # noqa: F401
        logger.debug("PowerPoint COM (win32com) is available.")
        return "powerpoint"
    except ImportError:
        logger.debug("win32com not installed -- skipping PowerPoint COM.")

    # 2. Try LibreOffice headless
    soffice = _find_soffice()
    if soffice is not None:
        logger.debug("LibreOffice found at %s", soffice)
        return "libreoffice"

    logger.warning("No slide renderer available (neither PowerPoint COM nor LibreOffice).")
    return "none"


def _find_soffice() -> Optional[str]:
    """Locate the *soffice* executable, or return ``None``."""
    path = shutil.which("soffice")
    if path:
        return path

    # Common Windows install locations
    for candidate in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ):
        if os.path.isfile(candidate):
            return candidate

    return None


# ---------------------------------------------------------------------------
# PowerPoint COM exporter
# ---------------------------------------------------------------------------

def export_slides_powerpoint(
    pptx_path: str,
    output_dir: str,
    width: int = 1920,
) -> List[str]:
    """Export every slide as a PNG using PowerPoint COM automation.

    Parameters
    ----------
    pptx_path : str
        Absolute path to the ``.pptx`` file.
    output_dir : str
        Directory where PNG files will be written.
    width : int, optional
        Desired image width in pixels (default 1920).  Height is calculated
        proportionally from the slide dimensions.

    Returns
    -------
    list[str]
        Absolute paths to the generated PNG files, ordered by slide number.
    """
    import pythoncom
    import win32com.client

    pptx_path = os.path.abspath(pptx_path)
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    pythoncom.CoInitialize()
    ppt_app = None
    presentation = None
    try:
        ppt_app = win32com.client.Dispatch("PowerPoint.Application")
        # Open invisibly: ReadOnly=True, Untitled=False, WithWindow=False
        presentation = ppt_app.Presentations.Open(
            pptx_path,
            ReadOnly=True,
            Untitled=False,
            WithWindow=False,
        )

        # Calculate height proportionally from slide dimensions (EMU)
        slide_width_emu = presentation.SlideMaster.Width
        slide_height_emu = presentation.SlideMaster.Height
        height = int(width * slide_height_emu / slide_width_emu) if slide_width_emu else int(width * 0.5625)

        exported_paths: List[str] = []

        for idx, slide in enumerate(presentation.Slides):
            slide_num = idx + 1
            dest = os.path.join(output_dir, f"slide_{slide_num}.png")
            logger.info("Exporting slide %d/%d via PowerPoint COM -> %s", slide_num, presentation.Slides.Count, dest)
            slide.Export(dest, "PNG", width, height)
            exported_paths.append(dest)

        return exported_paths

    finally:
        try:
            if presentation is not None:
                presentation.Close()
        except Exception as exc:
            logger.warning("Failed to close presentation: %s", exc)
        try:
            if ppt_app is not None:
                ppt_app.Quit()
        except Exception as exc:
            logger.warning("Failed to quit PowerPoint: %s", exc)
        pythoncom.CoUninitialize()


# ---------------------------------------------------------------------------
# LibreOffice headless exporter (fallback)
# ---------------------------------------------------------------------------

def export_slides_libreoffice(
    pptx_path: str,
    output_dir: str,
    soffice_path: Optional[str] = None,
    dpi: int = 200,
) -> List[str]:
    """Export slides via LibreOffice headless (PPTX -> PDF -> PNGs).

    Parameters
    ----------
    pptx_path : str
        Absolute path to the ``.pptx`` file.
    output_dir : str
        Directory where PNG files will be written.
    soffice_path : str or None
        Path to *soffice*. Auto-detected when ``None``.
    dpi : int
        Resolution for the PDF-to-image conversion (default 200).

    Returns
    -------
    list[str]
        Absolute paths to the generated PNG files, ordered by slide number.
    """
    from pdf2image import convert_from_path

    pptx_path = os.path.abspath(pptx_path)
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    if soffice_path is None:
        soffice_path = _find_soffice()
    if soffice_path is None:
        raise RuntimeError("LibreOffice (soffice) not found on this system.")

    # Use a unique UserInstallation directory to avoid lock conflicts when
    # multiple conversions run in parallel.
    user_install_dir = tempfile.mkdtemp(prefix="lo_user_")
    user_install_uri = Path(user_install_dir).as_uri()

    pdf_tmp_dir = tempfile.mkdtemp(prefix="lo_pdf_")
    try:
        cmd = [
            soffice_path,
            "--headless",
            "--invisible",
            "--convert-to", "pdf",
            "--outdir", pdf_tmp_dir,
            f"-env:UserInstallation={user_install_uri}",
            pptx_path,
        ]
        logger.info("Running LibreOffice conversion: %s", " ".join(cmd))
        subprocess.run(cmd, check=True, timeout=300, capture_output=True)

        # Locate the resulting PDF
        pdf_name = Path(pptx_path).stem + ".pdf"
        pdf_path = os.path.join(pdf_tmp_dir, pdf_name)
        if not os.path.isfile(pdf_path):
            raise FileNotFoundError(f"Expected PDF not found at {pdf_path}")

        # Convert PDF pages to PNG images
        images = convert_from_path(pdf_path, dpi=dpi)
        exported_paths: List[str] = []

        for idx, img in enumerate(images):
            slide_num = idx + 1
            dest = os.path.join(output_dir, f"slide_{slide_num}.png")
            logger.info("Saving slide %d/%d via LibreOffice -> %s", slide_num, len(images), dest)
            img.save(dest, "PNG")
            exported_paths.append(dest)

        return exported_paths

    finally:
        # Cleanup temporary directories
        shutil.rmtree(pdf_tmp_dir, ignore_errors=True)
        shutil.rmtree(user_install_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def export_slide_images(
    pptx_path: str,
    output_dir: str,
    renderer: Optional[str] = None,
) -> List[str]:
    """Render every slide as a high-res PNG image.

    Automatically detects the best available renderer unless *renderer* is
    specified explicitly.

    Parameters
    ----------
    pptx_path : str
        Path to the ``.pptx`` file.
    output_dir : str
        Directory where ``slide_1.png``, ``slide_2.png``, ... will be created.
    renderer : str or None
        Force a renderer: ``"powerpoint"``, ``"libreoffice"``, or ``"none"``.
        When ``None`` (default), the renderer is auto-detected via
        :func:`detect_renderer`.

    Returns
    -------
    list[str]
        Absolute paths to the generated PNG files, ordered by slide number.
        Returns an empty list when no renderer is available.
    """
    if renderer is None:
        renderer = detect_renderer()

    logger.info("Using renderer '%s' for slide image export.", renderer)

    if renderer == "powerpoint":
        return export_slides_powerpoint(pptx_path, output_dir)
    elif renderer == "libreoffice":
        return export_slides_libreoffice(pptx_path, output_dir)
    else:
        logger.warning("No renderer available -- skipping slide image export.")
        return []
