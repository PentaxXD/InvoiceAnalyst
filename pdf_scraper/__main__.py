#!/usr/bin/env python3
import argparse
from pathlib import Path
import sys
from typing import Optional

from chicago_imports_parser import _read_input_text, parse_invoice_text, write_csv


def cmd_items(input_path: Path, out_path: Optional[Path], all_pages: bool, debug_trace_path: Optional[Path]) -> int:
    # all_pages is currently a no-op because we extract full text by default
    default_out = Path("output") / "invoice_items.csv"
    out = (out_path or default_out).resolve()
    try:
        raw_text = _read_input_text(input_path)
        debug = [] if debug_trace_path else None
        items = parse_invoice_text(raw_text, source_path=input_path, debug_trace=debug)
    except Exception:
        # Always produce a CSV file even if parsing fails
        items = []
        debug = [] if debug_trace_path else None
    try:
        write_csv(items, out)
        if debug_trace_path and isinstance(debug, list):
            # Write debug CSV
            import csv
            dp = debug_trace_path.resolve()
            with dp.open('w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow([
                    "page",
                    "y",
                    "order_qty",
                    "shipped_qty",
                    "item_code",
                    "description",
                    "pack_size",
                    "pack_quantity",
                    "product_size",
                    "case_price",
                    "unit_price",
                    "extended_price",
                    "store_price",
                    "online_price",
                ])
                for row in debug:
                    w.writerow([
                        row.get("page", ""),
                        row.get("y", ""),
                        row.get("order_qty", ""),
                        row.get("shipped_qty", ""),
                        row.get("item_code", ""),
                        row.get("description", ""),
                        row.get("pack_size", ""),
                        row.get("pack_quantity", ""),
                        row.get("product_size", ""),
                        row.get("case_price", ""),
                        row.get("unit_price", ""),
                        row.get("extended_price", ""),
                        row.get("store_price", ""),
                        row.get("online_price", ""),
                    ])
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
    p_items.add_argument("--debug-trace", type=Path, help="Optional debug CSV to explain header->price mapping")

    args = parser.parse_args()

    if args.command == "items":
        return cmd_items(args.input, args.out, args.all_pages, getattr(args, 'debug_trace', None))

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
