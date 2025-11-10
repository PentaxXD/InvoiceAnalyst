"""Parsing utilities for Stark invoice text."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Iterable, Iterator, List, Optional, Sequence, Tuple


ITEM_PATTERN = re.compile(r"^(?P<code>[A-Z]{2,4})\s+(?P<sku>[A-Z0-9][A-Z0-9-]*)\b")
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9,&./-]+")
MONEY_PATTERN = re.compile(r"^\d{1,3}(?:,\d{3})*\.\d{2}$")
INTEGER_PATTERN = re.compile(r"^\d{1,3}(?:,\d{3})*$")


@dataclass
class InvoiceLine:
    """Structured representation of a single invoice row."""

    item_code: str
    sku: str
    description: str
    quantity: int
    unit_price: Decimal
    amount: Decimal


class InvoiceParsingError(ValueError):
    """Raised when raw text cannot be converted into invoice lines."""


def parse_invoice_lines(text: str) -> List[InvoiceLine]:
    """Parse Stark invoice text into :class:`InvoiceLine` objects."""

    lines = [line.rstrip() for line in text.splitlines()]
    blocks = list(_gather_item_blocks(lines))

    try:
        parsed = [_finalize_block(block) for block in blocks]
    except InvoiceParsingError:
        columnar = _parse_columnar_invoice(lines)
        if columnar is None:
            raise
        return columnar

    if not parsed:
        columnar = _parse_columnar_invoice(lines)
        if columnar is None:
            raise InvoiceParsingError("No invoice lines detected in provided text.")
        return columnar

    return parsed


def _gather_item_blocks(lines: Iterable[str]) -> Iterator[Sequence[str]]:
    current: List[str] = []

    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            continue

        if ITEM_PATTERN.match(stripped):
            if current:
                yield tuple(current)
            current = [stripped]
            continue

        if current:
            current.append(stripped)

    if current:
        yield tuple(current)


def _finalize_block(block: Sequence[str]) -> InvoiceLine:
    head = block[0]
    match = ITEM_PATTERN.match(head)
    if not match:
        raise InvoiceParsingError(f"Unable to locate item code in {head!r}")

    trailing_tokens = _collect_tokens(match, block)
    quantity, unit_price, amount, desc_tokens = _split_numeric_tail(trailing_tokens)

    description = _normalize_whitespace(" ".join(desc_tokens))

    return InvoiceLine(
        item_code=match.group("code"),
        sku=match.group("sku"),
        description=description,
        quantity=quantity,
        unit_price=unit_price,
        amount=amount,
    )


def _collect_tokens(match: re.Match[str], block: Sequence[str]) -> List[str]:
    tokens: List[str] = []

    head_remainder = block[0][match.end():].strip()
    if head_remainder:
        tokens.extend(TOKEN_PATTERN.findall(head_remainder))

    for line in block[1:]:
        tokens.extend(TOKEN_PATTERN.findall(line))

    return tokens


def _split_numeric_tail(tokens: Sequence[str]) -> Tuple[int, Decimal, Decimal, List[str]]:
    if len(tokens) < 3:
        raise InvoiceParsingError("Incomplete item line; expected quantity, price, and amount.")

    decimal_indices = [idx for idx, token in enumerate(tokens) if MONEY_PATTERN.fullmatch(_normalize_number(token))]
    if len(decimal_indices) < 2:
        raise InvoiceParsingError("Could not find both unit price and amount in item line.")

    amount_idx = decimal_indices[-1]
    unit_idx = decimal_indices[-2]

    quantity_idx = None
    for idx in range(unit_idx - 1, -1, -1):
        candidate = tokens[idx]
        if INTEGER_PATTERN.fullmatch(_normalize_number(candidate)):
            quantity_idx = idx
            break

    if quantity_idx is None:
        raise InvoiceParsingError("Quantity column missing for invoice item.")

    quantity = int(_normalize_number(tokens[quantity_idx]))
    unit_price = Decimal(_normalize_number(tokens[unit_idx]))
    amount = Decimal(_normalize_number(tokens[amount_idx]))

    description_tokens = list(tokens[:quantity_idx])
    return quantity, unit_price, amount, description_tokens


def _normalize_number(token: str) -> str:
    cleaned = re.sub(r"[^\d.,-]", "", token)
    return cleaned.replace(",", "")


def _parse_columnar_invoice(lines: Sequence[str]) -> Optional[List[InvoiceLine]]:
    sections = _extract_columnar_sections(lines)
    if sections is None:
        return None

    item_lines, description_lines, quantity_tokens, unit_tokens, amount_tokens = sections

    if not item_lines:
        return None

    if not (
        len(quantity_tokens) >= len(item_lines)
        and len(unit_tokens) >= len(item_lines)
        and len(amount_tokens) >= len(item_lines)
    ):
        return None

    descriptions = _segment_descriptions(description_lines, len(item_lines))
    if descriptions is None:
        return None

    invoice_lines: List[InvoiceLine] = []
    for idx, item_line in enumerate(item_lines):
        match = ITEM_PATTERN.match(item_line)
        if not match:
            return None

        try:
            quantity = int(_normalize_number(quantity_tokens[idx]))
            unit_price = Decimal(_normalize_number(unit_tokens[idx]))
            amount = Decimal(_normalize_number(amount_tokens[idx]))
        except (IndexError, ValueError, ArithmeticError):
            return None

        invoice_lines.append(
            InvoiceLine(
                item_code=match.group("code"),
                sku=match.group("sku"),
                description=_normalize_whitespace(descriptions[idx]),
                quantity=quantity,
                unit_price=unit_price,
                amount=amount,
            )
        )

    return invoice_lines


def _extract_columnar_sections(
    lines: Sequence[str],
) -> Optional[Tuple[List[str], List[str], List[str], List[str], List[str]]]:
    heading_idx = None
    for idx, raw in enumerate(lines):
        if raw.strip().lower() == "item":
            heading_idx = idx
            break

    if heading_idx is None:
        return None

    idx = heading_idx + 1
    item_lines: List[str] = []

    while idx < len(lines):
        stripped = lines[idx].strip()
        idx += 1
        if not stripped:
            continue
        match = ITEM_PATTERN.match(stripped)
        if match:
            item_lines.append(stripped)
        else:
            idx -= 1
            break

    if not item_lines:
        return None

    description_lines: List[str] = []
    while idx < len(lines):
        stripped = lines[idx].strip()
        idx += 1
        if not stripped:
            continue
        lower = stripped.lower()
        normalized = _normalize_number(stripped)
        if lower.startswith("total"):
            break
        if INTEGER_PATTERN.fullmatch(normalized) or MONEY_PATTERN.fullmatch(normalized):
            idx -= 1
            break
        if lower == "description":
            continue
        description_lines.append(stripped)

    quantity_tokens, idx = _collect_column(lines, idx, len(item_lines), INTEGER_PATTERN)
    unit_tokens, idx = _collect_column(lines, idx, len(item_lines), MONEY_PATTERN)
    amount_tokens, idx = _collect_column(lines, idx, len(item_lines), MONEY_PATTERN)

    return item_lines, description_lines, quantity_tokens, unit_tokens, amount_tokens


def _collect_column(
    lines: Sequence[str], start_idx: int, count: int, pattern: re.Pattern[str]
) -> Tuple[List[str], int]:
    values: List[str] = []
    idx = start_idx

    while idx < len(lines) and len(values) < count:
        stripped = lines[idx].strip()
        idx += 1
        if not stripped:
            continue

        normalized = _normalize_number(stripped)
        if pattern.fullmatch(normalized):
            values.append(stripped)

    return values, idx


def _segment_descriptions(lines: Sequence[str], count: int) -> Optional[List[str]]:
    if not lines:
        return None

    entries: List[str] = []
    current_parts: List[str] = []

    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            continue

        current_parts.append(stripped)
        if stripped.endswith(("/", "-")):
            continue

        entries.append(" ".join(current_parts))
        current_parts = []

    if current_parts:
        entries.append(" ".join(current_parts))

    if len(entries) != count:
        return None

    return entries


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


__all__ = ["InvoiceLine", "InvoiceParsingError", "parse_invoice_lines"]
