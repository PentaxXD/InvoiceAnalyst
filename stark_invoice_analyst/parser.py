"""Low-level invoice parsing utilities for Stark invoices."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Iterable, Iterator, List, Sequence


ITEM_PATTERN = re.compile(r"^[A-Z0-9]{2,4}\s+\S+")
INTEGER_PATTERN = re.compile(r"^\d+$")
DECIMAL_PATTERN = re.compile(r"^\d{1,3}(?:,\d{3})*\.\d{2}$|^\d+\.\d{2}$")
DIGIT_PATTERN = re.compile(r"\d")


def _is_item_line(line: str) -> bool:
    if not ITEM_PATTERN.match(line):
        return False
    prefix = line.split()[0]
    return any(ch.isalpha() for ch in prefix)


def _is_item_header(line: str) -> bool:
    upper = line.strip().upper()
    if not upper:
        return False
    if _is_item_line(line):
        return False
    return upper == "ITEM" or upper.startswith("ITEM ")


def _is_general_header(line: str) -> bool:
    upper = line.strip().upper()
    if not upper:
        return True
    header_prefixes = (
        "DESCRIPTION",
        "QUANTITY",
        "PRICE",
        "AMOUNT",
        "TOTAL",
        "PAGE",
        "SUBTOTAL",
        "DELIVERY",
        "CLAIMS",
        "INVOICE",
        "DATE",
        "BILL TO",
        "SHIP TO",
        "S.O.",
        "P.O.",
        "TERMS",
        "REP",
        "DUE DATE",
        "SHIP DATE",
        "SHIP VIA",
    )
    return upper.startswith(header_prefixes)

PACK_TERMINATOR_TOKENS = {
    " G",
    "G.",
    " KG",
    "KG.",
    " OZ",
    "OZ.",
    " LB",
    "LB.",
    " ML",
    "ML.",
    " L",
    "L.",
    " CL",
    "CL.",
    " PACK",
    "PACK.",
    " PACKS",
    "PCS",
    "PCS.",
    " STK",
    "STK.",
    " CS",
    "CS.",
    " BAG",
    "BAG.",
    " BOX",
    "BOX.",
    " CT",
    "CT.",
    " PK",
    "PK.",
    " PKG",
    "PKG.",
    " PC",
    "PC.",
    " EA",
    "EA.",
    " EACH",
    " CAN",
    "CAN.",
    " CANS",
    " BOTTLE",
    "BOTTLES",
    " JAR",
    "JARS",
    "LTR",
    "LTR.",
    "GAL",
    "GAL.",
    " GALLON",
    "GALLONS",
    "GRAM",
    "GRAMS",
}

PACK_UNIT_KEYWORDS = {token.strip().strip('.') for token in PACK_TERMINATOR_TOKENS if token.strip()}


@dataclass
class InvoiceLine:
    """Represents a single parsed invoice line item."""

    item_code: str
    sku: str
    description: str
    quantity: int
    unit_price: Decimal
    amount: Decimal


class InvoiceParsingError(ValueError):
    """Raised when a block of text cannot be parsed into an invoice line."""


def parse_invoice_lines(text: str) -> List[InvoiceLine]:
    """Parse raw invoice text into structured ``InvoiceLine`` objects."""

    lines = [line.strip() for line in text.splitlines()]
    sections = list(_extract_sections(lines))

    parsed: List[InvoiceLine] = []
    for items, descriptions, quantities, unit_prices, amounts in sections:
        if not quantities or not unit_prices or not amounts:
            # Skip summary/footers without full numeric columns
            continue
        if not (len(items) == len(descriptions) == len(quantities) == len(unit_prices) == len(amounts)):
            raise InvoiceParsingError(
                "Column count mismatch between parsed fields: "
                f"items={len(items)}, descriptions={len(descriptions)}, quantities={len(quantities)}, "
                f"unit_prices={len(unit_prices)}, amounts={len(amounts)}"
            )

        for index, item_text in enumerate(items):
            code, sku = _split_item_code(item_text)
            parsed.append(
                InvoiceLine(
                    item_code=code,
                    sku=sku,
                    description=descriptions[index],
                    quantity=quantities[index],
                    unit_price=unit_prices[index],
                    amount=amounts[index],
                )
            )

    if not parsed:
        raise InvoiceParsingError("No invoice lines detected in provided text.")

    return parsed


def _extract_sections(lines: Sequence[str]) -> Iterator[tuple[List[str], List[str], List[int], List[Decimal], List[Decimal]]]:
    total_lines = len(lines)
    index = 0

    while index < total_lines:
        line = lines[index]
        if not _is_item_header(line):
            index += 1
            continue

        index += 1
        items: List[str] = []
        while index < total_lines:
            current = lines[index]
            if not current:
                index += 1
                continue
            if _is_item_header(current):
                index += 1
                continue
            if _is_item_line(current):
                items.append(current)
                index += 1
                continue
            break

        if not items:
            continue

        descriptions: List[str] = []
        description_lines: List[str] = []
        while index < total_lines:
            current = lines[index]
            if not current:
                index += 1
                continue
            if _is_item_line(current) or INTEGER_PATTERN.match(current) or DECIMAL_PATTERN.match(current):
                break
            if current.upper() == "TOTAL":
                index += 1
                break
            if current.upper().startswith("QUANTITY"):
                index += 1
                continue
            if _is_item_header(current):
                if description_lines:
                    break
                index += 1
                continue
            if _is_general_header(current):
                index += 1
                continue
            description_lines.append(current)
            index += 1

        descriptions = _group_descriptions(description_lines, len(items))

        quantities: List[int] = []
        while index < total_lines and len(quantities) < len(items):
            current = lines[index]
            if not current:
                index += 1
                continue
            if INTEGER_PATTERN.match(current):
                quantities.append(int(current))
                index += 1
                continue
            if _is_general_header(current):
                index += 1
                continue
            break

        unit_prices: List[Decimal] = []
        while index < total_lines and len(unit_prices) < len(items):
            current = lines[index]
            if not current:
                index += 1
                continue
            if DECIMAL_PATTERN.match(current):
                unit_prices.append(_to_decimal(current))
                index += 1
                continue
            if _is_general_header(current):
                index += 1
                continue
            break

        amounts: List[Decimal] = []
        while index < total_lines and len(amounts) < len(items):
            current = lines[index]
            if not current:
                index += 1
                continue
            if DECIMAL_PATTERN.match(current):
                amounts.append(_to_decimal(current))
                index += 1
                continue
            if _is_general_header(current):
                index += 1
                continue
            break

        if items:
            yield items, descriptions, quantities, unit_prices, amounts


def _group_descriptions(lines: Iterable[str], expected: int) -> List[str]:
    grouped: List[str] = []
    current: List[str] = []

    for line in lines:
        current.append(line)
        if _description_terminates(current):
            grouped.append(" ".join(current).strip())
            current = []

    if current:
        grouped.append(" ".join(current).strip())

    if len(grouped) < expected:
        grouped.extend([""] * (expected - len(grouped)))
    elif len(grouped) > expected:
        grouped = grouped[:expected]

    return grouped


def _description_terminates(current: Sequence[str]) -> bool:
    candidate = " ".join(current).strip()
    if not DIGIT_PATTERN.search(candidate):
        return False
    if candidate.endswith('/'):
        return False
    if candidate.endswith('-'):
        return False

    upper = candidate.upper()
    if any(token in upper for token in PACK_TERMINATOR_TOKENS):
        return True

    if '/' in candidate:
        pre, post = candidate.rsplit('/', 1)
        post = post.strip()
        if any(ch.isdigit() for ch in post):
            return True
        if post:
            unit_token = post.split()[0].strip('.,')
            if unit_token.upper() in PACK_UNIT_KEYWORDS:
                return True
        if DIGIT_PATTERN.search(pre):
            return True

    return False


def _split_item_code(text: str) -> tuple[str, str]:
    parts = text.split(maxsplit=1)
    if len(parts) != 2:
        raise InvoiceParsingError(f"Unable to split item code and SKU from {text!r}")
    return parts[0], parts[1]


def _to_decimal(value: str) -> Decimal:
    normalized = value.replace(",", "")
    return Decimal(normalized)


__all__ = ["InvoiceLine", "InvoiceParsingError", "parse_invoice_lines"]
