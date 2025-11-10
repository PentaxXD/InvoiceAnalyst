from decimal import Decimal
from pathlib import Path

from stark_invoice_analyst.parser import parse_invoice_lines


SAMPLE_PATH = Path(__file__).parent / "data" / "sample_invoice_extracted.txt"


def test_parse_invoice_lines_counts_all_rows():
    text = SAMPLE_PATH.read_text(encoding="utf-8")
    lines = parse_invoice_lines(text)

    assert len(lines) == 24


def test_parse_invoice_lines_merges_wrapped_descriptions():
    text = SAMPLE_PATH.read_text(encoding="utf-8")
    lines = parse_invoice_lines(text)

    target = next(line for line in lines if line.item_code == "AP" and line.sku == "106-06606")

    assert target.description == "APPEL HERINGFILETS IN SAHNE-MEERRETTICH-CREME 10 / 200 G."


def test_parse_invoice_lines_handles_line_breaks_inside_description():
    text = SAMPLE_PATH.read_text(encoding="utf-8")
    lines = parse_invoice_lines(text)

    target = next(line for line in lines if line.item_code == "DR" and line.sku == "6075-07500")

    assert target.description.endswith("15 / CS")


def test_parse_invoice_lines_retains_hyphenated_pack_information():
    text = SAMPLE_PATH.read_text(encoding="utf-8")
    lines = parse_invoice_lines(text)

    target = next(line for line in lines if line.item_code == "KRGS" and line.sku == "0006-65555")

    assert target.description.endswith("16L. / 6 PCS. - CONTAINER")


def test_parse_invoice_lines_handles_split_numeric_columns():
    text = "\n".join(
        [
            "Item",
            "AP 0001 SAMPLE PRODUCT 10 / 100 G.",
            "3",
            "27.90",
            "83.70",
        ]
    )

    lines = parse_invoice_lines(text)

    assert len(lines) == 1
    assert lines[0].quantity == 3
    assert lines[0].unit_price == Decimal("27.90")
    assert lines[0].amount == Decimal("83.70")


def test_parse_invoice_lines_handles_columnar_pdf_layout():
    text = "\n".join(
        [
            "Header",
            "Item",
            "",
            "AA 0001-XYZ",
            "AB 0002-XYZ",
            "",
            "Product Alpha 10 / 100 G.",
            "Product Beta 5 /",
            "250 G.",
            "",
            "Total",
            "",
            "1",
            "2",
            "",
            "12.34",
            "56.78",
            "",
            "12.34",
            "113.56",
        ]
    )

    lines = parse_invoice_lines(text)

    assert len(lines) == 2

    first, second = lines
    assert first.item_code == "AA"
    assert first.sku == "0001-XYZ"
    assert first.description == "Product Alpha 10 / 100 G."
    assert first.quantity == 1
    assert first.unit_price == Decimal("12.34")
    assert first.amount == Decimal("12.34")

    assert second.item_code == "AB"
    assert second.sku == "0002-XYZ"
    assert second.description == "Product Beta 5 / 250 G."
    assert second.quantity == 2
    assert second.unit_price == Decimal("56.78")
    assert second.amount == Decimal("113.56")
