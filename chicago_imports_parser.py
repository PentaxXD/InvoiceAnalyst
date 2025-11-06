#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


@dataclass
class InvoiceItem:
    order_qty: int
    shipped_qty: int
    item_code: str
    description: str
    pack_size: str
    case_price: str
    unit_price: str
    extended_price: str


@dataclass
class _TextFragment:
    text: str
    x0: float
    x1: float
    y0: float
    y1: float
    page: int

    @property
    def y_center(self) -> float:
        return (self.y0 + self.y1) / 2.0


@dataclass
class _RowAssembly:
    y: float
    page: int
    order_qty: Optional[int] = None
    shipped_qty: Optional[int] = None
    item_code: Optional[str] = None
    description_parts: List[str] = field(default_factory=list)
    pack_size_parts: List[str] = field(default_factory=list)
    catch_weight_parts: List[str] = field(default_factory=list)
    case_price: Optional[str] = None
    unit_price: Optional[str] = None
    extended_price: Optional[str] = None

    def build_item(self) -> Optional[InvoiceItem]:
        if (
            self.order_qty is None
            or self.shipped_qty is None
            or not self.item_code
            or not self.description_parts
            or not self.pack_size_parts
            or not self.extended_price
        ):
            return None
        description = _collapse_text(self.description_parts)
        pack_size = _collapse_text(self.pack_size_parts)
        catch_weight = _collapse_text(self.catch_weight_parts)
        case_price = self.case_price or ""
        unit_price = self.unit_price or ""
        extended_price = self.extended_price or ""

        if catch_weight and case_price and case_price.startswith("$") and not unit_price:
            unit_price = case_price
            case_price = catch_weight
        elif catch_weight and not case_price:
            case_price = catch_weight

        if not unit_price and case_price.startswith("$"):
            unit_price = case_price
            case_price = ""

        if not unit_price.strip():
            unit_price = "N/A"

        return InvoiceItem(
            order_qty=self.order_qty,
            shipped_qty=self.shipped_qty,
            item_code=self.item_code,
            description=description,
            pack_size=pack_size,
            case_price=case_price,
            unit_price=unit_price,
            extended_price=extended_price,
        )


_ROW_Y_TOLERANCE = 16.0

_COLUMN_RANGES: Dict[str, Tuple[float, float]] = {
    "order": (30.0, 75.0),
    "shipped": (75.0, 100.0),
    "item": (100.0, 150.0),
    "description": (150.0, 320.0),
    "pack": (320.0, 380.0),
    "catch": (380.0, 440.0),
    "case": (440.0, 480.0),
    "unit": (480.0, 520.0),
    "extended": (520.0, 620.0),
}

_SKIP_EXACT = {
    "Bill To",
    "Ship To",
    "Terms",
    "Due Date",
    "PO #",
    "Customer",
    "Contact",
    "Shipping Method",
    "Sales Order #",
    "Customer #",
    "Order",
    "Qty",
    "Shipped",
    "Item",
    "Description",
    "Pack",
    "Size",
    "Catch",
    "Wt.(LBS)",
    "Case",
    "Unit",
    "Extended",
    "Price",
    "Net 20",
    "PREORDER",
    "Best Way",
    "United States",
}

_SKIP_PREFIXES = (
    "Invoice #",
    "Date Shipped:",
    "Total Due:",
    "Date Due:",
    "11/23/",
    "SO",
    "P:",
    "chicagoimporting.com",
    "11200 E.",
    "Huntley IL",
)

_SKIP_CONTAINS = (
    "CDISC-1004",
    "Holiday Preorder",
    "Customer - Holiday",
)


def _collapse_text(parts: Iterable[str]) -> str:
    return " ".join(p.strip() for p in parts if p.strip())


