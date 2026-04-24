#!/usr/bin/env python3
"""
Standalone CLI for PDF-to-HTML conversion — no GitHub Copilot required.

Usage:
  python cli.py report.pdf
  python cli.py report.pdf output.html
  python cli.py report.pdf --pages 1-3
  python cli.py report.pdf --dpi 200 --model gemini-1.5-pro
"""
import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from pdf_to_html import combine_pages_html, create_model, generate_html, process_pdf


def _parse_page_range(spec: str, total: int) -> list[int]:
    """'2-4' or '3' → zero-based indices."""
    if "-" in spec:
        a, b = spec.split("-", 1)
        start = max(1, int(a)) - 1
        end = min(total, int(b)) - 1
        return list(range(start, end + 1))
    idx = int(spec) - 1
    return [idx] if 0 <= idx < total else []


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Convert a PDF to pixel-perfect HTML/CSS using Gemini Vision",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("pdf", help="Input PDF path")
    parser.add_argument("output", nargs="?", help="Output HTML path (default: <pdf>.html)")
    parser.add_argument("--dpi", type=int, default=int(os.getenv("RENDER_DPI", "150")),
                        help="Rendering DPI (default: 150)")
    parser.add_argument("--pages", help="Page range, e.g. '1-3' or '2'")
    parser.add_argument("--model", default=os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest"),
                        help="Gemini model ID (default: gemini-flash-lite-latest)")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"Error: {pdf_path} not found", file=sys.stderr)
        sys.exit(1)

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("Error: GOOGLE_API_KEY is not set", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output) if args.output else pdf_path.with_suffix(".html")
    model = create_model(api_key, args.model)

    print(f"Reading {pdf_path} …")
    pages = process_pdf(str(pdf_path), render_dpi=args.dpi)
    print(f"  {len(pages)} page(s) found")

    if args.pages:
        indices = _parse_page_range(args.pages, len(pages))
        if not indices:
            print(f"Error: page range '{args.pages}' is out of bounds (1–{len(pages)})", file=sys.stderr)
            sys.exit(1)
        pages = [pages[i] for i in indices]
        print(f"  Processing {len(pages)} page(s) after range filter")

    all_html: list[str] = []
    for page in pages:
        label = f"page {page.page_num + 1}"
        print(f"  Generating HTML for {label} …", end="", flush=True)
        html = generate_html(page, model, args.model)
        all_html.append(html)
        print(f" done ({len(html):,} bytes)")

    final_html = all_html[0] if len(all_html) == 1 else combine_pages_html(all_html)
    output_path.write_text(final_html, encoding="utf-8")
    print(f"\nSaved: {output_path} ({len(final_html):,} bytes)")


if __name__ == "__main__":
    main()
