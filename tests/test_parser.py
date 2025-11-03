from pathlib import Path

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
