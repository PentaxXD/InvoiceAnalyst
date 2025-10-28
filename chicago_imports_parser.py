#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class InvoiceItem:
    quantity: int
    pack_size: str
    item: str
    rate: str  # keep as string preserving cents formatting
    amount: str  # keep as string preserving cents formatting


HEADER_ANCHOR = "Quantity Pack Size Item Rate Amount"

# Patterns
_QTY_PACK_RE = re.compile(r"^\s*(?P<qty>\d+)\s+(?P<pack>[0-9]+\/[0-9.]+)(?P<rest>.*)$")
_QTY_ONLY_RE = re.compile(r"^\s*(?P<qty>\d+)\s*$")
_PACK_ONLY_RE = re.compile(r"^\s*(?P<pack>[0-9]+\/[0-9.]+)\s*(?P<oz>OZ\.?)?\s*$", re.IGNORECASE)
_MONEY_RE = re.compile(r"\$\s*(?P<val>[0-9,]+\.[0-9]{2})")
_ITEM_CODE_PREFIX_RE = re.compile(r"^\s*(?P<code>\d{4,6})\s+(?P<name>.*\S)\s*$")

# Lines to skip after item pricing
_SKIP_EXACT = {
    "CDISC-1004 Customer - Holiday Preorder": True,
    "Holiday Preorder": True,
    # Common column headers and meta text from PDF extraction
    "Quantity": True,
    "Pack Size": True,
    "Item": True,
    "Rate": True,
    "Amount": True,
    "Sales Order": True,
    "Bill To": True,
    "Ship To": True,
    "TOTAL": True,
    "Terms": True,
    "Account": True,
    "PO #": True,
    "Shipping Method": True,
    "OZ": True,
}
_SKIP_CONTAINS = [
    "CDISC-1004 Customer - Holiday Preorder",
    "Holiday Preorder",
    "Order Con",  # matches both 'Confirmation' and 'Conﬁrmation'
    "Not an Invoice",
]


def _is_skip_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    if s in _SKIP_EXACT:
        return True
    for token in _SKIP_CONTAINS:
        if token in s:
            return True
    # discount percentage like "-5% $(11.16)"
    if re.search(r"-\s*\d+%", s):
        return True
    # Pagination markers like "1 of 16"
    if re.match(r"^\d+\s+of\s+\d+", s, flags=re.IGNORECASE):
        return True
    # Sales order id lines like SO2290048688
    if re.search(r"\bSO\d+", s):
        return True
    return False


def _normalize_space(text: str) -> str:
    # Keep line structure but trim trailing spaces
    return "\n".join(line.rstrip() for line in text.splitlines())


