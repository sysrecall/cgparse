"""Generate sample documents for testing the pipeline (CSV already hand-written)."""

import sys
from pathlib import Path

SEED = Path(__file__).resolve().parents[1] / "seed" / "samples"
SEED.mkdir(parents=True, exist_ok=True)


def make_xlsx() -> Path:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Invoice"
    rows = [
        ["Invoice Number", "INV-2026-0002"],
        ["Invoice Date", "2026-10-05"],
        ["Supplier", "Beta Logistics GmbH"],
        ["Customer", "Northwind Traders"],
        ["Subtotal", 2750.00],
        ["Tax", 247.50],
        ["Total", 2997.50],
        ["Currency", "EUR"],
        [],
        ["Item", "Qty", "Unit Price", "Amount"],
        ["Pallet screws", 500, 4.10, 2050.00],
        ["Steel brackets", 200, 3.50, 700.00],
    ]
    for row in rows:
        ws.append(row)
    path = SEED / "invoice_sample.xlsx"
    wb.save(path)
    return path


def make_pdf() -> Path:
    import fitz  # pymupdf

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4
    lines = [
        ("INVOICE", 36, 72, 60),
        ("Invoice Number: INV-2026-0003", 12, 72, 120),
        ("Invoice Date: 2026-10-10", 12, 72, 140),
        ("Supplier: Gamma Manufacturing Inc", 12, 72, 160),
        ("Customer: Northwind Traders", 12, 72, 180),
        ("Currency: USD", 12, 72, 200),
        ("Item                          Qty    Unit Price    Amount", 12, 72, 240),
        ("Copper wire spool             25     80.00         2000.00", 12, 72, 260),
        ("Insulation tape roll          40     12.50         500.00", 12, 72, 280),
        ("Subtotal: 2500.00", 12, 72, 320),
        ("Tax: 225.00", 12, 72, 340),
        ("Total: 2725.00", 14, 72, 370),
    ]
    for text, size, x, y in lines:
        page.insert_text((x, y), text, fontsize=size, fontname="helv")
    path = SEED / "invoice_sample.pdf"
    doc.save(path)
    doc.close()
    return path


def make_png() -> Path:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (800, 500), "white")
    draw = ImageDraw.Draw(img)
    lines = [
        ("INVOICE", 60, 40, 28),
        ("Invoice Number: INV-2026-0004", 40, 90, 20),
        ("Invoice Date: 2026-10-12", 40, 120, 20),
        ("Supplier: Delta Foods LLC", 40, 150, 20),
        ("Customer: Northwind Traders", 40, 180, 20),
        ("Currency: USD", 40, 210, 20),
        ("Olive oil case     12     45.00     540.00", 40, 260, 18),
        ("Subtotal: 540.00", 40, 310, 18),
        ("Tax: 54.00", 40, 340, 18),
        ("Total: 594.00", 40, 380, 20),
    ]
    try:
        from PIL import ImageFont

        font = ImageFont.load_default(24)
    except Exception:  # noqa: BLE001 — bitmap default font varies across Pillow versions
        font = None
    for text, x, y, size in lines:
        draw.text((x, y), text, fill="black", font=font)
    path = SEED / "invoice_scan.png"
    img.save(path)
    return path


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("all", "xlsx"):
        print("xlsx:", make_xlsx())
    if which in ("all", "pdf"):
        print("pdf:", make_pdf())
    if which in ("all", "png"):
        print("png:", make_png())
