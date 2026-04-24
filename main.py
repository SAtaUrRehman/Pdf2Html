"""
GitHub Copilot Extension server for PDF-to-HTML conversion.

Invoke in Copilot Chat:  @pdf-to-html /path/to/report.pdf

The server processes the PDF, generates pixel-perfect HTML/CSS using Gemini
Vision, saves the result next to the source file, and streams progress back
to the Copilot chat interface.

Run:
  uvicorn main:app --host 0.0.0.0 --port 3000

Expose publicly (local dev):
  ngrok http 3000
"""
import json
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from pdf_to_html import combine_pages_html, create_model, generate_html, process_pdf

load_dotenv()

GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]
MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
RENDER_DPI = int(os.getenv("RENDER_DPI", "150"))

app = FastAPI(title="PDF-to-HTML Copilot Extension")


# ---------------------------------------------------------------------------
# SSE helpers (OpenAI-compatible streaming format)
# ---------------------------------------------------------------------------

def _sse(content: str) -> str:
    payload = {
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": MODEL,
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": content}, "finish_reason": None}],
    }
    return f"data: {json.dumps(payload)}\n\n"


_SSE_DONE = "data: [DONE]\n\n"


def _extract_pdf_path(message: str) -> str | None:
    match = re.search(r'["\']?([^\s"\']+\.pdf)["\']?', message, re.IGNORECASE)
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# Core streaming generator
# ---------------------------------------------------------------------------

async def _process_and_stream(pdf_path: str):
    model = create_model(GOOGLE_API_KEY, MODEL)
    output_path = str(Path(pdf_path).with_suffix(".html"))

    yield _sse(f"Reading `{pdf_path}`…\n\n")

    try:
        pages = await run_in_threadpool(process_pdf, pdf_path, RENDER_DPI)
    except FileNotFoundError:
        yield _sse(f"Error: file not found — `{pdf_path}`")
        yield _SSE_DONE
        return
    except Exception as exc:
        yield _sse(f"Error reading PDF: {exc}")
        yield _SSE_DONE
        return

    yield _sse(f"Parsed **{len(pages)}** page(s). Generating HTML/CSS with Gemini Vision…\n\n")

    all_page_html: list[str] = []
    for page in pages:
        label = f"page {page.page_num + 1}/{len(pages)}"
        yield _sse(f"  {label} — analysing layout… ")
        try:
            html = await run_in_threadpool(generate_html, page, model)
            all_page_html.append(html)
            yield _sse(f"done ({len(html):,} bytes)\n")
        except Exception as exc:
            yield _sse(f"failed: {exc}\n")

    if not all_page_html:
        yield _sse("\nNo pages generated. Check your GOOGLE_API_KEY and PDF file.")
        yield _SSE_DONE
        return

    final_html = all_page_html[0] if len(all_page_html) == 1 else combine_pages_html(all_page_html)

    try:
        Path(output_path).write_text(final_html, encoding="utf-8")
        yield _sse(
            f"\nSaved **{len(final_html):,} bytes** → `{output_path}`\n\n"
            "Open the file in a browser to preview the converted report.\n"
        )
    except Exception as exc:
        yield _sse(f"\nCould not write file: {exc}\n")

    yield _SSE_DONE


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/")
async def copilot_agent(request: Request):
    """GitHub Copilot Extension entry point."""
    body = await request.json()
    messages = body.get("messages", [])

    last_user_msg = next(
        (m["content"] for m in reversed(messages) if m.get("role") == "user"),
        "",
    )

    pdf_path = _extract_pdf_path(last_user_msg)
    if not pdf_path:
        async def _usage():
            yield _sse(
                "Please provide the path to a PDF file.\n\n"
                "**Usage:** `@pdf-to-html /path/to/report.pdf`\n"
            )
            yield _SSE_DONE
        return StreamingResponse(_usage(), media_type="text/event-stream")

    return StreamingResponse(
        _process_and_stream(pdf_path),
        media_type="text/event-stream",
    )


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL, "render_dpi": RENDER_DPI}
