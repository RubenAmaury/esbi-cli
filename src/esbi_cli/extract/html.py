import re
from urllib.parse import urljoin, urlparse

import lxml.html
import trafilatura

from esbi_cli.extract import ExtractedDoc, ExtractError

MAX_IMAGES = 5
NOT_CONTENT = re.compile(r"logo|icon|avatar|sprite|pixel|tracking|badge|button", re.I)


def _image_links(html: str, base_url: str) -> list[tuple[str, str]]:
    """(alt, url) of the article's content images. Linked, never downloaded."""
    try:
        tree = lxml.html.fromstring(html)
    except (lxml.etree.ParserError, ValueError):
        return []
    region = next(iter(tree.xpath("//article") or tree.xpath("//main") or [tree]))
    links, seen = [], set()
    for img in region.iter("img"):
        src = (img.get("src") or "").strip()
        if (
            not src
            or src.startswith("data:")
            or urlparse(src).path.lower().endswith((".svg", ".gif"))
        ):
            continue
        try:
            width, height = int(img.get("width") or 0), int(img.get("height") or 0)
        except ValueError:
            width = height = 0
        if (width and width < 100) or (height and height < 100):
            continue  # a pixel, an icon
        if NOT_CONTENT.search(src) or NOT_CONTENT.search(img.get("class") or ""):
            continue
        url = urljoin(base_url, src)
        if urlparse(url).scheme in ("http", "https") and url not in seen:
            seen.add(url)
            links.append((" ".join((img.get("alt") or "").split()), url))
            if len(links) == MAX_IMAGES:
                break
    return links


def extract_html(html: str, url: str) -> ExtractedDoc:
    text = trafilatura.extract(
        html, url=url, output_format="markdown", include_links=False, include_tables=True
    )
    if not text or len(text.strip()) < 200:
        raise ExtractError(f"No readable article content found at {url}")
    meta = trafilatura.extract_metadata(html, default_url=url)
    title = (meta.title if meta and meta.title else None) or url
    return ExtractedDoc(
        title=title.strip(),
        text=text.strip(),
        kind="article",
        url=url,
        image_links=_image_links(html, url),
    )
