from stark_invoice_analyst.cli import _read_invoice

def main():
    text = _read_invoice("Inv_250611_from_Stark_Group_International_Inc_7696.pdf", "pdf")
    lines = [line.rstrip() for line in text.splitlines()]
    for idx, raw in enumerate(lines[200:360], start=201):
        print(f"{idx:03}: {raw!r}")

if __name__ == "__main__":
    main()
