from pathlib import Path
from chicago_imports_parser import _read_input_text, parse_invoice_text

text = _read_input_text(Path('/workspace/Chicago_Imports_SO2290048688.pdf'))
items = parse_invoice_text(text)
for idx, it in enumerate(items[:20], start=1):
    print(idx, it.quantity, it.pack_size, '|', it.item, '|', it.rate, it.amount)
print('TOTAL ITEMS:', len(items))
