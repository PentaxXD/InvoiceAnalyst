"""High-level invoice analysis for Stark invoices."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING
import re
from typing import List

from .parser import InvoiceLine, parse_invoice_lines


DEFAULT_STORE_MARKUP = Decimal("1.55")
DEFAULT_STORE_SURCHARGE = Decimal("0.30")
DEFAULT_ONLINE_MARKUP = Decimal("0.50")

UNIT_PATTERN = re.compile(
    r"(\d+)\s*(?:/|x|X)?\s*(?:PCS?|PACKS?|PACK|PKG|PKGS|EA|EACH|COUNT|BTL|BOTTLES?|"
    r"CAN|CANS|JAR|JARS|BAG|BOX|STK|CS|CT|PKS?|L|LTR|ML|CL|G|KG|OZ|LB)\b",
    re.IGNORECASE,
)
PACK_KEYWORDS = {
    "/",
    "X",
    "PCS",
    "PCS.",
    "PACK",
    "PACKS",
    "PKG",
    "PKGS",
    "PK",
    "PKS",
    "EA",
    "EACH",
    "COUNT",
    "BTL",
    "BTLS",
    "BOTTLE",
    "BOTTLES",
    "CAN",
    "CANS",
    "JAR",
    "JARS",
    "BAG",
    "BAGS",
    "BOX",
    "BOXES",
    "STK",
    "CS",
    "CT",
    "L",
    "LTR",
    "ML",
    "CL",
    "G",
    "G.",
    "KG",
    "OZ",
    "LB",
    "KOSHER",
    "CONTAINER",
    "GLASS",
}


@dataclass
class AnalyzedLine:
    """Computed invoice information ready for export."""

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
    """Parse raw text and calculate pricing information."""

    store_multiplier = _as_decimal(store_markup)
    online_surcharge = _as_decimal(online_markup)
    store_surcharge = DEFAULT_STORE_SURCHARGE

    parsed_lines = parse_invoice_lines(text)
    analyzed: List[AnalyzedLine] = []

    for raw in parsed_lines:
        description, pack_size = _split_description(raw.description)
        units = max(_infer_units(pack_size), 1)

        unit_price = _quantize(raw.unit_price)
        amount = _quantize(raw.amount)
        price_each_product = _quantize(raw.unit_price / Decimal(units))
        store_base = price_each_product * store_multiplier + store_surcharge
        store_price = _round_to_nine_cents(store_base)
        online_price = _quantize(store_price + online_surcharge)

        analyzed.append(
            AnalyzedLine(
                item=f"{raw.item_code} {raw.sku}",
                description=_title_case(description),
                pack_size=pack_size,
                quantity=raw.quantity,
                price_each=unit_price,
                amount=amount,
                price_each_product=price_each_product,
                store_price=store_price,
                online_price=online_price,
            )
        )

    return analyzed


def _split_description(description: str) -> tuple[str, str]:
    if not description:
        return "", ""

    tokens = description.strip().split()
    if not tokens:
        return description.strip(), ""

    pack_tokens: List[str] = []
    for token in reversed(tokens):
        if _is_pack_token(token, pack_tokens):
            pack_tokens.append(token)
            continue
        break

    pack_tokens.reverse()
    if not pack_tokens:
        return description.strip(), ""

    desc_length = len(tokens) - len(pack_tokens)
    base_tokens = tokens[:desc_length]

    base = " ".join(base_tokens).strip(" ,-/")
    pack = " ".join(pack_tokens).strip(" ,")
    return base or description.strip(), pack


def _is_pack_token(token: str, current: List[str]) -> bool:
    normalized = token.strip(",.")
    if not normalized:
        return False

    if any(ch.isdigit() for ch in normalized):
        return True

    upper = normalized.upper()
    if upper in PACK_KEYWORDS:
        return True

    if current and upper in {"-", "&"}:
        return True

    return False


def _infer_units(pack: str) -> int:
    if not pack:
        return 1

    slash_match = re.search(r"(\d+)\s*/", pack)
    if slash_match:
        value = int(slash_match.group(1))
        if value > 0:
            return value

    suffix_match = UNIT_PATTERN.search(pack)
    if suffix_match:
        value = int(suffix_match.group(1))
        if value > 0:
            return value

    fallback = re.search(r"\d+", pack)
    if fallback:
        value = int(fallback.group())
        if value > 0:
            return value

    return 1


def _title_case(text: str) -> str:
    if not text:
        return ""
    lowered = text.lower()
    return " ".join(segment.capitalize() for segment in lowered.split())


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _format_money(value: Decimal) -> str:
    return f"{_quantize(value):.2f}"


def _round_to_nine_cents(value: Decimal) -> Decimal:
    if value <= 0:
        return Decimal("0.00")

    tenths = (value * Decimal("10")).to_integral_value(rounding=ROUND_CEILING)
    rounded = Decimal(tenths) / Decimal("10")
    candidate = rounded - Decimal("0.01")
    if candidate < 0:
        candidate = Decimal("0.00")
    return _quantize(candidate)


def _as_decimal(value: Decimal | float) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


__all__ = [
    "AnalyzedLine",
    "DEFAULT_ONLINE_MARKUP",
    "DEFAULT_STORE_MARKUP",
    "DEFAULT_STORE_SURCHARGE",
    "analyze_invoice_text",
    "_infer_units",
]
