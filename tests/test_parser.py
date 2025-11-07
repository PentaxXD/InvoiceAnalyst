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
