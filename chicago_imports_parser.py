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


def parse_invoice_text(raw_text: str) -> List[InvoiceItem]:
    text = _normalize_space(raw_text)
    lines = text.splitlines()

    # New robust strategy: parse by item-code lines (e.g., "24921 Name...")
    def _strip_oz_prefix(s: str) -> str:
        return re.sub(r"^\s*OZ\.?\s+", "", s, flags=re.IGNORECASE)

    items: List[InvoiceItem] = []
    items_meta: List[tuple[int, Optional[int], str, str]] = []  # (code_idx, qty?, pack_size, item_name)

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
        # Look backward up to 40 lines
        for k in range(start_j - 1, max(-1, start_j - 40), -1):
            s = lines[k].strip()
            if not s or _is_skip_line(s):
                continue
            m = _QTY_ONLY_RE.match(s)
            if m:
                return int(m.group("qty"))
        # Fallback: look forward a few lines in case quantity is below the pack
        for k in range(start_j + 1, min(len(lines), start_j + 6)):
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
        mcomb = _COMBINED_QTY_PACK_CODE_RE.match(s)
        if mcomb:
            # Quantity, pack, optional OZ, code and name all on one line
            qty_val: Optional[int] = int(mcomb.group("qty"))
            pack_ratio = mcomb.group("pack").strip()
            pack_units = "OZ" if mcomb.group("oz") else ""
            first_name = mcomb.group("name").strip()

            def _norm_name(x: str) -> str:
                x = x.replace("®", " ")
                x = re.sub(r"\s+", " ", x)
                return x.strip().lower()

            name_parts: List[str] = [first_name]
            seen_norm: set[str] = {_norm_name(first_name)}
            fwd = idx + 1
            while fwd < len(lines):
                probe = _strip_oz_prefix(lines[fwd].strip())
                if not probe:
                    fwd += 1
                    continue
                if _is_skip_line(probe):
                    fwd += 1
                    continue
                if _ITEM_CODE_PREFIX_RE.match(probe) or _COMBINED_QTY_PACK_CODE_RE.match(probe):
                    break
                if _PACK_ONLY_RE.match(probe) or _QTY_ONLY_RE.match(probe) or probe.startswith("$"):
                    break
                np = _norm_name(probe)
                if np not in seen_norm:
                    name_parts.append(probe)
                    seen_norm.add(np)
                if len(name_parts) >= 3:
                    break
                fwd += 1

            pack_size = f"{pack_ratio}{(' ' + pack_units) if pack_units else ''}".strip()
            longest = max(name_parts, key=lambda s: len(_norm_name(s)))
            item_name = longest if all(_norm_name(p) in _norm_name(longest) for p in name_parts) else " ".join(name_parts)
            items_meta.append((idx, qty_val, pack_size, item_name))
            idx = fwd + 1
            continue

        mcode = _ITEM_CODE_PREFIX_RE.match(s)
        if not mcode:
            idx += 1
            continue

        # Backtrack to get pack and qty
        pack_ratio, pack_units, pack_idx = find_prev_pack(idx)
        qty_val: Optional[int] = find_prev_qty(pack_idx if pack_idx != -1 else idx)
        if pack_ratio is None:
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
            if _ITEM_CODE_PREFIX_RE.match(probe) or _COMBINED_QTY_PACK_CODE_RE.match(probe):
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
        end = min(len(lines), code_idx + 200)
        # Primary: scan forward and pick a pair that matches the expected quantity if known
        Token = tuple[int, Decimal, str]
        local_tokens: List[Token] = []
        same_line_pairs: List[tuple[str, str]] = []
        for li in range(start, end):
            s = lines[li].strip()
            if not s or "$(" in s:
                continue
            mvs = _MONEY_RE.findall(s)
            if not mvs:
                continue
            if len(mvs) >= 2:
                same_line_pairs.append((mvs[0].replace(",", ""), mvs[1].replace(",", "")))
            for mv in mvs:
                try:
                    d = Decimal(mv.replace(",", ""))
                except Exception:
                    continue
                local_tokens.append((li, d, mv.replace(",", "")))

        def choose_pair_with_qty(tokens: List[Token], qty: int) -> Optional[tuple[str, str]]:
            # Prefer same-line pairs that match qty
            for li in range(start, end):
                # reconstruct line tokens
                line_vals = [t for t in local_tokens if t[0] == li]
                if len(line_vals) >= 2:
                    r = line_vals[0][1]
                    a = line_vals[1][1]
                    if r > 0 and int((a / r).to_integral_value()) == qty:
                        return (line_vals[0][2], line_vals[1][2])
            # Next, sliding window pairs
            for idx_r, (li_r, r, rs) in enumerate(tokens):
                for idx_a in range(idx_r + 1, min(len(tokens), idx_r + 12)):
                    li_a, a, as_ = tokens[idx_a]
                    if r > 0 and int((a / r).to_integral_value()) == qty:
                        return (rs, as_)
            return None

        selected_pair: Optional[tuple[str, str]] = None
        if qty_val is not None:
            selected_pair = choose_pair_with_qty(local_tokens, qty_val)
        if selected_pair is None and same_line_pairs:
            selected_pair = same_line_pairs[0]
        if selected_pair is None and local_tokens:
            # As a last local attempt, pick first token and next with integer multiple <= 100
            r_li, r, rs = local_tokens[0]
            amount_s = rs
            for _, a, as_ in local_tokens[1:12]:
                if r > 0:
                    q = a / r
                    q_int = int(q.to_integral_value())
                    if 1 <= q_int <= 100:
                        amount_s = as_
                        break
            selected_pair = (rs, amount_s)

        if selected_pair is not None:
            rate_val, amount_val = selected_pair
        else:
            # Global fallback with ordering, keep advancing the global cursor
            if money_cursor + 1 < len(money_tokens):
                rate_val = money_tokens[money_cursor][1]
                amount_val = money_tokens[money_cursor + 1][1]
                money_cursor += 2
            elif money_cursor < len(money_tokens):
                rate_val = amount_val = money_tokens[money_cursor][1]
                money_cursor += 1
            else:
                rate_val = amount_val = ""

        # Derive quantity if missing from prices (qty ≈ amount / rate)
        final_qty: int
        if qty_val is not None:
            final_qty = qty_val
        else:
            try:
                r = Decimal(rate_val)
                a = Decimal(amount_val)
                if r > 0:
                    q_est = int((a / r).to_integral_value())
                    final_qty = q_est if q_est > 0 else 1
                else:
                    final_qty = 1
            except Exception:
                final_qty = 1

        items.append(
            InvoiceItem(
                quantity=final_qty,
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
