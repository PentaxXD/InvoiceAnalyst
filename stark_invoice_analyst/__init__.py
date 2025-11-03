"""Stark Invoice Analyst package.

Provides utilities to parse Stark Group invoice exports and convert them into
structured data sets that can be exported to CSV or consumed programmatically.
"""

from .analysis import (
    AnalyzedLine,
    DEFAULT_ONLINE_MARKUP,
    DEFAULT_STORE_MARKUP,
    analyze_invoice_text,
)
from .parser import InvoiceLine, InvoiceParsingError, parse_invoice_lines

__all__ = [
    "AnalyzedLine",
    "DEFAULT_ONLINE_MARKUP",
    "DEFAULT_STORE_MARKUP",
    "InvoiceLine",
    "InvoiceParsingError",
    "analyze_invoice_text",
    "parse_invoice_lines",
]
