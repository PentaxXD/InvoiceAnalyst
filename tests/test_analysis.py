from decimal import Decimal
from pathlib import Path

from stark_invoice_analyst import analyze_invoice_text
from stark_invoice_analyst.analysis import _infer_units_per_case


SAMPLE_PATH = Path(__file__).parent / "data" / "sample_invoice_extracted.txt"


def test_analyze_invoice_text_returns_expected_first_row():
    text = SAMPLE_PATH.read_text(encoding="utf-8")

    results = analyze_invoice_text(text)

    assert len(results) == 52

    first = results[0]
    assert first.item == "3AB 204-984451"
    assert first.pack_size == "12 / 220 G"
    assert first.price_each_product == Decimal("9.89")
    assert first.store_price == Decimal("16.62")
    assert first.online_price == Decimal("18.40")


def test_analyze_invoice_text_properly_handles_split_pack_lines():
    text = SAMPLE_PATH.read_text(encoding="utf-8")

    results = analyze_invoice_text(text)

    target = next(row for row in results if row.item.startswith("3NG 170-06911"))

    assert target.pack_size == "10 / 110 G."
    assert target.price_each == Decimal("48.90")


def test_analyze_invoice_text_prefers_units_before_slash():
    text = SAMPLE_PATH.read_text(encoding="utf-8")

    results = analyze_invoice_text(text)

    cocoa = next(row for row in results if row.item.startswith("3RG 140-52025"))

    assert cocoa.pack_size.startswith("24 /")
    assert cocoa.price_each_product == Decimal("1.99")


def test_infer_units_prefers_number_before_slash():
    tokens = ["35", "COCOA", "12", "/", "100", "G."]

    assert _infer_units_per_case(tokens) == 12
