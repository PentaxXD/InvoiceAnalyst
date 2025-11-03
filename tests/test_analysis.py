from decimal import Decimal
from pathlib import Path

from stark_invoice_analyst import analyze_invoice_text


SAMPLE_PATH = Path(__file__).parent / "data" / "sample_invoice.txt"


def test_analyze_invoice_text_returns_expected_first_row():
    text = SAMPLE_PATH.read_text(encoding="utf-8")

    results = analyze_invoice_text(text)

    assert len(results) == 39

    first = results[0]
    assert first.item == "AP 104-06604"
    assert first.pack_size == "10 / 200 G"
    assert first.price_each_product == Decimal("2.79")
    assert first.store_price == Decimal("4.69")
    assert first.online_price == Decimal("5.19")


def test_analyze_invoice_text_tracks_wrapped_descriptions():
    text = SAMPLE_PATH.read_text(encoding="utf-8")

    results = analyze_invoice_text(text)

    knorr = next(row for row in results if row.item.startswith("KRS 1944-23644"))

    assert knorr.pack_size == "15 / 5 PACK"
    assert knorr.price_each_product == Decimal("2.90")
