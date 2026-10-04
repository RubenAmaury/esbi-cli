"""Turn a URL or a local file into clean markdown text."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import httpx

from esbi_cli.netguard import CannotResolve, UnsafeURL, safe_get

# Identify honestly with a contact URL: Wikipedia (and others) answer 403 to generic browser-like agents
USER_AGENT = "esbi-cli/0.1 (personal knowledge tool; +https://github.com/RubenAmaury/esbi-cli)"


class ExtractError(RuntimeError):
    pass


@dataclass
class Figure:
    """An image taken from a PDF (as PNG), with the caption printed next to it if there is one."""

    data: bytes
    page: int
    caption: str | None = None


@dataclass
class ExtractedDoc:
    title: str
    text: str
    kind: str  # article | paper
    url: str | None = None  # canonical URL, or None for local files
    pdf_bytes: bytes | None = None  # original PDF, saved into raw/
    figures: list[Figure] = field(default_factory=list)  # PDF images: copied into the vault
    image_links: list[tuple[str, str]] = field(
        default_factory=list
    )  # web images: (alt, url), linked
    image_bytes: bytes | None = None  # the original image file, saved into raw/
    image_suffix: str = ""  # its extension, e.g. ".jpg"
    warnings: list[str] = field(default_factory=list)  # said to the user (e.g. OCR page cap)


def is_url(target: str) -> bool:
    return urlparse(target).scheme in ("http", "https")


_GITHUB_REPO = re.compile(r"^https?://(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


def _get(url: str) -> httpx.Response:
    try:
        resp = safe_get(url, headers={"User-Agent": USER_AGENT}, timeout_seconds=30)
        resp.raise_for_status()
    except CannotResolve as exc:
        raise ExtractError(f"Could not fetch {url}: {exc}") from exc
    except UnsafeURL as exc:
        raise ExtractError(f"Refused to fetch {url}: {exc}") from exc
    except httpx.HTTPError as exc:
        raise ExtractError(f"Could not fetch {url}: {exc}") from exc
    return resp


def extract_source(target: str, ocr=None, max_ocr_pages: int = 10) -> ExtractedDoc:
    """Dispatch on the target: http(s) URL, local .pdf, .md or image path. `ocr` is the model that
    reads images and scanned PDFs; without one, those are rejected."""
    from esbi_cli.extract import clip, html, image, pdf

    if is_url(target):
        if repo := _GITHUB_REPO.match(target):
            # the repo page is mostly navigation; its README is the content
            owner, name = repo.groups()
            try:
                readme = _get(f"https://raw.githubusercontent.com/{owner}/{name}/HEAD/README.md")
            except ExtractError:
                readme = None  # no README: read the page like any other
            if readme is not None and len(readme.text.strip()) >= 200:
                return ExtractedDoc(f"{owner}/{name}", readme.text.strip(), "article", target)
        resp = _get(target)
        final_url = str(resp.url)
        content_type = resp.headers.get("content-type", "")
        if "application/pdf" in content_type or final_url.lower().endswith(".pdf"):
            doc = pdf.extract_pdf_bytes(
                resp.content,
                fallback_title=Path(urlparse(final_url).path).stem,
                ocr=ocr,
                max_ocr_pages=max_ocr_pages,
            )
            doc.url = target
            return doc
        doc = html.extract_html(resp.text, url=final_url)
        doc.url = target
        return doc

    path = Path(target).expanduser()
    if not path.is_file():
        raise ExtractError(f"{target} is neither an http(s) URL nor an existing file")
    if path.suffix.lower() == ".pdf":
        return pdf.extract_pdf_bytes(
            path.read_bytes(), fallback_title=path.stem, ocr=ocr, max_ocr_pages=max_ocr_pages
        )
    if path.suffix.lower() == ".md":
        return clip.extract_clip(path)
    if path.suffix.lower() in image.IMAGE_SUFFIXES:
        return image.extract_image(path, ocr)
    raise ExtractError(f"Unsupported file type: {path.suffix or path.name}")
