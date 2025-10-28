import argparse
import csv
import sys
from typing import List

import pdfplumber

from .parsers.stark import parse_stark_invoice_lines


def extract_lines_from_pdf(path: str, all_pages: bool) -> List[str]:
    lines: List[str] = []
    with pdfplumber.open(path) as pdf:
        pages = pdf.pages if all_pages else pdf.pages[:1]
        for page in pages:
            text = page.extract_text() or ""
            page_lines = text.splitlines()
            lines.extend(page_lines)
    return lines


def cmd_items(args: argparse.Namespace) -> int:
    lines = extract_lines_from_pdf(args.pdf, args.all_pages)
    rows = parse_stark_invoice_lines(lines)

    # Output
    out_fh = open(args.out, "w", newline="", encoding="utf-8") if args.out else sys.stdout
    writer = csv.writer(out_fh)
    writer.writerow(["Item", "Description", "Pack Size", "Quantity", "Price Each", "Amount"])
    for r in rows:
        writer.writerow([
            r.get("Item", ""),
            r.get("Description", ""),
            r.get("Pack Size", ""),
            r.get("Quantity", ""),
            r.get("Price Each", ""),
            r.get("Amount", ""),
        ])
    if args.out:
        out_fh.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pdf_scraper", description="PDF invoice scraper for Stark invoices")
    sub = p.add_subparsers(dest="subcmd", required=True)

    p_items = sub.add_parser("items", help="Extract line items to CSV")
    p_items.add_argument("pdf", help="Path to invoice PDF")
    p_items.add_argument("--all-pages", dest="all_pages", action="store_true", help="Process all pages")
    p_items.add_argument("--out", dest="out", default=None, help="Output CSV file path (default: stdout)")
    p_items.set_defaults(func=cmd_items)

    return p


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
