#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
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

    # New robust strategy: parse by item-code lines (e.g., "24921 Name...")
    def _strip_oz_prefix(s: str) -> str:
        return re.sub(r"^\s*OZ\.?\s+", "", s, flags=re.IGNORECASE)

    items: List[InvoiceItem] = []
    items_meta: List[tuple[int, int, str, str]] = []  # (code_idx, qty, pack_size, item_name)

    # Helper to find nearest pack line above a given index
    def find_prev_pack(idx: int) -> tuple[Optional[str], str, int]:
        for j in range(idx - 1, max(-1, idx - 12), -1):
            s = lines[j].strip()
            if not s:
                continue
            if _is_skip_line(s):
                continue
            m = _PACK_ONLY_RE.match(s)
            if m:
                pack = m.group("pack").strip()
                units = "OZ" if m.group("oz") else ""
                return pack, units, j
        return None, "", -1

    def find_prev_qty(start_j: int) -> Optional[int]:
        for k in range(start_j - 1, max(-1, start_j - 8), -1):
            s = lines[k].strip()
            if not s or _is_skip_line(s):
                continue
            m = _QTY_ONLY_RE.match(s)
            if m:
                return int(m.group("qty"))
        return None

    # Gather all positive money values after the first 'Rate' label; keep positions
    first_rate_idx = next((idx for idx, l in enumerate(lines) if l.strip() == "Rate"), 0)
    money_tokens: List[tuple[int, str]] = []  # (line_idx, value)
    for li in range(first_rate_idx, len(lines)):
        s = lines[li].strip()
        if not s or "$(" in s:
            continue
        mvs = _MONEY_RE.findall(s)
        for mv in mvs:
            money_tokens.append((li, mv.replace(",", "")))

    idx = 0
    while idx < len(lines):
        s = lines[idx].strip()
        mcode = _ITEM_CODE_PREFIX_RE.match(s)
        if not mcode:
            idx += 1
            continue

        # Backtrack to get pack and qty
        pack_ratio, pack_units, pack_idx = find_prev_pack(idx)
        qty_val = find_prev_qty(pack_idx if pack_idx != -1 else idx)
        if pack_ratio is None or qty_val is None:
            idx += 1
            continue

        # Build item name (current line name + short continuation lines)
        def _norm_name(x: str) -> str:
            x = x.replace("®", " ")
            x = re.sub(r"\s+", " ", x)
            return x.strip().lower()

        name_parts: List[str] = []
        seen_norm: set[str] = set()
        first_name = mcode.group("name").strip()
        n0 = _norm_name(first_name)
        if n0 not in seen_norm:
            name_parts.append(first_name)
            seen_norm.add(n0)
        fwd = idx + 1
        while fwd < len(lines):
            probe = _strip_oz_prefix(lines[fwd].strip())
            if not probe:
                fwd += 1
                continue
            if _is_skip_line(probe):
                fwd += 1
                continue
            if _ITEM_CODE_PREFIX_RE.match(probe):
                break
            if _PACK_ONLY_RE.match(probe) or _QTY_ONLY_RE.match(probe) or probe.startswith("$"):
                break
            # Avoid runaway names; keep to 2 lines max beyond the code line
            np = _norm_name(probe)
            if np not in seen_norm:
                name_parts.append(probe)
                seen_norm.add(np)
            if len(name_parts) >= 3:
                break
            fwd += 1

        # Compose pack size string
        pack_size = f"{pack_ratio}{(' ' + pack_units) if pack_units else ''}".strip()

        # Compose item name (prefer the longest part covering others)
        longest = max(name_parts, key=lambda s: len(_norm_name(s)))
        if all(_norm_name(p) in _norm_name(longest) for p in name_parts):
            item_name = longest
        else:
            item_name = " ".join(name_parts)

        items_meta.append((idx, qty_val, pack_size, item_name))

        idx = fwd + 1

    # Second pass: assign prices using money tokens within a sliding window
    code_indices = [m[0] for m in items_meta]
    money_cursor = 0
    for i, (code_idx, qty_val, pack_size, item_name) in enumerate(items_meta):
        start = code_idx
        end = code_indices[i + 2] if i + 2 < len(code_indices) else len(lines)
        # Find first unused money token within [start, end)
        pos = money_cursor
        # advance to first token within window
        while pos < len(money_tokens) and not (start <= money_tokens[pos][0] < end):
            pos += 1
        if pos >= len(money_tokens):
            rate_val = amount_val = ""
        else:
            # rate token
            rate_val = money_tokens[pos][1]
            # find the next token within window after pos for amount
            pos2 = pos + 1
            while pos2 < len(money_tokens) and not (start <= money_tokens[pos2][0] < end):
                pos2 += 1
            if pos2 < len(money_tokens):
                amount_val = money_tokens[pos2][1]
                money_cursor = pos2 + 1
            else:
                amount_val = rate_val
                money_cursor = pos + 1
        if rate_val == "" and amount_val == "":
            rate_val = amount_val = ""

        items.append(
            InvoiceItem(
                quantity=qty_val,
                pack_size=pack_size,
                item=item_name,
                rate=rate_val,
                amount=amount_val,
            )
        )

    return items


