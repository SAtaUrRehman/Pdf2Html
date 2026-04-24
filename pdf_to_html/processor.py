"""
PDF parsing: renders pages to images and extracts text/image elements with exact
positions, fonts, sizes, and colors — all coordinates are in PDF points (pt).
"""
import base64
from dataclasses import dataclass, field
from typing import List

import fitz  # PyMuPDF


@dataclass
class TextSpan:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    font: str
    size: float
    color: str   # "#rrggbb"
    bold: bool
    italic: bool


@dataclass
class EmbeddedImage:
    x0: float
    y0: float
    x1: float
    y1: float
    data_b64: str
    ext: str     # "png", "jpeg", etc.


@dataclass
class PageData:
    page_num: int        # 0-based
    width_pt: float
    height_pt: float
    render_b64: str      # base64-encoded PNG of the rendered page
    text_spans: List[TextSpan] = field(default_factory=list)
    images: List[EmbeddedImage] = field(default_factory=list)


def process_pdf(pdf_path: str, render_dpi: int = 150) -> List[PageData]:
    """Open a PDF and return structured data for every page."""
    doc = fitz.open(pdf_path)
    scale = render_dpi / 72.0
    mat = fitz.Matrix(scale, scale)
    pages: List[PageData] = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        rect = page.rect

        pix = page.get_pixmap(matrix=mat, alpha=False)
        render_b64 = base64.b64encode(pix.tobytes("png")).decode()

        pages.append(PageData(
            page_num=page_num,
            width_pt=rect.width,
            height_pt=rect.height,
            render_b64=render_b64,
            text_spans=_extract_text_spans(page),
            images=_extract_images(page, doc),
        ))

    doc.close()
    return pages


def _extract_text_spans(page) -> List[TextSpan]:
    spans: List[TextSpan] = []
    blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]

    for block in blocks:
        if block.get("type") != 0:   # 0 = text block
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "")
                if not text.strip():
                    continue

                c = span.get("color", 0)
                r, g, b = (c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF

                flags = span.get("flags", 0)
                bbox = span["bbox"]

                spans.append(TextSpan(
                    text=text,
                    x0=bbox[0], y0=bbox[1], x1=bbox[2], y1=bbox[3],
                    font=span.get("font", ""),
                    size=round(span.get("size", 12), 2),
                    color=f"#{r:02x}{g:02x}{b:02x}",
                    bold=bool(flags & (1 << 4)),   # bit 4 = bold
                    italic=bool(flags & (1 << 1)),  # bit 1 = italic
                ))

    return spans


def _extract_images(page, doc) -> List[EmbeddedImage]:
    images: List[EmbeddedImage] = []

    for img_info in page.get_images(full=True):
        xref = img_info[0]
        rects = page.get_image_rects(xref)
        if not rects:
            continue
        try:
            base_img = doc.extract_image(xref)
            bbox = rects[0]
            images.append(EmbeddedImage(
                x0=bbox.x0, y0=bbox.y0, x1=bbox.x1, y1=bbox.y1,
                data_b64=base64.b64encode(base_img["image"]).decode(),
                ext=base_img.get("ext", "png"),
            ))
        except Exception:
            continue

    return images
