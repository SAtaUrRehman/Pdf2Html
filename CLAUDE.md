# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A **GitHub Copilot Extension** (and standalone CLI) that converts PDF files into pixel-perfect HTML/CSS for use in web-based report builders. It helps developers reverse-engineer existing PDF reports into HTML without manual layout work.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env          # fill in GOOGLE_API_KEY
```

Get a free Google API key at **aistudio.google.com/app/apikey** — free tier allows 15 requests/min and 1M tokens/day.

## Commands

**Run the Copilot Extension server:**
```bash
uvicorn main:app --host 0.0.0.0 --port 3000 --reload
```

**Expose locally for GitHub (requires ngrok or similar):**
```bash
ngrok http 3000
```

**CLI — convert a PDF directly (no GitHub App needed):**
```bash
python cli.py report.pdf                          # outputs report.html
python cli.py report.pdf out.html                 # custom output path
python cli.py report.pdf --pages 1-3             # subset of pages
python cli.py report.pdf --dpi 200               # higher render quality
python cli.py report.pdf --model gemini-1.5-pro  # higher quality model
```

**Health check:**
```bash
curl http://localhost:3000/health
```

## Architecture

```
pdf_to_html/
  processor.py   — PyMuPDF: renders each page to a PNG + extracts text spans
                   (position, font, size, colour, bold/italic) and embedded images.
                   All coordinates are in PDF points (pt); no unit conversion needed
                   because CSS pt == PDF pt == 1/72 inch.

  generator.py   — Sends the rendered PNG + text span data to Gemini Vision.
                   Gemini generates a standalone HTML file per page using
                   position:absolute layout with exact pt coordinates.
                   combine_pages_html() merges per-page HTML into one document.

main.py          — FastAPI server. POST / receives the GitHub Copilot Extension
                   request (OpenAI-compatible messages array), extracts the PDF path
                   from the user message, runs the pipeline via run_in_threadpool,
                   and streams progress + completion back as OpenAI-compatible SSE.

cli.py           — Thin argparse wrapper around the same pipeline for local use.
```

### Key design decisions

- **Coordinate system**: PyMuPDF returns bounding boxes in PDF points. CSS also understands `pt`. The generator prompt instructs Claude to use `pt` units directly, so there is no conversion layer and no floating-point drift.
- **Two inputs to Gemini**: The rendered page image (for visual structure — lines, borders, shading, tables) AND the extracted text spans (for exact positions, fonts, colours). Neither alone is sufficient for pixel-perfect output.
- **Per-page generation**: Each PDF page is sent as a separate Gemini request. This keeps token counts manageable and enables page-by-page progress reporting.
- **Streaming in the extension**: `main.py` uses `run_in_threadpool` for the synchronous PyMuPDF and Gemini SDK calls, then yields SSE chunks between pages so Copilot Chat shows live progress.

## GitHub Copilot Extension Setup

1. Create a **GitHub App** at `github.com/settings/apps`.
2. Under *Copilot*, enable **"Copilot Extension"** and set the agent URL to your public server URL (e.g. `https://abc123.ngrok.io`).
3. Install the GitHub App on your account or organisation.
4. In Copilot Chat, invoke: `@<your-app-slug> /path/to/report.pdf`

The extension parses any token matching `*.pdf` from the user message, so natural phrasing also works:  
`@pdf-to-html please convert C:\reports\q1.pdf`

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `GOOGLE_API_KEY` | required | Google AI Studio API key (free at aistudio.google.com) |
| `GEMINI_MODEL` | `gemini-1.5-flash` | Gemini model — use `gemini-1.5-pro` for higher quality |
| `RENDER_DPI` | `150` | PDF render resolution (higher = better quality, larger payload) |
