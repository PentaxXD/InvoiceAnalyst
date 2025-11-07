"""Low-level invoice parsing utilities for Stark invoices."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Iterable, Iterator, List, Optional, Tuple


ITEM_START_PATTERN = re.compile(r"^(?P<code>[A-Z]{2,4})\s+(?P<sku>[A-Z0-9][A-Z0-9-]*)\b")
NUMERIC_TAIL_PATTERN = re.compile(
    r"(?P<quantity>\d+)\s+"
    r"(?P<unit_price>\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2})\s+"
    r"(?P<amount>\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2})$"
)
NUMERIC_LINE_PATTERN = re.compile(r"^[\d\s.,-]+$")


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
    """Parse raw Stark invoice text into structured ``InvoiceLine`` objects."""

    lines = [line.strip() for line in text.splitlines()]
    item_blocks = list(_iter_item_blocks(lines))

    parsed: List[InvoiceLine] = [*map(_parse_block, item_blocks)]
    if not parsed:
        raise InvoiceParsingError("No invoice lines detected in provided text.")

    return parsed


def _iter_item_blocks(lines: Iterable[str]) -> Iterator[List[str]]:
    buffered: List[str] = []
    iterator = iter(lines)

    for line in iterator:
        if not line:
            continue

        if not buffered:
            if ITEM_START_PATTERN.match(line):
                buffered.append(line)
            continue

        if ITEM_START_PATTERN.match(line):
            if not _block_has_numeric_tail(buffered):
                raise InvoiceParsingError(
                    f"Missing quantity/price/amount for line starting with {buffered[0]!r}"
                )
            yield buffered
            buffered = [line]
            continue

        buffered.append(line)

        if _block_has_numeric_tail(buffered):
            yield buffered
            buffered = []

    if buffered:
        if not _block_has_numeric_tail(buffered):
            raise InvoiceParsingError(
                f"Missing quantity/price/amount for line starting with {buffered[0]!r}"
            )
        yield buffered


def _block_has_numeric_tail(block: List[str]) -> bool:
    return _collect_numeric_tail(block) is not None


def _parse_block(block: List[str]) -> InvoiceLine:
    first_line = block[0]
    first_match = ITEM_START_PATTERN.match(first_line)
    if not first_match:
        raise InvoiceParsingError(f"Unable to identify item code in {first_line!r}")

    numeric_info = _collect_numeric_tail(block)
    if numeric_info is None:
        raise InvoiceParsingError(f"Unable to locate numeric columns for {first_line!r}")

    quantity, unit_price, amount, start_index, inline_match = numeric_info

    description_parts: List[str] = []

    if start_index == 0:
        end_idx = inline_match.start() if inline_match else len(block[0])
        fragment = first_line[first_match.end():end_idx].strip()
        if fragment:
            description_parts.append(fragment)
    else:
        remainder = first_line[first_match.end():].strip()
        if remainder:
            description_parts.append(remainder)

        for line in block[1:start_index]:
            cleaned = line.strip()
            if cleaned:
                description_parts.append(cleaned)

        if inline_match:
            prefix = block[start_index][: inline_match.start()].strip()
            if prefix:
                description_parts.append(prefix)

    description = " ".join(part.strip() for part in description_parts if part.strip())

    return InvoiceLine(
        item_code=first_match.group("code"),
        sku=first_match.group("sku"),
        description=description,
        quantity=quantity,
        unit_price=unit_price,
        amount=amount,
    )


def _to_decimal(value: str) -> Decimal:
    normalized = value.replace(",", "")
    return Decimal(normalized)


def _collect_numeric_tail(
    block: List[str],
) -> Optional[Tuple[int, Decimal, Decimal, int, Optional[re.Match[str]]]]:
    tokens: List[str] = []
    first_numeric_index: Optional[int] = None

    for index in range(len(block) - 1, -1, -1):
        line = block[index]
        match = NUMERIC_TAIL_PATTERN.search(line)
        if match:
            quantity = int(match.group("quantity").replace(",", ""))
            unit_price = _to_decimal(match.group("unit_price"))
            amount = _to_decimal(match.group("amount"))
            return quantity, unit_price, amount, index, match

        if NUMERIC_LINE_PATTERN.match(line):
            first_numeric_index = index
            parts = line.split()
            tokens = parts + tokens
            if len(tokens) >= 3:
                try:
                    quantity = int(tokens[-3].replace(",", ""))
                    unit_price = _to_decimal(tokens[-2])
                    amount = _to_decimal(tokens[-1])
                except (ValueError, ArithmeticError):
                    continue
                return quantity, unit_price, amount, first_numeric_index, None
            continue

        if tokens:
            break

    return None


__all__ = ["InvoiceLine", "InvoiceParsingError", "parse_invoice_lines"]
