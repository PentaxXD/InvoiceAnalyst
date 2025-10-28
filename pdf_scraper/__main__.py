import argparse
import csv
import sys
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, getcontext
from typing import List, Optional

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

    # Always write a .csv file. If no output path is provided, place next to the PDF.
    out_path = _resolve_out_path(args.pdf, args.out)

    with open(out_path, "w", newline="", encoding="utf-8") as out_fh:
        writer = csv.writer(out_fh)
        writer.writerow([
            "Item",
            "Description",
            "Pack Size",
            "Quantity",
            "Price Each",
            "Amount",
            "Price Each Product",
            "Store Price",
            "Online Price",
        ])
        for r in rows:
            per_product, store_price, online_price = _compute_prices(
                r.get("Pack Size", ""), r.get("Price Each", "")
            )
            writer.writerow([
                r.get("Item", ""),
                r.get("Description", ""),
                r.get("Pack Size", ""),
                r.get("Quantity", ""),
                r.get("Price Each", ""),
                r.get("Amount", ""),
                per_product or "",
                store_price or "",
                online_price or "",
            ])
    return 0


def _resolve_out_path(pdf_path: str, out_arg: Optional[str]) -> str:
    p = Path(out_arg) if out_arg else None
    if p is None:
        pdfp = Path(pdf_path)
        return str(pdfp.with_name(f"{pdfp.stem}_items.csv"))
    # Ensure .csv suffix
    if p.suffix.lower() != ".csv":
        p = p.with_suffix(".csv")
    return str(p)


# Calculation helpers
_UNITS_PER_CASE_RE = __import__("re").compile(r"(\d+)\s*/")


def _parse_units_per_case(pack_size: str) -> Optional[int]:
    m = _UNITS_PER_CASE_RE.search(pack_size or "")
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _parse_decimal(number_str: str) -> Optional[Decimal]:
    s = (number_str or "").strip()
    if not s:
        return None
    s = s.replace(",", "")
    try:
        return Decimal(s)
    except Exception:
        return None


def _quantize_2(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _round_to_next_nine_cents(amount: Decimal) -> Decimal:
    # Next price >= amount with hundredths digit equal to 9
    ten = Decimal("10")
    one_tenth_trunc = (amount * ten).to_integral_value(rounding=ROUND_FLOOR) / ten
    candidate = one_tenth_trunc + Decimal("0.09")
    if candidate < amount:
        candidate = one_tenth_trunc + Decimal("0.19")
    return _quantize_2(candidate)


def _compute_prices(pack_size: str, price_each: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    # Increase precision for intermediate arithmetic
    getcontext().prec = 28

    units = _parse_units_per_case(pack_size)
    case_price = _parse_decimal(price_each)
    if not units or not case_price or units == 0:
        return None, None, None

    per_product = _quantize_2(case_price / Decimal(units))
    store_base = per_product * Decimal("1.55") + Decimal("0.3")
    store_price = _round_to_next_nine_cents(store_base)
    online_price = _quantize_2(store_price + Decimal("0.50"))

    return (
        f"{per_product:.2f}",
        f"{store_price:.2f}",
        f"{online_price:.2f}",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pdf_scraper", description="PDF invoice scraper for Stark invoices")
    sub = p.add_subparsers(dest="subcmd", required=True)

    p_items = sub.add_parser("items", help="Extract line items to CSV file")
    p_items.add_argument("pdf", help="Path to invoice PDF")
    p_items.add_argument("--all-pages", dest="all_pages", action="store_true", help="Process all pages")
    p_items.add_argument(
        "--out",
        dest="out",
        default=None,
        help="Output CSV file path (default: <pdf>_items.csv)",
    )
    p_items.set_defaults(func=cmd_items)

    return p


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
