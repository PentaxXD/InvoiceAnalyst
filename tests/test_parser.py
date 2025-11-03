from pathlib import Path

from stark_invoice_analyst.parser import parse_invoice_lines


SAMPLE_PATH = Path(__file__).parent / "data" / "sample_invoice.txt"


def load_sample_text() -> str:
    return SAMPLE_PATH.read_text(encoding="utf-8")


def test_parse_invoice_lines_counts_all_rows():
    text = load_sample_text()
    lines = parse_invoice_lines(text)

    assert len(lines) == 39


def test_parse_invoice_lines_handles_wrapped_descriptions():
    text = load_sample_text()
    lines = parse_invoice_lines(text)

    first = lines[0]
    second = lines[1]

    assert first.description.endswith("10 / 200 G")
    assert second.description.endswith("10 / 200 G.")