def parse_invoice_text(raw_text: str) -> List[InvoiceItem]:
    text = _normalize_space(raw_text)
    lines = text.splitlines()

    # Find anchor header
    start_index = 0
    for idx, line in enumerate(lines):
        if HEADER_ANCHOR.lower() in line.lower():
            start_index = idx + 1
            break

    i = start_index
    items: List[InvoiceItem] = []

    def peek(offset: int = 0) -> str:
        if 0 <= i + offset < len(lines):
            return lines[i + offset]
        return ""

    def _strip_oz_prefix(s: str) -> str:
        return re.sub(r"^\s*OZ\.?\s+", "", s, flags=re.IGNORECASE)

    while i < len(lines):
        line = lines[i].strip()

        # Skip blank or known non-item lines
        if not line or _is_skip_line(line):
            i += 1
            continue

        quantity: Optional[int] = None
        pack_ratio: Optional[str] = None
        pack_units = ""
        item_line_inline = ""

        qty_pack_match = _QTY_PACK_RE.match(line)
        if qty_pack_match:
            # Parsed quantity and pack ratio from single line
            quantity = int(qty_pack_match.group("qty"))
            pack_ratio = qty_pack_match.group("pack").strip()
            rest_after_pack = qty_pack_match.group("rest").strip()

            if rest_after_pack:
                oz_inline_match = re.search(r"\bOZ\b\.?", rest_after_pack)
                if oz_inline_match:
                    pack_units = "OZ"
                    item_line_inline = rest_after_pack[oz_inline_match.end():].strip()
                else:
                    item_line_inline = rest_after_pack
            else:
                # Check next line for OZ
                next_line = peek(1).strip()
                if next_line.upper() in {"OZ", "OZ."}:
                    pack_units = "OZ"
                    i += 1  # consume the OZ line
        else:
            # Try PDF-style split where qty is alone on a line and pack is on next
            qty_only = _QTY_ONLY_RE.match(line)
            if not qty_only:
                i += 1
                continue
            quantity = int(qty_only.group("qty"))
            # Find the next non-skip line containing the pack ratio
            j = i + 1
            while j < len(lines):
                s = lines[j].strip()
                if not s or _is_skip_line(s):
                    j += 1
                    continue
                mpack = _PACK_ONLY_RE.match(s)
                if mpack:
                    pack_ratio = mpack.group("pack").strip()
                    if mpack.group("oz"):
                        pack_units = "OZ"
                    j += 1
                else:
                    # If OZ is isolated on its own following line
                    if s.upper() in {"OZ", "OZ."}:
                        pack_units = "OZ"
                        j += 1
                    # Stop after examining first non-skip token
                break
            if pack_ratio is None:
                # Could not parse this as a real item block
                i += 1
                continue
            # Advance index to the first line after the pack/oz info
            i = j

        pack_size = f"{pack_ratio}{(' ' + pack_units) if pack_units else ''}".strip()

        # Resolve item name lines
        item_name_parts: List[str] = []

        def append_name_part(s: str) -> None:
            s = s.strip()
            if not s:
                return
            if not item_name_parts or item_name_parts[-1] != s:
                item_name_parts.append(s)

        # If there is inline content after units, try to parse item code/name from it
        consumed_inline_item_line = False
        if item_line_inline:
            item_line_inline = _strip_oz_prefix(item_line_inline)
            m_code = _ITEM_CODE_PREFIX_RE.match(item_line_inline)
            if m_code:
                append_name_part(m_code.group("name"))
            else:
                append_name_part(item_line_inline)
            consumed_inline_item_line = True

        # Advance to the first post-qty line if inline not used
        i += 1

        # If no inline item extracted, expect a line like "24921 Name..."
        if not consumed_inline_item_line:
            if i < len(lines):
                first_item_line = _strip_oz_prefix(lines[i].strip())
                # Some stray skip lines may appear; skip them
                while i < len(lines) and (not first_item_line or _is_skip_line(first_item_line)):
                    i += 1
                    if i < len(lines):
                        first_item_line = _strip_oz_prefix(lines[i].strip())
                if i < len(lines):
                    m_code_line = _ITEM_CODE_PREFIX_RE.match(first_item_line)
                    if m_code_line:
                        append_name_part(m_code_line.group("name"))
                    else:
                        append_name_part(first_item_line)
                    i += 1

        # Collect continuation lines until we hit pricing line (which starts with $) or next item starts
        while i < len(lines):
            probe = _strip_oz_prefix(lines[i].strip())
            if not probe:
                i += 1
                continue
            if probe.startswith("$"):
                break
            if _QTY_PACK_RE.match(probe) or _QTY_ONLY_RE.match(probe):
                # Next item has begun unexpectedly, stop collecting name
                break
            if _is_skip_line(probe):
                # discount blocks after pricing; but if encountered early, break out
                i += 1
                continue
            append_name_part(probe)
            i += 1

        # Expect pricing line now
        if i >= len(lines):
            # No pricing found; skip incomplete entry
            continue

        # Gather pricing tokens across subsequent lines (PDF may split them)
        found_prices: List[str] = []
        k = i
        while k < len(lines) and len(found_prices) < 2:
            s = lines[k].strip()
            if not s:
                k += 1
                continue
            if _QTY_PACK_RE.match(s) or _QTY_ONLY_RE.match(s):
                # Reached the next item; stop
                break
            if _is_skip_line(s):
                k += 1
                continue
            # Ignore negative amounts like '$(11.16)'
            if "$" in s and "$(" in s:
                k += 1
                continue
            money_vals = _MONEY_RE.findall(s)
            if money_vals:
                for mv in money_vals:
                    found_prices.append(mv)
                    if len(found_prices) >= 2:
                        break
            k += 1

        if not found_prices:
            # Could not find prices; skip this block
            i = max(i + 1, k)
            continue

        if len(found_prices) == 1:
            rate_val = amount_val = found_prices[0]
        else:
            rate_val, amount_val = found_prices[0], found_prices[1]

        # Compose item name
        # Prefer the longest part if it contains all other parts (handles duplicate/continuation cases)
        if item_name_parts:
            longest = max(item_name_parts, key=len)
            if all(p.lower() in longest.lower() for p in item_name_parts):
                item_name = longest
            else:
                # Fallback: join unique parts while removing immediate word duplicates
                joined = " ".join(item_name_parts)
                item_name = re.sub(r"\b(\w+)\s+\1\b", r"\1", joined, flags=re.IGNORECASE)
        else:
            item_name = ""

        items.append(
            InvoiceItem(
                quantity=quantity,
                pack_size=pack_size,
                item=item_name,
                rate=rate_val.replace(",", ""),
                amount=amount_val.replace(",", ""),
            )
        )

        # Move index to after price scan
        i = k
        # Skip any discount/holiday lines following
        while i < len(lines) and _is_skip_line(lines[i]):
            i += 1

    return items


def write_csv(items: List[InvoiceItem], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Quantity", "Pack Size", "Item", "Rate", "Amount"])
        for it in items:
            writer.writerow([it.quantity, it.pack_size, it.item, it.rate, it.amount])


def _read_input_text(input_path: Path) -> str:
    suffix = input_path.suffix.lower()
    if suffix == ".pdf":
        try:
            from pdfminer.high_level import extract_text  # type: ignore
        except Exception as exc:  # pragma: no cover - import error handling
            raise SystemExit(
                "PDF input detected but pdfminer.six is not installed. "
                "Install with: python3 -m pip install pdfminer.six"
            ) from exc
        return extract_text(str(input_path))
    # default: treat as text
    return input_path.read_text(encoding="utf-8", errors="ignore")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Parse Chicago Imports invoice text into CSV. "
            "Starts at 'Quantity Pack Size Item Rate Amount', and excludes CDISC/Holiday discount lines."
        )
    )
    parser.add_argument("input", type=Path, help="Path to input .txt or .pdf")
    parser.add_argument("output", type=Path, help="Path to output .csv")

    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"Input file not found: {args.input}")

    raw_text = _read_input_text(args.input)
    items = parse_invoice_text(raw_text)
    write_csv(items, args.output)


if __name__ == "__main__":
    main()