def _ensure_pdfminer() -> Tuple[Any, Any, Any, Any, Any]:
    try:
        from pdfminer.high_level import extract_pages, extract_text  # type: ignore
        from pdfminer.layout import LAParams, LTTextBoxHorizontal, LTTextLineHorizontal  # type: ignore
    except Exception:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--user",
                "--disable-pip-version-check",
                "-q",
                "pdfminer.six",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        from pdfminer.high_level import extract_pages, extract_text  # type: ignore
        from pdfminer.layout import LAParams, LTTextBoxHorizontal, LTTextLineHorizontal  # type: ignore
    return extract_pages, extract_text, LAParams, LTTextBoxHorizontal, LTTextLineHorizontal


def _should_skip_fragment(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if stripped in _SKIP_EXACT:
        return True
    for prefix in _SKIP_PREFIXES:
        if stripped.startswith(prefix):
            return True
    for token in _SKIP_CONTAINS:
        if token in stripped:
            return True
    if stripped == "-5%":
        return True
    if stripped.startswith("$("):
        return True
    if stripped.lower().startswith("page "):
        return True
    if stripped.endswith(" of 11"):
        return True
    if stripped.replace(" ", "").lower().startswith("date shipped"):
        return True
    return False


def _looks_like_discount_value(text: str) -> bool:
    return text.startswith("$(")


def _iter_text_lines(layout_obj: Any, line_class: Any) -> Iterable[Any]:
    if isinstance(layout_obj, line_class):
        yield layout_obj
        return
    if hasattr(layout_obj, "__iter__"):
        for child in layout_obj:
            yield from _iter_text_lines(child, line_class)


def _collect_text_fragments(pdf_path: Path) -> List[_TextFragment]:
    extract_pages, _, LAParams, _, LTTextLineHorizontal = _ensure_pdfminer()
    laparams = LAParams(line_margin=0.10, char_margin=2.0, word_margin=0.1)
    fragments: List[_TextFragment] = []
    for page_number, page_layout in enumerate(extract_pages(str(pdf_path), laparams=laparams), start=1):
        for line in _iter_text_lines(page_layout, LTTextLineHorizontal):
            text = line.get_text().strip()
            if not text:
                continue
            x0, y0, x1, y1 = line.bbox
            fragments.append(_TextFragment(text=text, x0=x0, x1=x1, y0=y0, y1=y1, page=page_number))
    return fragments


def _looks_like_order_seed(frag: _TextFragment) -> bool:
    if not frag.text.isdigit():
        return False
    lower, upper = _COLUMN_RANGES["order"]
    return lower <= frag.x0 <= upper


def _find_row(rows: List[_RowAssembly], frag: _TextFragment) -> Optional[_RowAssembly]:
    yc = frag.y_center
    best: Optional[_RowAssembly] = None
    best_delta = _ROW_Y_TOLERANCE
    for row in rows:
        if row.page != frag.page:
            continue
        delta = abs(row.y - yc)
        if delta < best_delta:
            best = row
            best_delta = delta
    return best


def _parse_invoice_pdf(pdf_path: Path, debug_trace: Optional[List[Dict[str, Any]]]) -> List[InvoiceItem]:
    fragments = _collect_text_fragments(pdf_path)
    if not fragments:
        return []

    rows: List[_RowAssembly] = []
    for frag in fragments:
        if _looks_like_order_seed(frag):
            rows.append(_RowAssembly(y=frag.y_center, page=frag.page, order_qty=int(frag.text)))

    rows.sort(key=lambda r: (r.page, -r.y))
    if not rows:
        return []

    for frag in fragments:
        text = frag.text.strip()
        if not text:
            continue
        if _should_skip_fragment(text):
            continue

        row = _find_row(rows, frag)
        if row is None:
            continue

        x0 = frag.x0
        if _COLUMN_RANGES["order"][0] <= x0 <= _COLUMN_RANGES["order"][1] and text.isdigit():
            row.order_qty = int(text)
        elif _COLUMN_RANGES["item"][0] <= x0 <= _COLUMN_RANGES["item"][1] and text.replace(" ", "").isdigit():
            row.item_code = text.replace(" ", "")
        elif _COLUMN_RANGES["shipped"][0] <= x0 <= _COLUMN_RANGES["shipped"][1] and text.isdigit():
            row.shipped_qty = int(text)
        elif _COLUMN_RANGES["pack"][0] <= x0 <= _COLUMN_RANGES["pack"][1]:
            row.pack_size_parts.append(text)
        elif _COLUMN_RANGES["description"][0] <= x0 <= _COLUMN_RANGES["description"][1]:
            row.description_parts.append(text)
        elif _COLUMN_RANGES["catch"][0] <= x0 <= _COLUMN_RANGES["catch"][1]:
            row.catch_weight_parts.append(text)
        elif _COLUMN_RANGES["case"][0] <= x0 <= _COLUMN_RANGES["case"][1]:
            if not _looks_like_discount_value(text):
                row.case_price = text
        elif _COLUMN_RANGES["unit"][0] <= x0 <= _COLUMN_RANGES["unit"][1]:
            if not _looks_like_discount_value(text):
                row.unit_price = text
        elif _COLUMN_RANGES["extended"][0] <= x0 <= _COLUMN_RANGES["extended"][1]:
            if not _looks_like_discount_value(text):
                row.extended_price = text

    items: List[InvoiceItem] = []
    for row in rows:
        item = row.build_item()
        if item is None:
            continue
        items.append(item)
        if debug_trace is not None:
            debug_trace.append(
                {
                    "page": row.page,
                    "y": row.y,
                    "order_qty": row.order_qty,
                    "shipped_qty": row.shipped_qty,
                    "item_code": row.item_code,
                    "description": _collapse_text(row.description_parts),
                    "pack_size": _collapse_text(row.pack_size_parts),
                    "case_price": row.case_price,
                    "unit_price": row.unit_price,
                    "extended_price": row.extended_price,
                }
            )

    return items


def _parse_invoice_text_block(raw_text: str) -> List[InvoiceItem]:
    raise ValueError(
        "Parsing raw text exports is not supported for the new invoice format; provide a PDF file instead."
    )


def parse_invoice_text(
    raw_text: str,
    *,
    source_path: Optional[Path] = None,
    debug_trace: Optional[List[Dict[str, Any]]] = None,
) -> List[InvoiceItem]:
    if source_path and source_path.suffix.lower() == ".pdf":
        return _parse_invoice_pdf(source_path, debug_trace)
    return _parse_invoice_text_block(raw_text)


def write_csv(items: List[InvoiceItem], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        headers = [
            "Order_Qty",
            "Shipped_Qty",
            "Item",
            "Description",
            "Pack_Size",
            "Case_Price",
            "Unit_Price",
            "Extended_Price",
        ]
        writer.writerow(headers)
        for item in items:
            writer.writerow(
                [
                    item.order_qty,
                    item.shipped_qty,
                    item.item_code,
                    item.description,
                    item.pack_size,
                    item.case_price,
                    item.unit_price,
                    item.extended_price,
                ]
            )


def _read_input_text(input_path: Path) -> str:
    suffix = input_path.suffix.lower()
    if suffix == ".pdf":
        _, extract_text, _, _, _ = _ensure_pdfminer()
        return extract_text(str(input_path))
    return input_path.read_text(encoding="utf-8", errors="ignore")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse Chicago Imports invoice PDFs into CSV using the newer format layout",
    )
    parser.add_argument("input", type=Path, help="Path to input .pdf (or .txt for legacy exports)")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Path to output .csv (default: <input>_parsed.csv)",
    )

    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"Input file not found: {args.input}")

    raw_text = _read_input_text(args.input)
    try:
        items = parse_invoice_text(raw_text, source_path=args.input)
    except ValueError as exc:
        raise SystemExit(f"Failed to parse invoice: {exc}")

    default_out = Path("output") / "invoice_items.csv"
    if args.output:
        out_path = args.output
    else:
        # Use output/invoice_items.csv by default to avoid recreating the source path tree
        out_path = default_out
    write_csv(items, out_path)


if __name__ == "__main__":
    main()
