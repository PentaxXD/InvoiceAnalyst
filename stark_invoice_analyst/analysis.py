"""High-level analysis utilities for Stark invoices."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import re
from typing import Iterable, List, Sequence

from .parser import InvoiceLine, parse_invoice_lines


DEFAULT_STORE_MARKUP = Decimal("1.68")
DEFAULT_ONLINE_MARKUP = Decimal("1.86")

_PACK_LEFT_JOINERS = {
    "/",
    "x",
    "X",
    "PCS",
    "PCS.",
    "PACK",
    "PACKS",
    "STK",
    "STK.",
    "CS",
    "G",
    "G.",
    "KG",
    "OZ",
    "OZ.",
    "LB",
    "L",
    "L.",
    "ML",
    "CL",
    "GLASS",
    "CONTAINER",
    "KOSHER",
}


@dataclass
class AnalyzedLine:
    """Represents an analyzed invoice line ready for export."""

    item: str
    description: str
    pack_size: str
    quantity: int
    price_each: Decimal
    amount: Decimal
    price_each_product: Decimal
    store_price: Decimal
    online_price: Decimal

    def to_csv_row(self) -> dict[str, str]:
        """Return a CSV-friendly mapping of the line contents."""

        return {
            "Item": self.item,
            "Description": self.description,
            "Pack Size": self.pack_size,
            "Quantity": str(self.quantity),
            "Price Each": _format_money(self.price_each),
            "Amount": _format_money(self.amount),
            "Price Each Product": _format_money(self.price_each_product),
            "Store Price": _format_money(self.store_price),
            "Online Price": _format_money(self.online_price),
        }


def analyze_invoice_text(
    text: str,
    *,
    store_markup: Decimal | float = DEFAULT_STORE_MARKUP,
    online_markup: Decimal | float = DEFAULT_ONLINE_MARKUP,
) -> List[AnalyzedLine]:
    """Parse raw invoice text and compute the derived pricing fields."""

    store_markup = _coerce_decimal(store_markup)
    online_markup = _coerce_decimal(online_markup)

    lines = parse_invoice_lines(text)
    analyzed: List[AnalyzedLine] = []

    for raw_line in lines:
        description, pack_size, pack_tokens = _split_description(raw_line.description)
        units_per_case = _infer_units_per_case(pack_tokens) or 1
        price_each_product = _quantize(raw_line.unit_price / Decimal(units_per_case))
        store_price = _quantize(price_each_product * store_markup)
        online_price = _quantize(price_each_product * online_markup)

        analyzed.append(
            AnalyzedLine(
                item=f"{raw_line.item_code} {raw_line.sku}",
                description=_normalize_description(description),
                pack_size=pack_size,
                quantity=raw_line.quantity,
                price_each=_quantize(raw_line.unit_price),
                amount=_quantize(raw_line.amount),
                price_each_product=price_each_product,
                store_price=store_price,
                online_price=online_price,
            )
        )

    return analyzed


def _split_description(description: str) -> tuple[str, str, Sequence[str]]:
    """Split a raw description into the readable portion and pack size."""

    tokens = description.split()
    if not tokens:
        return description, "", []

    last_digit_index = _find_last_digit_index(tokens)
    if last_digit_index is None:
        cleaned = description.strip().rstrip("/")
        return cleaned, "", []

    start_index = last_digit_index
    while start_index > 0:
        candidate = tokens[start_index - 1]
        if _token_allows_pack(candidate):
            start_index -= 1
        else:
            break

    pack_tokens = tokens[start_index:]
    desc_tokens = tokens[:start_index]

    pack_size = " ".join(pack_tokens).strip(" ,")
    clean_description = " ".join(desc_tokens).strip(" ,/")

    return clean_description or description.strip(), pack_size, pack_tokens


def _find_last_digit_index(tokens: Sequence[str]) -> int | None:
    for index in range(len(tokens) - 1, -1, -1):
        if any(ch.isdigit() for ch in tokens[index]):
            return index
    return None


def _token_allows_pack(token: str) -> bool:
    stripped = token.strip(",.")
    if not stripped:
        return False
    if any(ch.isdigit() for ch in stripped):
        return True
    return stripped.upper() in _PACK_LEFT_JOINERS


_LEADING_UNIT_PATTERN = re.compile(r"(\d+)\s*/")
_UNIT_SUFFIX_PATTERN = re.compile(
    r"(\d+)\s*(?:PCS?|PACKS?|PACK|PKG|PKGS|STK|BAG|BOX|CT|EA|EACH|COUNT|BTL|BOTTLES?|CAN|CANS|JAR|JARS|LTR|L|ML|CL|G|KG|OZ|LB)\b",
    re.IGNORECASE,
)
_UNIT_FALLBACK_PATTERN = re.compile(r"\d+")


def _infer_units_per_case(pack_tokens: Sequence[str]) -> int | None:
    text = " ".join(pack_tokens)

    slash_match = _LEADING_UNIT_PATTERN.search(text)
    if slash_match:
        return int(slash_match.group(1))

    suffix_match = _UNIT_SUFFIX_PATTERN.search(text)
    if suffix_match:
        return int(suffix_match.group(1))

    for token in pack_tokens:
        for match in _UNIT_FALLBACK_PATTERN.finditer(token):
            value = int(match.group())
            if value > 0:
                return value

    return None


def _normalize_description(description: str) -> str:
    if not description:
        return ""
    lowered = description.lower()
    return " ".join(word.capitalize() for word in lowered.split())


def _format_money(value: Decimal) -> str:
    return f"{_quantize(value):.2f}"


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _coerce_decimal(value: Decimal | float) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


__all__ = [
    "AnalyzedLine",
    "DEFAULT_ONLINE_MARKUP",
    "DEFAULT_STORE_MARKUP",
    "analyze_invoice_text",
]
