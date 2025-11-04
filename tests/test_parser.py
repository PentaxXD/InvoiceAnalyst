from pathlib import Path
from textwrap import dedent

from stark_invoice_analyst.parser import parse_invoice_lines


SAMPLE_PATH = Path(__file__).parent / "data" / "sample_invoice_extracted.txt"


def test_parse_invoice_lines_counts_all_rows():
    text = SAMPLE_PATH.read_text(encoding="utf-8")
    lines = parse_invoice_lines(text)

    assert len(lines) == 52


def test_parse_invoice_lines_merges_wrapped_descriptions():
    text = SAMPLE_PATH.read_text(encoding="utf-8")
    lines = parse_invoice_lines(text)

    combined = next(line for line in lines if line.item_code == "3HM" and line.sku == "102-280816")

    assert "LEBKUCHEN" in combined.description
    assert combined.description.endswith("21 / 200 G.")


def test_parse_invoice_lines_handles_cross_page_headers_and_units():
    text = dedent(
        """
        Item
        AP 0001
        DR 0002

        Sample Product 10 / 100 G.
        Dessert Sosse 15 /
        CS

        Total

        1
        2

        10.00
        20.00

        10.00
        40.00

        Item Description Quantity Price Each Amount
        RS 217-211

        Ritter Sport Fine Milk Chocolate 35 COCOA 12 / 100 G. Kosher

        Total

        3

        30.00

        90.00
        """
    )

    lines = parse_invoice_lines(text)

    assert len(lines) == 3
    assert lines[1].description.endswith("15 / CS")
    assert lines[2].description.endswith("12 / 100 G. Kosher")


def test_parse_invoice_lines_handles_hyphenated_pack_lines():
    text = dedent(
        """
        Item
        KRGS 0006

        Knorr Gemuese Vegetable Bouillon 16L. / 6 PCS. -
        CONTAINER

        3
        65.12
        195.36
        """
    )

    lines = parse_invoice_lines(text)

    assert len(lines) == 1
    assert lines[0].description.endswith("16L. / 6 PCS. - CONTAINER")
