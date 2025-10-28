import csv, sys
from decimal import Decimal
from pathlib import Path
p = Path(sys.argv[1])
rows = list(csv.DictReader(p.open()))
count = len(rows)
sum_amount = sum(Decimal(r['Amount']) for r in rows)
print(f"items={count}")
print(f"total_amount={sum_amount:.2f}")
# Print a small preview
print("\npreview:")
print(",".join(rows[0].keys()))
for r in rows[:15]:
    print(",".join([r['Quantity'], r['Pack Size'], r['Item'], r['Rate'], r['Amount']]))