def write_csv(items: List[InvoiceItem], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        # Categorization helpers
        def parse_pack_count(pack_size: str) -> Optional[int]:
            m = re.match(r"^\s*(\d+)\s*/", pack_size)
            return int(m.group(1)) if m else None

        def categorize_pack_count(pack_count: Optional[int]) -> str:
            if pack_count is None:
                return "Unknown"
            if pack_count <= 10:
                return "Small Pack"
            if pack_count <= 24:
                return "Medium Pack"
            if pack_count <= 60:
                return "Large Pack"
            return "Bulk Pack"

        def parse_rate_decimal(rate: str) -> Optional[Decimal]:
            try:
                return Decimal(rate)
            except (InvalidOperation, ValueError):
                return None

        def categorize_rate(rate_dec: Optional[Decimal]) -> str:
            if rate_dec is None:
                return "Unknown"
            if rate_dec < Decimal("50"):
                return "Low"
            if rate_dec < Decimal("100"):
                return "Medium"
            if rate_dec < Decimal("200"):
                return "High"
            return "Premium"

        def compute_price_each(rate_dec: Optional[Decimal], pack_count: Optional[int]) -> Optional[Decimal]:
            if rate_dec is None or not pack_count or pack_count <= 0:
                return None
            return (rate_dec / Decimal(pack_count))

        def round_to_next_9_cents(x: Decimal) -> Decimal:
            # Find the smallest y >= x of the form N + k/10 + 0.09 (i.e., cents end with 9)
            tenths_floor = (x * Decimal('10')).to_integral_value(rounding=ROUND_FLOOR) / Decimal('10')
            candidate = tenths_floor + Decimal('0.09')
            if candidate < x:
                candidate = candidate + Decimal('0.10')
            return candidate.quantize(Decimal('0.01'))

        def fmt_money(d: Optional[Decimal]) -> str:
            return f"{d.quantize(Decimal('0.01')):.2f}" if d is not None else ""

        headers = [
            "Quantity",
            "Pack Size",
            "Item",
            "Rate",
            "Amount",
            "Price Each",
            "Store Price",
            "Online Price",
        ]
        writer.writerow(headers)
        for it in items:
            pack_count = parse_pack_count(it.pack_size)
            rate_dec = parse_rate_decimal(it.rate)
            price_each = compute_price_each(rate_dec, pack_count)
            store_price = round_to_next_9_cents((price_each * Decimal('1.55') + Decimal('0.30'))) if price_each is not None else None
            online_price = (store_price + Decimal('0.50')).quantize(Decimal('0.01')) if store_price is not None else None
            writer.writerow([
                it.quantity,
                it.pack_size,
                it.item,
                it.rate,
                it.amount,
                fmt_money(price_each),
                fmt_money(store_price),
                fmt_money(online_price),
            ])


def _read_input_text(input_path: Path) -> str:
    suffix = input_path.suffix.lower()
    if suffix == ".pdf":
        try:
            from pdfminer.high_level import extract_text  # type: ignore
        except Exception:
            # Graceful fallback when pdfminer.six is not available
            # Return empty text so downstream still writes a CSV header
            return ""
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
    items = parse_invoice_text(raw_text)
    out_path = args.output or (args.input.parent / f"{args.input.stem}_parsed.csv")
    write_csv(items, out_path)


if __name__ == "__main__":
    main()
