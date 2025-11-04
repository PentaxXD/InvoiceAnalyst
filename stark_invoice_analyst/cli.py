"""Command line interface for Stark Invoice Analyst."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys
from typing import Iterable, Optional

from . import (
    DEFAULT_ONLINE_MARKUP,
    DEFAULT_STORE_MARKUP,
    analyze_invoice_text,
)
from .parser import InvoiceParsingError

CSV_FIELDS = [
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
    parser = argparse.ArgumentParser(description="Analyze Stark invoice PDFs or text dumps")
    parser.add_argument("input_path", help="Path to the invoice PDF or plain text file")
    parser.add_argument(
        "-o",
        "--output",
        help="Optional path for the generated CSV. Defaults to stdout when omitted",
    )
    parser.add_argument(
        "--input-format",
        choices=("auto", "pdf", "text"),
        default="auto",
        help="Force the parser to treat the input as PDF or text. Default is auto-detect",
    )
    parser.add_argument(
        "--store-markup",
        type=float,
        default=float(DEFAULT_STORE_MARKUP),
        help="Multiplier used to compute the Store Price column",
    )
    parser.add_argument(
        "--online-markup",
        type=float,
        default=float(DEFAULT_ONLINE_MARKUP),
        help="Multiplier used to compute the Online Price column",
    )

    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        text = _load_invoice_text(args.input_path, args.input_format)
    except RuntimeError as exc:  # pragma: no cover - user input error path
        parser.error(str(exc))

    try:
        analyzed = analyze_invoice_text(
            text,
            store_markup=args.store_markup,
            online_markup=args.online_markup,
        )
    except InvoiceParsingError as exc:
        parser.error(f"Failed to parse invoice: {exc}")

    if args.output:
        output_path = Path(args.output)
        with output_path.open("w", newline="", encoding="utf-8") as handle:
            _write_csv(handle, analyzed)
    else:
        _write_csv(sys.stdout, analyzed)

    return 0


def _load_invoice_text(path_str: str, input_format: str) -> str:
    path = Path(path_str)
    if input_format == "auto":
        input_format = "pdf" if path.suffix.lower() == ".pdf" else "text"

    if input_format == "text":
        if not path.exists():
            raise RuntimeError(f"Input file not found: {path}")
        return path.read_text(encoding="utf-8")

    if input_format == "pdf":
        try:
            from pdfminer.high_level import extract_text
        except ImportError as exc:  # pragma: no cover - executed only when dependency missing
            raise RuntimeError(
                "pdfminer.six is required to parse PDF files. Install it via 'pip install pdfminer.six'."
            ) from exc

        if not path.exists():
            raise RuntimeError(f"Input file not found: {path}")
        return extract_text(path)

    raise RuntimeError(f"Unsupported input format: {input_format}")


def _write_csv(file_obj, analyzed_lines) -> None:
    writer = csv.DictWriter(file_obj, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for line in analyzed_lines:
        writer.writerow(line.to_csv_row())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
