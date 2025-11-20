from decimal import Decimal
from pathlib import Path

from stark_invoice_analyst import analyze_invoice_text
from stark_invoice_analyst.analysis import _infer_units


SAMPLE_PATH = Path(__file__).parent / "data" / "sample_invoice_extracted.txt"


def test_analyze_invoice_text_returns_expected_first_row():
    text = SAMPLE_PATH.read_text(encoding="utf-8")

    results = analyze_invoice_text(text)

    assert len(results) == 24

    first = results[0]
    assert first.item == "AP 104-06604"
    assert first.pack_size == "10 / 200 G"
    assert first.price_each_product == Decimal("2.79")
    assert first.store_price == Decimal("4.69")
    assert first.online_price == Decimal("5.19")


def test_analyze_invoice_text_properly_handles_split_pack_lines():
    text = SAMPLE_PATH.read_text(encoding="utf-8")

    results = analyze_invoice_text(text)

    target = next(row for row in results if row.item.startswith("DR 6075-07500"))

    assert target.pack_size == "15 / CS"
    assert target.price_each == Decimal("26.71")


def test_analyze_invoice_text_prefers_units_before_slash():
    text = SAMPLE_PATH.read_text(encoding="utf-8")

    results = analyze_invoice_text(text)

    cocoa = next(row for row in results if row.item.startswith("AP 106-06606"))

    assert cocoa.pack_size == "10 / 200 G."
    assert cocoa.price_each_product == Decimal("2.79")


def test_infer_units_prefers_number_before_slash():
    pack = "35 COCOA 12 / 100 G."

    assert _infer_units(pack) == 12


def test_infer_units_handles_unit_only_suffix():
    pack = "15 / CS"

    assert _infer_units(pack) == 15


def test_infer_units_handles_multiplication_pattern():
    pack = "16 x 6 / T4"

    assert _infer_units(pack) == 96


def test_analyze_invoice_text_reorders_weight_first_pack():
    text = "\n".join(
        [
            "Item",
            "3RS 7021 SAMPLE PRODUCT 100 G. / 12 PCS 1 10.00 10.00",
        ]
    )

    results = analyze_invoice_text(text)

    assert len(results) == 1
    assert results[0].pack_size == "12 PCS / 100 G."
