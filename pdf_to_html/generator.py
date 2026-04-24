"""
HTML/CSS generation: uses Gemini Vision to produce pixel-perfect HTML that matches
the layout of a rendered PDF page. Coordinates stay in PDF points (pt) so no
unit conversion is needed — CSS pt == PDF pt == 1/72 inch.
"""
import base64
import io
import re
from typing import List

import PIL.Image
from google import genai
from google.genai import types

from .processor import PageData

_SYSTEM_PROMPT = """You are an expert HTML/CSS engineer specialising in pixel-perfect PDF-to-HTML conversion for web-based reports.

Given:
  • A high-resolution rendered image of a PDF page
  • Extracted text spans with exact bounding boxes in PDF points (pt), font names, sizes, colours, and weight/style flags

Produce a complete, standalone HTML file (<!DOCTYPE html> … </html>) that visually replicates the page exactly.

Rules:
1. Page container: <div class="page"> with `position:relative; width:{W}pt; height:{H}pt; background:#fff; overflow:hidden;`
2. Every text span: `position:absolute; left:{x0}pt; top:{y0}pt; width:{w}pt; font-size:{size}pt; color:{hex}; white-space:pre;`
   Apply font-weight:bold and font-style:italic as flagged.
3. Map PDF font families to web-safe equivalents:
   - Times / Garamond / Georgia → serif
   - Helvetica / Arial / Calibri → sans-serif
   - Courier / Consolas / Lucida Console → monospace
   If a specific font is needed, add a Google Fonts <link>.
4. Reconstruct ALL visual elements visible in the image but absent from the text data:
   horizontal/vertical rules, borders, shaded cells, table grids, background fills, logos, charts.
   Use <div> with border/background CSS or inline <svg> for lines and shapes.
5. For embedded images, use <img> with a data URI: `src="data:{mime};base64,{b64}"`.
6. Do NOT add any scrollbars, margins, or padding outside the .page container.
7. Output ONLY the HTML document — no markdown fences, no explanation."""


def create_model(api_key: str, model_name: str = "gemini-flash-lite-latest") -> genai.Client:
    """Configure the Gemini client and return a ready-to-use client."""
    return genai.Client(api_key=api_key)


def _build_prompt(page: PageData) -> str:
    span_lines = []
    for s in page.text_spans:
        parts = [
            f"  '{s.text}'",
            f"x0={s.x0:.0f} y0={s.y0:.0f} x1={s.x1:.0f} y1={s.y1:.0f}",
            f"font={s.font!r} size={s.size}pt color={s.color}",
        ]
        if s.bold:
            parts.append("bold")
        if s.italic:
            parts.append("italic")
        span_lines.append(" ".join(parts))

    img_lines = [
        f"  [{i}] x0={im.x0:.0f} y0={im.y0:.0f} x1={im.x1:.0f} y1={im.y1:.0f} type={im.ext}"
        for i, im in enumerate(page.images)
    ]

    text_section = "\n".join(span_lines) or "  (none)"
    img_section = "\n".join(img_lines) or "  (none)"

    data_uri_section = ""
    if page.images:
        lines = []
        for i, im in enumerate(page.images):
            mime = "image/jpeg" if im.ext in ("jpg", "jpeg") else f"image/{im.ext}"
            lines.append(f"  [{i}] data:{mime};base64,{im.data_b64}")
        data_uri_section = "\nEmbedded image data URIs (use as <img src=...>):\n" + "\n".join(lines) + "\n"

    return (
        f"Page {page.page_num + 1} — {page.width_pt:.0f}pt × {page.height_pt:.0f}pt\n\n"
        f"Text spans:\n{text_section}\n\n"
        f"Embedded images (positions):\n{img_section}\n"
        f"{data_uri_section}\n"
        "Generate the complete HTML file now."
    )


def _to_pil(b64_data: str) -> PIL.Image.Image:
    return PIL.Image.open(io.BytesIO(base64.b64decode(b64_data)))


def generate_html(page: PageData, model: genai.Client, model_name: str) -> str:
    """Generate a standalone HTML file for one PDF page."""
    contents = types.Content(
        role='user',
        parts=[
            types.Part.from_bytes(data=base64.b64decode(page.render_b64), mime_type='image/png'),
            types.Part.from_text(text=_build_prompt(page))
        ]
    )

    config = types.GenerateContentConfig(
        system_instruction=_SYSTEM_PROMPT,
        max_output_tokens=8192,
        temperature=0.1,
    )

    response = model.models.generate_content(
        model=model_name,
        contents=[contents],
        config=config,
    )

    if not response.candidates or not response.candidates[0].content.parts:
        raise RuntimeError(
            "Gemini returned no content — the response may have been blocked. "
            "Try a lower DPI or check your API quota."
        )

    return response.text


def combine_pages_html(pages_html: List[str]) -> str:
    """Merge per-page HTML strings into a single multi-page document."""
    body_parts: List[str] = []
    style_parts: List[str] = []

    for i, html in enumerate(pages_html):
        for style_match in re.finditer(r"<style[^>]*>(.*?)</style>", html, re.DOTALL | re.IGNORECASE):
            style_parts.append(f"/* page {i + 1} */\n{style_match.group(1).strip()}")

        body_match = re.search(r"<body[^>]*>(.*?)</body>", html, re.DOTALL | re.IGNORECASE)
        content = body_match.group(1).strip() if body_match else html
        body_parts.append(
            f'<div class="report-page" id="page-{i + 1}">{content}</div>'
        )

    merged_styles = "\n\n".join(style_parts)
    merged_body = "\n\n".join(body_parts)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Report</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ background: #808080; padding: 24px; }}
.report-page {{ background: #fff; box-shadow: 0 4px 16px rgba(0,0,0,.45); margin: 0 auto 24px; }}

{merged_styles}
</style>
</head>
<body>
{merged_body}
</body>
</html>"""
