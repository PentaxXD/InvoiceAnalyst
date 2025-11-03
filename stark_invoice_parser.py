"""Parser utilities for Stark invoice line items.

This module focuses on robustly parsing item tables extracted from PDF
invoices where descriptions may wrap across multiple lines while the
quantity, unit price and amount values typically remain on the final line.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Iterable, List


_LINE_START_PATTERN = re.compile(r"^[A-Z]{2,4}\s+(?=\S*[0-9])[0-9A-Z-]{4,}")
_LINE_PARSE_PATTERN = re.compile(
    r"^(?P<item_code>[A-Z]{2,4})\s+"
    r"(?P<sku>\S+)\s+"
    r"(?P<description>.+?)\s+"
    r"(?P<quantity>\d+)\s+"
    r"(?P<unit_price>\d+\.\d{2})\s+"
    r"(?P<amount>\d+\.\d{2})$"
)


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


def _collapse_wrapped_lines(lines: Iterable[str]) -> List[str]:
    """Combine wrapped description lines into single logical entries."""

    combined: List[str] = []
    current_parts: List[str] = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        if not current_parts:
            if not _LINE_START_PATTERN.match(line):
                # Skip table headers or unrelated text before the actual data.
                continue
            current_parts.append(line)
        else:
            current_parts.append(line)

        candidate = " ".join(current_parts)
        if _LINE_PARSE_PATTERN.match(candidate):
            combined.append(candidate)
            current_parts = []

    if current_parts:
        raise InvoiceParsingError(
            "Incomplete invoice line detected at end of input:"
            f" {' '.join(current_parts)!r}"
        )

    return combined


def parse_invoice_lines(text: str) -> List[InvoiceLine]:
    """Parse raw invoice line text into structured ``InvoiceLine`` objects.

    Args:
        text: Raw text extracted from the invoice table (may include wraps).

    Returns:
        A list of ``InvoiceLine`` instances in the order they were provided.

    Raises:
        InvoiceParsingError: If any entry fails structured parsing.
    """

    logical_lines = _collapse_wrapped_lines(text.splitlines())
    parsed: List[InvoiceLine] = []

    for entry in logical_lines:
        match = _LINE_PARSE_PATTERN.match(entry)
        if not match:
            raise InvoiceParsingError(
                "Unable to parse invoice line after wrapping resolution:"
                f" {entry!r}"
            )

        try:
            quantity = int(match.group("quantity"))
            unit_price = Decimal(match.group("unit_price"))
            amount = Decimal(match.group("amount"))
        except (ValueError, InvalidOperation) as exc:
            raise InvoiceParsingError(
                "Failed to convert numeric fields for entry:"
                f" {entry!r}"
            ) from exc

        parsed.append(
            InvoiceLine(
                item_code=match.group("item_code"),
                sku=match.group("sku"),
                description=match.group("description"),
                quantity=quantity,
                unit_price=unit_price,
                amount=amount,
            )
        )

    return parsed


def format_invoice_lines(lines: Iterable[InvoiceLine]) -> str:
    """Pretty-print parsed invoice lines for quick verification."""

    header = "CODE | SKU           | QTY | UNIT  | AMOUNT | DESCRIPTION"
    rows = [header, "-" * len(header)]

    for line in lines:
        rows.append(
            f"{line.item_code:<4}| {line.sku:<14}| {line.quantity:>3} | "
            f"{line.unit_price:>6} | {line.amount:>7} | {line.description}"
        )

    return "\n".join(rows)


__all__ = ["InvoiceLine", "InvoiceParsingError", "parse_invoice_lines", "format_invoice_lines"]
