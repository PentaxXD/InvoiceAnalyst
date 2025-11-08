"""CLI entrypoint for the rebuilt Stark invoice analyst."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys
from typing import Iterable, Optional

from . import DEFAULT_ONLINE_MARKUP, DEFAULT_STORE_MARKUP, analyze_invoice_text
from .parser import InvoiceParsingError

CSV_HEADERS = [
    "Item",
    "Description",
    "Pack Size",
    "Quantity",
    "Price Each",
    "Amount",
    "Price Each Product",
    "Store Price",
    "Online Price",
]


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze Stark invoice text or PDFs.")
    parser.add_argument("input_path", help="Path to a Stark invoice (PDF or text).")
    parser.add_argument(
        "-o",
        "--output",
        help="Optional path for the generated CSV (defaults to stdout).",
    )
    parser.add_argument(
        "--input-format",
        choices=("auto", "pdf", "text"),
        default="auto",
        help="Force the parser to treat the input as PDF or plain text.",
    )
    parser.add_argument(
        "--store-markup",
        type=float,
        default=float(DEFAULT_STORE_MARKUP),
        help="Markup multiplier for the store price column.",
    )
    parser.add_argument(
        "--online-markup",
        type=float,
        default=float(DEFAULT_ONLINE_MARKUP),
        help="Markup multiplier for the online price column.",
    )

    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        invoice_text = _read_invoice(args.input_path, args.input_format)
    except RuntimeError as exc:  # pragma: no cover - input handling
        parser.error(str(exc))

    try:
        lines = analyze_invoice_text(
            invoice_text,
            store_markup=args.store_markup,
            online_markup=args.online_markup,
        )
    except InvoiceParsingError as exc:
        parser.error(f"Failed to parse invoice: {exc}")

    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", newline="", encoding="utf-8") as handle:
            _emit_csv(handle, lines)
    else:
        _emit_csv(sys.stdout, lines)

    return 0


def _read_invoice(path_str: str, input_format: str) -> str:
    path = Path(path_str)
    resolved_format = input_format
    if resolved_format == "auto":
        resolved_format = "pdf" if path.suffix.lower() == ".pdf" else "text"

    if resolved_format == "text":
        if not path.exists():
            raise RuntimeError(f"Input file not found: {path}")
        return path.read_text(encoding="utf-8")

    if resolved_format == "pdf":
        try:
            from pdfminer.high_level import extract_text
        except ImportError as exc:  # pragma: no cover - dependency missing
            raise RuntimeError(
                "pdfminer.six is required for PDF support. Install it with 'pip install pdfminer.six'."
            ) from exc

        if not path.exists():
            raise RuntimeError(f"Input file not found: {path}")
        return extract_text(path)

    raise RuntimeError(f"Unsupported input format: {resolved_format}")


def _emit_csv(handle, rows) -> None:
    writer = csv.DictWriter(handle, fieldnames=CSV_HEADERS)
    writer.writeheader()
    for row in rows:
        writer.writerow(row.to_csv_row())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
