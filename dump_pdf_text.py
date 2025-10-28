from pdfminer.high_level import extract_text
from pathlib import Path
import sys
p = Path('/workspace/Chicago_Imports_SO2290048688.pdf')
out = Path('/workspace/pdf_text.txt')
out.write_text(extract_text(str(p)), encoding='utf-8')
print('wrote', out)