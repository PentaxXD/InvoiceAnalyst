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
_MONEY_RE = re.compile(r"\$\s*(?P<val>[0-9,]+\.[0-9]{2})")
_ITEM_CODE_PREFIX_RE = re.compile(r"^\s*(?P<code>\d{4,6})\s+(?P<name>.*\S)\s*$")

# Lines to skip after item pricing
_SKIP_EXACT = {
    "CDISC-1004 Customer - Holiday Preorder": True,
    "Holiday Preorder": True,
}
_SKIP_CONTAINS = [
    "CDISC-1004 Customer - Holiday Preorder",
    "Holiday Preorder",
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

    while i < len(lines):
        line = lines[i].strip()

        # Skip blank or known non-item lines
        if not line or _is_skip_line(line):
            i += 1
            continue

        qty_pack_match = _QTY_PACK_RE.match(line)
        if not qty_pack_match:
            # Not the start of an item block; skip
            i += 1
            continue

        # Parsed quantity and pack ratio
        quantity = int(qty_pack_match.group("qty"))
        pack_ratio = qty_pack_match.group("pack").strip()
        rest_after_pack = qty_pack_match.group("rest").strip()

        # Some formats split "OZ" into the next line
        pack_units = ""
        item_line_inline = ""

        if rest_after_pack:
            # Rest could contain units (OZ) and possibly start of item code/name
            # Try to capture an inline units token followed by anything else
            # Heuristics: look for ' OZ ' or ending with ' OZ'
            oz_inline_match = re.search(r"\bOZ\b\.?", rest_after_pack)
            if oz_inline_match:
                pack_units = "OZ"
                item_line_inline = rest_after_pack[oz_inline_match.end():].strip()
            else:
                # No OZ here; maybe item starts right away (rare) or units on next line
                item_line_inline = rest_after_pack
        else:
            # Check next line for OZ
            next_line = peek(1).strip()
            if next_line.upper() in {"OZ", "OZ."}:
                pack_units = "OZ"
                i += 1  # consume the OZ line

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
                first_item_line = lines[i].strip()
                # Some stray skip lines may appear; skip them
                while i < len(lines) and (not first_item_line or _is_skip_line(first_item_line)):
                    i += 1
                    if i < len(lines):
                        first_item_line = lines[i].strip()
                if i < len(lines):
                    m_code_line = _ITEM_CODE_PREFIX_RE.match(first_item_line)
                    if m_code_line:
                        append_name_part(m_code_line.group("name"))
                    else:
                        append_name_part(first_item_line)
                    i += 1

        # Collect continuation lines until we hit pricing line (which starts with $) or next item starts
        while i < len(lines):
            probe = lines[i].strip()
            if not probe:
                i += 1
                continue
            if probe.startswith("$"):
                break
            if _QTY_PACK_RE.match(probe):
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

        price_line = lines[i].strip()
        if not price_line.startswith("$"):
            # Search ahead up to 2 lines for a price line, to be resilient
            lookahead_found = False
            for j in range(1, 3):
                if i + j < len(lines) and lines[i + j].strip().startswith("$"):
                    i = i + j
                    price_line = lines[i].strip()
                    lookahead_found = True
                    break
            if not lookahead_found:
                # Could not find prices; skip this block
                continue

        money_vals = _MONEY_RE.findall(price_line)
        if len(money_vals) >= 2:
            rate_val, amount_val = money_vals[0], money_vals[1]
        elif len(money_vals) == 1:
            rate_val, amount_val = money_vals[0], money_vals[0]
        else:
            # No prices found; skip
            i += 1
            continue

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

        # Move past pricing line
        i += 1
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Parse Chicago Imports invoice text into CSV. "
            "Starts at 'Quantity Pack Size Item Rate Amount', and excludes CDISC/Holiday discount lines."
        )
    )
    parser.add_argument("input", type=Path, help="Path to input .txt (raw text from invoice)")
    parser.add_argument("output", type=Path, help="Path to output .csv")

    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"Input file not found: {args.input}")

    raw_text = args.input.read_text(encoding="utf-8", errors="ignore")
    items = parse_invoice_text(raw_text)
    write_csv(items, args.output)


if __name__ == "__main__":
    main()
