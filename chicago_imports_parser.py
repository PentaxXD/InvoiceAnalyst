#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from pathlib import Path
from typing import List, Optional, Dict, Any


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
_COMBINED_QTY_PACK_CODE_RE = re.compile(
    r"^\s*(?P<qty>\d+)\s+(?P<pack>[0-9]+\/[0-9.]+)(?:\s*(?P<oz>OZ\.?))?\s+(?P<code>\d{4,6})\s+(?P<name>.*\S)\s*$",
    re.IGNORECASE,
)

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


def parse_invoice_text(raw_text: str, debug_trace: Optional[List[Dict[str, Any]]] = None) -> List[InvoiceItem]:
    text = _normalize_space(raw_text)
    lines = text.splitlines()

    # Helpers
    def _strip_oz_prefix(s: str) -> str:
        return re.sub(r"^\s*OZ\.?\s+", "", s, flags=re.IGNORECASE)

    def _norm_name(x: str) -> str:
        x = x.replace("®", " ")
        x = re.sub(r"\s+", " ", x)
        return x.strip()

    def is_item_header_combined(line: str) -> Optional[re.Match]:
        return _COMBINED_QTY_PACK_CODE_RE.match(line)

    def match_qty_pack(line: str) -> Optional[re.Match]:
        # e.g., "2 10/3.5 OZ" or "2 10/3.5"
        m = re.match(r"^\s*(?P<qty>\d+)\s+(?P<pack>[0-9]+\/[0-9.]+)(?:\s*(?P<oz>OZ\.?))?\s*$", line, flags=re.IGNORECASE)
        return m

    def match_code_name(line: str) -> Optional[re.Match]:
        return _ITEM_CODE_PREFIX_RE.match(line)

    def is_qty_only(line: str) -> Optional[int]:
        m = _QTY_ONLY_RE.match(line)
        return int(m.group("qty")) if m else None

    def is_header_start(line: str) -> bool:
        return bool(is_item_header_combined(line) or match_qty_pack(line) or is_qty_only(line))

    items: List[InvoiceItem] = []
    items_info: List[Dict[str, Any]] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        # Skip known non-item lines quickly
        if _is_skip_line(line):
            i += 1
            continue

        # Try combined header
        mcomb = is_item_header_combined(line)
        if mcomb:
            qty = int(mcomb.group("qty"))
            pack_ratio = mcomb.group("pack").strip()
            pack_units = "OZ" if mcomb.group("oz") else ""
            item_name = _norm_name(mcomb.group("name").strip())
            header_idx = i
            code_idx = i
            i += 1
        else:
            # Try split header: qty+pack on this line, code on next non-skip line within 2 lines
            mqp = match_qty_pack(line)
            if mqp:
                qty = int(mqp.group("qty"))
                pack_ratio = mqp.group("pack").strip()
                pack_units = "OZ" if mqp.group("oz") else ""
                header_idx = i
                # Allow optional OZ line on next line (already handled), then code line
                j = i + 1
                # Skip blank/skip lines up to 2 steps to find code
                steps = 0
                mcode = None
                while j < len(lines) and steps <= 2:
                    cand = _strip_oz_prefix(lines[j].strip())
                    if not cand or _is_skip_line(cand):
                        j += 1
                        steps += 1
                        continue
                    mcode = match_code_name(cand)
                    if mcode:
                        break
                    else:
                        # Not a code-name; abort split header
                        mcode = None
                        break
                if not mcode:
                    i += 1
                    continue
                item_name = _norm_name(mcode.group("name").strip())
                code_idx = j
                # Advance i to first line after code
                i = j + 1
            else:
                # Try split header variant: qty on its own line, then pack line next (or within 1), then optional OZ line, then code line
                qty_only = is_qty_only(line)
                if qty_only is not None:
                    # find pack in next 2 lines
                    j = i + 1
                    pack_ratio = None
                    pack_units = ""
                    found_pack_at = -1
                    for look in range(0, 2):
                        if j + look >= len(lines):
                            break
                        cand = lines[j + look].strip()
                        mp = _PACK_ONLY_RE.match(cand)
                        if mp:
                            pack_ratio = mp.group("pack").strip()
                            if mp.group("oz"):
                                pack_units = "OZ"
                            found_pack_at = j + look
                            break
                    if pack_ratio is None:
                        i += 1
                        continue
                    # Find code-name within next 2 non-skip lines after pack
                    code_idx = -1
                    mcode = None
                    k = found_pack_at + 1
                    hops = 0
                    while k < len(lines) and hops <= 3:
                        cand2 = _strip_oz_prefix(lines[k].strip())
                        if not cand2 or _is_skip_line(cand2):
                            k += 1
                            hops += 1
                            continue
                        mcode = match_code_name(cand2)
                        if mcode:
                            code_idx = k
                            break
                        else:
                            mcode = None
                            break
                    if not mcode:
                        i += 1
                        continue
                    qty = qty_only
                    item_name = _norm_name(mcode.group("name").strip())
                    header_idx = i
                    # advance i to after code line
                    i = code_idx + 1
                else:
                    i += 1
                    continue

        pack_size = f"{pack_ratio}{(' ' + pack_units) if pack_units else ''}".strip()

        # Defer price assignment to global sequential mapping
        rate_val = ""
        amount_val = ""
        rate_line = -1
        amount_line = -1

        # Record item
        items_info.append({
            "qty": qty,
            "pack_size": pack_size,
            "item": item_name,
            "rate": rate_val,
            "amount": amount_val,
            "rate_line": rate_line,
            "amount_line": amount_line,
        })

        if debug_trace is not None:
            debug_trace.append({
                "header_idx": header_idx,
                "code_idx": code_idx,
                "qty": qty,
                "pack_size": pack_size,
                "item": item_name,
                "rate": rate_val,
                "amount": amount_val,
                "rate_line": rate_line,
                "amount_line": amount_line,
            })

    # Global assignment for missing prices: collect all positive $ tokens and map two per item
    # Build token list
    money_tokens: List[tuple[int, str]] = []
    # Start after the first 'Rate' label to avoid totals/header noise
    start_idx = 0
    for idx_line, content in enumerate(lines):
        if content.strip().lower() == 'rate':
            start_idx = idx_line
            break
    for li in range(start_idx, len(lines)):
        s = lines[li]
        st = s.strip()
        if not st or "$(" in st:
            continue
        for mv in _MONEY_RE.findall(st):
            if f"$({mv})" in st:
                continue
            money_tokens.append((li, mv.replace(",", "")))
    # Exclude tokens already used within-block
    used_lines = set()
    for info in items_info:
        if info["rate_line"] >= 0:
            used_lines.add(info["rate_line"])
        if info["amount_line"] >= 0:
            used_lines.add(info["amount_line"])
    # Cursor over remaining tokens
    cur = 0
    def next_token() -> Optional[str]:
        nonlocal cur
        while cur < len(money_tokens):
            li, val = money_tokens[cur]
            cur += 1
            if li in used_lines:
                continue
            return val
        return None

    for info in items_info:
        if not info["rate"] or not info["amount"]:
            if not info["rate"]:
                t = next_token()
                if t is not None:
                    info["rate"] = t
            if not info["amount"]:
                t2 = next_token()
                if t2 is not None:
                    info["amount"] = t2
            # If still missing amount but have rate and qty>1, compute
            try:
                if info["rate"] and not info["amount"] and info["qty"] > 1:
                    rv = Decimal(info["rate"])
                    info["amount"] = f"{(rv * Decimal(info["qty"])) .quantize(Decimal('0.01'))}"
            except Exception:
                pass

    # Build final items
    for info in items_info:
        items.append(
            InvoiceItem(
                quantity=info["qty"],
                pack_size=info["pack_size"],
                item=info["item"],
                rate=info["rate"],
                amount=info["amount"],
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


def _ensure_pdfminer_extract_text():
    try:
        from pdfminer.high_level import extract_text  # type: ignore
        return extract_text
    except Exception:
        # Try installing pdfminer.six for the current user silently
        try:
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
            from pdfminer.high_level import extract_text  # type: ignore
            return extract_text
        except Exception:
            return None


def _read_input_text(input_path: Path) -> str:
    suffix = input_path.suffix.lower()
    if suffix == ".pdf":
        extract_text = _ensure_pdfminer_extract_text()
        if extract_text is None:
            # As a last resort, return empty text; caller will still write headers
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
