from pathlib import Path
from chicago_imports_parser import parse_invoice_text

pdf_path = Path('/workspace/ChicagoImports_Invoice_274179.pdf')
items = parse_invoice_text('', source_path=pdf_path)
for idx, item in enumerate(items[:20], start=1):
    print(
        idx,
        item.order_qty,
        item.shipped_qty,
        item.item_code,
        '|',
        item.description,
        '|',
        item.case_price,
        item.unit_price,
        item.extended_price,
    )
print('TOTAL ITEMS:', len(items))
