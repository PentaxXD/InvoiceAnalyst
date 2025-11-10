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
        if parsed:
            return parsed
    except InvoiceParsingError:
        pass

    columnar = _parse_columnar_invoice(lines)
    if columnar is None:
        if blocks:
            raise InvoiceParsingError("Failed to parse invoice in either row or column layout.")
        raise InvoiceParsingError("No invoice lines detected in provided text.")
    return columnar


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
    cursor = 0
    invoice_lines: List[InvoiceLine] = []
    while cursor < len(lines):
        section = _extract_columnar_section(lines, cursor)
        if section is None:
            cursor += 1
            continue

        (
            next_cursor,
            item_lines,
            description_lines,
            quantity_tokens,
            unit_tokens,
            amount_tokens,
        ) = section

        if not item_lines:
            cursor = next_cursor
            continue

        if not (
            len(quantity_tokens) >= len(item_lines)
            and len(unit_tokens) >= len(item_lines)
            and len(amount_tokens) >= len(item_lines)
        ):
            return None

        descriptions = _segment_descriptions(description_lines, len(item_lines))
        if descriptions is None:
            return None

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

        cursor = next_cursor

    return invoice_lines or None


def _extract_columnar_section(
    lines: Sequence[str], start_idx: int
) -> Optional[
    Tuple[int, List[str], List[str], List[str], List[str], List[str]]
]:
    heading_idx = None
    for idx in range(start_idx, len(lines)):
        raw = lines[idx]
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

    pre_columns = _collect_pre_item_columns(lines, start_idx, heading_idx, len(item_lines))
    if pre_columns is not None:
        description_lines, quantity_tokens, unit_tokens, amount_tokens = pre_columns
        return idx, item_lines, description_lines, quantity_tokens, unit_tokens, amount_tokens

    description_lines: List[str] = []
    while idx < len(lines):
        stripped = lines[idx].strip()
        idx += 1
        if not stripped:
            continue
        lower = stripped.lower()
        if lower.startswith(("total", "page ")):
            break
        if _looks_like_numeric_column_line(stripped):
            idx -= 1
            break
        if lower == "description":
            continue
        description_lines.append(stripped)

    quantity_tokens, idx = _collect_column(lines, idx, len(item_lines), INTEGER_PATTERN)
    unit_tokens, idx = _collect_column(lines, idx, len(item_lines), MONEY_PATTERN)
    amount_tokens, idx = _collect_column(lines, idx, len(item_lines), MONEY_PATTERN)

    return idx, item_lines, description_lines, quantity_tokens, unit_tokens, amount_tokens


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

    if len(entries) < count:
        return None

    while len(entries) > count:
        merge_idx = _pick_description_merge_index(entries)
        if merge_idx is None:
            return None
        entries[merge_idx - 1] = f"{entries[merge_idx - 1]} {entries.pop(merge_idx)}"

    if len(entries) != count:
        return None

    return entries


def _looks_like_numeric_column_line(text: str) -> bool:
    if not text:
        return False

    stripped = text.strip()
    if not stripped:
        return False

    if any(char.isalpha() for char in stripped):
        return False

    return bool(re.fullmatch(r"[\d\s,.\-()]+", stripped))


def _collect_pre_item_columns(
    lines: Sequence[str], start_idx: int, heading_idx: int, item_count: int
) -> Optional[Tuple[List[str], List[str], List[str], List[str]]]:
    desc_heading_idx = None
    quantity_heading_idx = None
    amount_heading_idx = None

    for idx in range(heading_idx - 1, start_idx - 1, -1):
        stripped = lines[idx].strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if desc_heading_idx is None and lower == "description":
            desc_heading_idx = idx
        elif quantity_heading_idx is None and "quantity" in lower and "price" in lower:
            quantity_heading_idx = idx
        elif amount_heading_idx is None and lower == "amount":
            amount_heading_idx = idx

        if desc_heading_idx is not None and quantity_heading_idx is not None and amount_heading_idx is not None:
            break

    if (
        desc_heading_idx is None
        or quantity_heading_idx is None
        or amount_heading_idx is None
        or not (desc_heading_idx < quantity_heading_idx < amount_heading_idx < heading_idx)
    ):
        return None

    description_lines: List[str] = []
    quantity_tokens: List[str] = []
    unit_tokens: List[str] = []
    amount_tokens: List[str] = []

    for idx in range(desc_heading_idx + 1, heading_idx):
        stripped = lines[idx].strip()
        if not stripped:
            continue

        lower = stripped.lower()
        if lower.startswith(("description", "quantity", "amount", "total", "page ")):
            continue
        if lower == "item":
            break

        normalized = _normalize_number(stripped)

        if any(char.isalpha() for char in stripped):
            description_lines.append(stripped)
            continue

        if len(quantity_tokens) < item_count and INTEGER_PATTERN.fullmatch(normalized):
            quantity_tokens.append(stripped)
        elif len(quantity_tokens) < item_count:
            return None
        elif len(unit_tokens) < item_count and MONEY_PATTERN.fullmatch(normalized):
            unit_tokens.append(stripped)
        elif len(unit_tokens) < item_count:
            return None
        elif len(amount_tokens) < item_count and MONEY_PATTERN.fullmatch(normalized):
            amount_tokens.append(stripped)
        elif len(amount_tokens) < item_count:
            return None

        if (
            len(quantity_tokens) == item_count
            and len(unit_tokens) == item_count
            and len(amount_tokens) == item_count
        ):
            break

    if (
        len(quantity_tokens) != item_count
        or len(unit_tokens) != item_count
        or len(amount_tokens) != item_count
        or not description_lines
    ):
        return None

    return description_lines, quantity_tokens, unit_tokens, amount_tokens


def _pick_description_merge_index(entries: Sequence[str]) -> Optional[int]:
    candidate_idx = None
    candidate_score = None

    for idx in range(1, len(entries)):
        entry = entries[idx]
        score = len(entry)
        if candidate_score is None or score < candidate_score:
            candidate_idx = idx
            candidate_score = score

    return candidate_idx


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


__all__ = ["InvoiceLine", "InvoiceParsingError", "parse_invoice_lines"]
