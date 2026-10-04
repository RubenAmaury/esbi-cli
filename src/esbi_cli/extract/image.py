"""Images (screenshots, photos of slides, scanned pages): an OCR model reads the text."""

import io
from pathlib import Path

from PIL import Image, ImageOps

from esbi_cli.extract import ExtractedDoc, ExtractError, Figure
from esbi_cli.llm.adapter import LLMError

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff")
MAX_SIDE_PX = 1600  # px: measured, a dense page at this size reads as well as at twice the size
MIN_CHARS = 40  # less than this is a photo or a diagram, not text worth a note
NO_OCR = (
    "reading images and scanned PDFs is off: `sb ocr enable` sets up a local vision model "
    "([llm.ocr], https://rubenamaury.github.io/esbi-cli/docs/reference/configuration/)"
)


def read_text(ocr, png: bytes, name: str) -> str:
    try:
        return ocr.read_image(png)
    except LLMError as exc:  # this source fails; the text model and the other sources are fine
        raise ExtractError(f"The OCR model could not read {name}: {exc}") from exc


def to_png(data: bytes, name: str) -> bytes:
    """Upright (EXIF), RGB, at most MAX_SIDE_PX on the long side: what the model sees and the note shows."""
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except Exception as exc:  # Pillow raises several unrelated error types
        raise ExtractError(f"Could not open {name} as an image: {exc}") from exc
    img.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def extract_image(path: Path, ocr) -> ExtractedDoc:
    if ocr is None:
        raise ExtractError(f"{path.name}: {NO_OCR}")
    data = path.read_bytes()
    png = to_png(data, path.name)
    text = read_text(ocr, png, path.name).strip()
    if len(text) < MIN_CHARS:
        raise ExtractError(f"{path.name} has no readable text (a photo or a diagram?)")
    return ExtractedDoc(
        title=path.stem.replace("-", " ").replace("_", " ").strip(),
        text=text,
        kind="article",
        image_bytes=data,
        image_suffix=path.suffix.lower(),
        figures=[image_figure(png)],
    )


def image_figure(png: bytes) -> Figure:
    return Figure(data=png, page=0)  # page 0: it is not a page of anything
