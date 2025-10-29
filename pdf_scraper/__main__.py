#!/usr/bin/env python3
import argparse
from pathlib import Path
import sys
from typing import Optional

from chicago_imports_parser import _read_input_text, parse_invoice_text, write_csv


def cmd_items(input_path: Path, out_path: Optional[Path], all_pages: bool) -> int:
    # all_pages is currently a no-op because we extract full text by default
    out = (out_path or Path("invoice_items.csv")).resolve()
    try:
        raw_text = _read_input_text(input_path)
        items = parse_invoice_text(raw_text)
    except Exception:
        # Always produce a CSV file even if parsing fails
        items = []
    try:
        write_csv(items, out)
    finally:
        # Print absolute output path for clarity
        print(str(out))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="pdf_scraper", description="Invoice PDF scraper utilities")
    sub = parser.add_subparsers(dest="command", required=True)

    p_items = sub.add_parser("items", help="Extract invoice line items into CSV")
    p_items.add_argument("input", type=Path, help="Path to input .pdf or .txt")
    p_items.add_argument("--all-pages", action="store_true", help="Process all pages (default: on)")
    p_items.add_argument("--out", type=Path, help="Output CSV path (default: invoice_items.csv)")

    args = parser.parse_args()

    if args.command == "items":
        return cmd_items(args.input, args.out, args.all_pages)

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
