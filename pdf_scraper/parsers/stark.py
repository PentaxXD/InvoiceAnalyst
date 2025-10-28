import re
from typing import List, Dict, Optional, Tuple


ROW_START_RE = re.compile(r"^([0-9A-Z]{1,3})\s+([0-9]{1,3}-[0-9][0-9\-]*)\s+(.*)$")
TRAILING_NUMBERS_RE = re.compile(r"^(.*?\S)\s+(\d+)\s+([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)\s+([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)\s*$")
PACK_AT_END_RE = re.compile(r"^(.*?\S)\s+(\d+\s*/\s*\d+\s*(?:G|g|KG|kg|Kg)\.?)(?:\s*)$")


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _normalize_pack_size(text: str) -> str:
    # Remove trailing period and normalize units to uppercase G/KG
    text = text.strip()
    if text.endswith("."):
        text = text[:-1]
    # Normalize unit casing
    text = re.sub(r"\b([Gg])\b", "G", text)
    text = re.sub(r"\b[Kk][Gg]\b", "KG", text)
    # Collapse inner whitespace
    return _normalize_whitespace(text)


def _title_case_description(text: str) -> str:
    # Basic title case, then fix known abbreviations/acronyms common in these invoices
    t = text.strip().title()
    # Fix specific tokens
    fixes = {
        "Dr.": "Dr.",
        "Zb": "ZB",
        "Vm": "VM",
    }
    parts = t.split(" ")
    parts = [fixes.get(p, p) for p in parts]
    return _normalize_whitespace(" ".join(parts))


def _parse_numbers_tail(text: str) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
    m = TRAILING_NUMBERS_RE.match(text)
    if not m:
        return text, None, None, None
    prefix, qty, price_each, amount = m.groups()
    return prefix, qty, price_each, amount


def _split_pack_size(text: str) -> Tuple[str, Optional[str]]:
    m = PACK_AT_END_RE.match(text)
    if not m:
        return text, None
    desc, pack = m.groups()
    return desc, _normalize_pack_size(pack)


def parse_stark_invoice_lines(lines: List[str]) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    current: Optional[Dict[str, Optional[str]]] = None

    def try_finalize():
        nonlocal current
        if not current:
            return
        if all(current.get(k) for k in ("Item", "Description", "Pack Size", "Quantity", "Price Each", "Amount")):
            # finalize and append, then clear current
            items.append({
                "Item": str(current["Item"]),
                "Description": str(current["Description"]),
                "Pack Size": str(current["Pack Size"]),
                "Quantity": str(current["Quantity"]),
                "Price Each": str(current["Price Each"]),
                "Amount": str(current["Amount"]),
            })
            current = None

    for raw_line in lines:
        line = _normalize_whitespace(raw_line)
        if not line:
            continue

        m = ROW_START_RE.match(line)
        if m:
            # If there is an unfinished current, we cannot finalize safely; drop if incomplete
            try_finalize()
            code1, code2, rest = m.groups()
            current = {
                "Item": f"{code1} {code2}",
                "Description": None,
                "Pack Size": None,
                "Quantity": None,
                "Price Each": None,
                "Amount": None,
                "_accum": rest,
            }
            # Parse immediately from the remainder on the same line
            prefix, qty, price_each, amount = _parse_numbers_tail(current["_accum"])  # type: ignore[arg-type]
            if qty and price_each and amount:
                current["Quantity"], current["Price Each"], current["Amount"] = qty, price_each, amount
                current["_accum"] = prefix
            # Try pack size
            desc_part, pack = _split_pack_size(current["_accum"])  # type: ignore[arg-type]
            if pack:
                current["Pack Size"] = pack
                current["_accum"] = desc_part
            # Set description if we have accumulated text
            if current["_accum"]:
                current["Description"] = _title_case_description(str(current["_accum"]))
                current["_accum"] = ""
            try_finalize()
            continue

        # Not a row start; must be a continuation (description wrap or trailing numbers)
        if not current:
            continue  # ignore stray lines

        # If this is a pure numbers line for the current row, capture them
        prefix, qty, price_each, amount = _parse_numbers_tail(line)
        if qty and price_each and amount and not current.get("Quantity"):
            current["Quantity"], current["Price Each"], current["Amount"] = qty, price_each, amount
            try_finalize()
            continue

        # Else, treat as additional description content; append and try to extract pack size
        accum = (str(current.get("Description")) if current.get("Description") else "")
        joiner = " " if accum else ""
        accum = f"{accum}{joiner}{line}".strip()

        # Try to peel off pack size from the end
        desc_part, pack = _split_pack_size(accum)
        if pack and not current.get("Pack Size"):
            current["Pack Size"] = pack
            accum = desc_part

        if accum:
            current["Description"] = _title_case_description(accum)
        try_finalize()

    # In case the last row was complete at end
    try_finalize()

    return items
