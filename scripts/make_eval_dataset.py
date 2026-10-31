"""Generate the labeled evaluation corpus under ``seed/eval/``.

Synthetic, deterministic invoices across every supported input type plus the
edge cases the pipeline must survive:

    clean · comma money · missing tax · US date · long date · missing currency
    missing customer · no line items · arithmetic mismatch · line-item mismatch
    duplicate pair · multi-page · unsupported/empty failure

Writes ``seed/eval/documents/*`` and ``seed/eval/ground_truth.json`` (+ a
human-readable ``ground_truth.csv``). Run through the processing environment,
which carries pdfplumber/pymupdf/Pillow/openpyxl:

    uv run --project services/processing python scripts/make_eval_dataset.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "seed" / "eval"
DOCS = OUT / "documents"

KIND_META = {
    "csv": ("text/csv", "csv", ".csv"),
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "spreadsheet",
        ".xlsx",
    ),
    "pdf": ("application/pdf", "pdf", ".pdf"),
    "png": ("image/png", "image", ".png"),
}

HEADER_FIELDS = (
    "invoice_number",
    "invoice_date",
    "supplier_name",
    "customer_name",
    "subtotal",
    "tax",
    "total",
    "currency",
)


class Spec:
    def __init__(
        self,
        slug: str,
        kind: str,
        *,
        number: str | None,
        date: str | None,
        supplier: str | None,
        customer: str | None,
        currency: str | None,
        items: list[tuple[str, float, float, float]],
        subtotal: float | None,
        tax: float | None,
        total: float | None,
        edge: str = "clean",
        expected_status: str = "validated",
        expected_rules: tuple[str, ...] = (),
        comma_money: bool = False,
        notes: bool = False,
        pages: int = 1,
    ) -> None:
        self.slug = slug
        self.kind = kind
        self.number = number
        self.date = date
        self.supplier = supplier
        self.customer = customer
        self.currency = currency
        self.items = items
        self.subtotal = subtotal
        self.tax = tax
        self.total = total
        self.edge = edge
        self.expected_status = expected_status
        self.expected_rules = list(expected_rules)
        self.comma_money = comma_money
        self.notes = notes
        self.pages = pages

    @property
    def filename(self) -> str:
        return f"eval_{self.slug}{KIND_META[self.kind][2]}"


def _money(value: float | None, comma: bool = False) -> str:
    if value is None:
        return ""
    return f"{value:,.2f}" if comma else f"{value:.2f}"


# ── the corpus ───────────────────────────────────────────────────────────────

SPECS: list[Spec] = [
    # CSV -------------------------------------------------------------------
    Spec(
        "clean_csv_01",
        "csv",
        number="INV-2026-1001",
        date="2026-10-01",
        supplier="Acme Supplies Ltd",
        customer="Northwind Traders",
        currency="USD",
        items=[("Widget", 2, 50.00, 100.00), ("Bolt", 4, 25.00, 100.00)],
        subtotal=200.00,
        tax=20.00,
        total=220.00,
    ),
    Spec(
        "clean_csv_02",
        "csv",
        number="INV-2026-1002",
        date="2026-10-02",
        supplier="Beta Logistics GmbH",
        customer="Contoso GmbH",
        currency="EUR",
        items=[("Pallet screws", 500, 4.10, 2050.00)],
        subtotal=2050.00,
        tax=205.00,
        total=2255.00,
    ),
    Spec(
        "clean_csv_03",
        "csv",
        number="INV-2026-1003",
        date="2026-10-03",
        supplier="Gamma Manufacturing",
        customer="Fabrikam Inc",
        currency="GBP",
        items=[
            ("Steel brackets", 200, 3.50, 700.00),
            ("Rivets", 1000, 0.12, 120.00),
            ("Washers", 500, 0.08, 40.00),
        ],
        subtotal=860.00,
        tax=86.00,
        total=946.00,
    ),
    Spec(
        "comma_money_csv_04",
        "csv",
        number="INV-2026-1004",
        date="2026-10-04",
        supplier="Copper Works Inc",
        customer="Northwind Traders",
        currency="USD",
        items=[("Copper wire spool", 25, 80.00, 2000.00), ("Insulation tape roll", 50, 50.00, 2500.00)],
        subtotal=4500.00,
        tax=450.00,
        total=4950.00,
        edge="comma_money",
        comma_money=True,
    ),
    Spec(
        "missing_tax_csv_05",
        "csv",
        number="INV-2026-1005",
        date="2026-10-05",
        supplier="Delta Foods LLC",
        customer="Adventure Works",
        currency="USD",
        items=[("Olive oil case", 12, 45.00, 540.00)],
        subtotal=540.00,
        tax=0.00,
        total=540.00,
        edge="missing_tax",
    ),
    Spec(
        "us_date_csv_06",
        "csv",
        number="INV-2026-1006",
        date="10/06/2026",
        supplier="Epsilon Trading Co",
        customer="Northwind Traders",
        currency="USD",
        items=[("Laptop stand", 10, 35.00, 350.00)],
        subtotal=350.00,
        tax=35.00,
        total=385.00,
        edge="us_date",
        expected_status="needs_review",
        expected_rules=("type_and_format",),
    ),
    Spec(
        "missing_currency_csv_07",
        "csv",
        number="INV-2026-1007",
        date="2026-10-07",
        supplier="Zeta Components",
        customer="Northwind Traders",
        currency=None,
        items=[("Gearbox", 3, 220.00, 660.00)],
        subtotal=660.00,
        tax=66.00,
        total=726.00,
        edge="missing_currency",
        expected_status="needs_review",
        expected_rules=("missing_field",),
    ),
    Spec(
        "no_line_items_csv_08",
        "csv",
        number="INV-2026-1008",
        date="2026-10-08",
        supplier="Eta Services",
        customer="Fabrikam Inc",
        currency="USD",
        items=[],
        subtotal=500.00,
        tax=50.00,
        total=550.00,
        edge="no_line_items",
    ),
    # XLSX ------------------------------------------------------------------
    Spec(
        "clean_xlsx_01",
        "xlsx",
        number="INV-2026-2001",
        date="2026-10-09",
        supplier="Theta Materials",
        customer="Contoso GmbH",
        currency="GBP",
        items=[("Aluminium sheet", 20, 30.00, 600.00), ("Copper rod", 15, 40.00, 600.00), ("Brass fitting", 5, 20.00, 100.00)],
        subtotal=1300.00,
        tax=130.00,
        total=1430.00,
    ),
    Spec(
        "clean_xlsx_02",
        "xlsx",
        number="INV-2026-2002",
        date="2026-10-10",
        supplier="Iota Hardware",
        customer="Northwind Traders",
        currency="USD",
        items=[("Hammer", 30, 12.00, 360.00), ("Screwdriver set", 20, 18.50, 370.00)],
        subtotal=730.00,
        tax=73.00,
        total=803.00,
    ),
    Spec(
        "multiline_xlsx_03",
        "xlsx",
        number="INV-2026-2003",
        date="2026-10-11",
        supplier="Kappa Supplies",
        customer="Adventure Works",
        currency="USD",
        items=[("Cable reel", 8, 95.00, 760.00), ("Connector", 40, 5.00, 200.00)],
        subtotal=960.00,
        tax=96.00,
        total=1056.00,
        notes=True,
    ),
    Spec(
        "line_sum_xlsx_04",
        "xlsx",
        number="INV-2026-2004",
        date="2026-10-12",
        supplier="Lambda Parts",
        customer="Fabrikam Inc",
        currency="USD",
        items=[("Part A", 1, 60.00, 60.00), ("Part B", 1, 30.00, 30.00)],
        subtotal=100.00,
        tax=10.00,
        total=110.00,
        edge="line_items_sum",
        expected_status="needs_review",
        expected_rules=("line_items_sum",),
    ),
    Spec(
        "duplicate_a_xlsx_05",
        "xlsx",
        number="INV-DUP-9001",
        date="2026-10-13",
        supplier="Duplicate Co",
        customer="Northwind Traders",
        currency="USD",
        items=[("Repeated item", 1, 300.00, 300.00)],
        subtotal=300.00,
        tax=30.00,
        total=330.00,
        edge="duplicate_pair_first",
        expected_rules=("duplicate_invoice",),
    ),
    Spec(
        "long_date_xlsx_06",
        "xlsx",
        number="INV-2026-2006",
        date="October 5, 2026",
        supplier="Mu Trading",
        customer="Contoso GmbH",
        currency="EUR",
        items=[("Sensor", 4, 75.00, 300.00)],
        subtotal=300.00,
        tax=30.00,
        total=330.00,
        edge="long_date",
    ),
    Spec(
        "clean_xlsx_07",
        "xlsx",
        number="INV-2026-2007",
        date="2026-10-14",
        supplier="Nu Components",
        customer="Adventure Works",
        currency="CHF",
        items=[("Bearing", 12, 22.00, 264.00), ("Seal ring", 24, 3.50, 84.00)],
        subtotal=348.00,
        tax=34.80,
        total=382.80,
    ),
    # PDF digital -----------------------------------------------------------
    Spec(
        "clean_pdf_01",
        "pdf",
        number="INV-2026-3001",
        date="2026-10-15",
        supplier="Xi Industries",
        customer="Northwind Traders",
        currency="USD",
        items=[("Copper wire spool", 25, 80.00, 2000.00), ("Insulation tape roll", 40, 12.50, 500.00)],
        subtotal=2500.00,
        tax=225.00,
        total=2725.00,
    ),
    Spec(
        "clean_pdf_02",
        "pdf",
        number="INV-2026-3002",
        date="2026-10-16",
        supplier="Omicron Ltd",
        customer="Fabrikam Inc",
        currency="EUR",
        items=[("Hydraulic pump", 2, 450.00, 900.00)],
        subtotal=900.00,
        tax=90.00,
        total=990.00,
    ),
    Spec(
        "multipage_pdf_03",
        "pdf",
        number="INV-2026-3003",
        date="2026-10-17",
        supplier="Pi Engineering",
        customer="Contoso GmbH",
        currency="USD",
        items=[
            ("Motor mount", 4, 55.00, 220.00),
            ("Drive belt", 6, 18.00, 108.00),
            ("Pulley", 8, 9.00, 72.00),
        ],
        subtotal=400.00,
        tax=40.00,
        total=440.00,
        pages=2,
    ),
    Spec(
        "multipage_pdf_04",
        "pdf",
        number="INV-2026-3004",
        date="2026-10-18",
        supplier="Rho Systems",
        customer="Adventure Works",
        currency="USD",
        items=[("Server rack", 2, 350.00, 700.00), ("Patch panel", 5, 60.00, 300.00)],
        subtotal=1000.00,
        tax=100.00,
        total=1100.00,
        pages=2,
    ),
    Spec(
        "arithmetic_pdf_05",
        "pdf",
        number="INV-2026-3005",
        date="2026-10-19",
        supplier="Sigma Tools",
        customer="Fabrikam Inc",
        currency="USD",
        items=[("Drill bit set", 3, 33.333, 100.00)],
        subtotal=100.00,
        tax=10.00,
        total=120.00,
        edge="arithmetic_mismatch",
        expected_status="needs_review",
        expected_rules=("subtotal_tax_total",),
    ),
    Spec(
        "no_tax_pdf_06",
        "pdf",
        number="INV-2026-3006",
        date="2026-10-20",
        supplier="Tau Supplies",
        customer="Northwind Traders",
        currency="USD",
        items=[("Safety gloves", 50, 4.00, 200.00)],
        subtotal=200.00,
        tax=0.00,
        total=200.00,
        edge="missing_tax",
    ),
    Spec(
        "duplicate_b_pdf_07",
        "pdf",
        number="INV-DUP-9001",
        date="2026-10-13",
        supplier="Duplicate Co",
        customer="Northwind Traders",
        currency="USD",
        items=[("Repeated item", 1, 300.00, 300.00)],
        subtotal=300.00,
        tax=30.00,
        total=330.00,
        edge="duplicate_pair_second",
        expected_rules=("duplicate_invoice",),
    ),
    Spec(
        "missing_customer_pdf_08",
        "pdf",
        number="INV-2026-3008",
        date="2026-10-21",
        supplier="Upsilon Ltd",
        customer=None,
        currency="USD",
        items=[("Valve", 10, 15.00, 150.00)],
        subtotal=150.00,
        tax=15.00,
        total=165.00,
        edge="missing_customer",
        expected_status="needs_review",
        expected_rules=("missing_field",),
    ),
    Spec(
        "clean_pdf_09",
        "pdf",
        number="INV-2026-3009",
        date="2026-10-22",
        supplier="Phi Manufacturing",
        customer="Contoso GmbH",
        currency="CAD",
        items=[("Bracket", 100, 2.50, 250.00), ("Fastener", 400, 0.30, 120.00)],
        subtotal=370.00,
        tax=37.00,
        total=407.00,
    ),
    # PNG (scanned, OCR) ----------------------------------------------------
    Spec(
        "clean_png_01",
        "png",
        number="INV-2026-4001",
        date="2026-10-23",
        supplier="Chi Foods LLC",
        customer="Northwind Traders",
        currency="USD",
        items=[("Olive oil case", 12, 45.00, 540.00)],
        subtotal=540.00,
        tax=54.00,
        total=594.00,
    ),
    Spec(
        "clean_png_02",
        "png",
        number="INV-2026-4002",
        date="2026-10-24",
        supplier="Psi Textiles",
        customer="Adventure Works",
        currency="GBP",
        items=[("Cotton roll", 10, 22.00, 220.00), ("Thread spool", 30, 3.00, 90.00)],
        subtotal=310.00,
        tax=31.00,
        total=341.00,
    ),
    Spec(
        "clean_png_03",
        "png",
        number="INV-2026-4003",
        date="2026-10-25",
        supplier="Omega Foods",
        customer="Contoso GmbH",
        currency="EUR",
        items=[("Coffee beans", 20, 12.50, 250.00)],
        subtotal=250.00,
        tax=25.00,
        total=275.00,
    ),
    Spec(
        "clean_png_04",
        "png",
        number="INV-2026-4004",
        date="2026-10-26",
        supplier="Alpha Hardware",
        customer="Fabrikam Inc",
        currency="USD",
        items=[("Nail box", 15, 8.00, 120.00), ("Screw box", 15, 9.00, 135.00)],
        subtotal=255.00,
        tax=25.50,
        total=280.50,
    ),
    Spec(
        "clean_png_05",
        "png",
        number="INV-2026-4005",
        date="2026-10-27",
        supplier="Omega Foods",
        customer="Northwind Traders",
        currency="USD",
        items=[("Sugar sack", 40, 11.00, 440.00)],
        subtotal=440.00,
        tax=44.00,
        total=484.00,
    ),
]

# Two deliberate pipeline failures, inserted directly (not uploadable live).
FAILURES = [
    {
        "filename": "eval_corrupt_csv_01.csv",
        "kind": "csv",
        "edge_case": "empty_file_failure",
        "data": b"",
    },
    {
        "filename": "eval_corrupt_csv_02.csv",
        "kind": "csv",
        "edge_case": "blank_file_failure",
        "data": b"\n\n\n",
    },
]


# ── renderers ────────────────────────────────────────────────────────────────


COLUMNS = [
    "Invoice Number",
    "Invoice Date",
    "Supplier",
    "Customer",
    "Currency",
    "Item",
    "Qty",
    "Unit Price",
    "Amount",
    "Subtotal",
    "Tax",
    "Total",
]


def _row(spec: Spec, item: tuple | None) -> list[object]:
    description, quantity, unit_price, amount = item or (None, None, None, None)
    return [
        spec.number or "",
        spec.date or "",
        spec.supplier or "",
        spec.customer or "",
        spec.currency or "",
        description or "",
        "" if quantity is None else _num(quantity),
        "" if unit_price is None else f"{unit_price:.2f}",
        "" if amount is None else f"{amount:.2f}",
        _money(spec.subtotal, spec.comma_money),
        _money(spec.tax, spec.comma_money),
        _money(spec.total, spec.comma_money),
    ]


def render_csv(spec: Spec) -> bytes:
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(COLUMNS)
    for item in spec.items or [None]:
        writer.writerow(_row(spec, item))
    return buffer.getvalue().encode()


def _num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def render_xlsx(spec: Spec) -> bytes:
    import io

    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Invoice"
    sheet.append(COLUMNS)
    for item in spec.items or [None]:
        sheet.append(_row(spec, item))
    if spec.notes:
        notes = workbook.create_sheet("Notes")
        notes.append(["Note"])
        notes.append(["Thank you for your business"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _pdf_lines(spec: Spec) -> list[tuple[str, int]]:
    lines: list[tuple[str, int]] = [
        ("INVOICE", 22),
        (f"Invoice Number: {spec.number}", 12) if spec.number else ("", 12),
        (f"Invoice Date: {spec.date}", 12) if spec.date else ("", 12),
        (f"Supplier: {spec.supplier}", 12) if spec.supplier else ("", 12),
        (f"Customer: {spec.customer}", 12) if spec.customer else ("", 12),
        (f"Currency: {spec.currency}", 12) if spec.currency else ("", 12),
        ("", 12),
        ("Item                          Qty    Unit Price    Amount", 11),
    ]
    for description, quantity, unit_price, amount in spec.items:
        lines.append((f"{description:<28}{_num(quantity):>4}   {unit_price:>9.2f}   {amount:>9.2f}", 11))
    lines += [
        ("", 12),
        (f"Subtotal: {_money(spec.subtotal, spec.comma_money)}", 12),
        (f"Tax: {_money(spec.tax, spec.comma_money)}", 12),
        (f"Total: {_money(spec.total, spec.comma_money)}", 13),
    ]
    return [(text, size) for text, size in lines if text]


def render_pdf(spec: Spec) -> bytes:
    import fitz

    document = fitz.open()
    lines = _pdf_lines(spec)
    chunks = [lines] if spec.pages == 1 else _split_pages(lines, spec.pages)
    for chunk in chunks:
        page = document.new_page(width=595, height=842)
        y = 64
        for text, size in chunk:
            page.insert_text((60, y), text, fontsize=size, fontname="helv")
            y += size + 8
    data = document.tobytes()
    document.close()
    return data


def _split_pages(lines: list[tuple[str, int]], pages: int) -> list[list[tuple[str, int]]]:
    """Push the item rows / totals onto a second page for multi-page sources."""
    header = lines[:8]
    body = lines[8:]
    midpoint = max(1, len(body) // 2)
    return [header + body[:midpoint], body[midpoint:]]


def render_png(spec: Spec) -> bytes:
    import io

    from PIL import Image, ImageDraw, ImageFont

    lines = _pdf_lines(spec)
    width, height = 900, 60 + 26 * len(lines) + 40
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 20)
    except Exception:  # noqa: BLE001 — font availability varies
        font = ImageFont.load_default(size=20)
    y = 30
    for text, size in lines:
        draw.text((40, y), text, fill="black", font=font)
        y += 26
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


RENDER = {"csv": render_csv, "xlsx": render_xlsx, "pdf": render_pdf, "png": render_png}


def expected_fields(spec: Spec) -> dict:
    return {
        "invoice_number": spec.number,
        "invoice_date": _iso(spec.date),
        "supplier_name": spec.supplier,
        "customer_name": spec.customer,
        "subtotal": spec.subtotal,
        "tax": spec.tax,
        "total": spec.total,
        "currency": spec.currency,
    }


def _iso(value: str | None) -> str | None:
    """Ground truth is stored in the canonical ISO form the pipeline targets."""
    if value is None:
        return None
    if len(value) == 10 and value[4] == "-":
        return value
    if len(value) == 10 and value[2] == "/":  # MM/DD/YYYY
        month, day, year = value.split("/")
        return f"{year}-{month}-{day}"
    from dateutil import parser as dateparser

    return dateparser.parse(value).date().isoformat()


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []

    for spec in SPECS:
        mime, source_kind, _ = KIND_META[spec.kind]
        data = RENDER[spec.kind](spec)
        (DOCS / spec.filename).write_bytes(data)
        records.append(
            {
                "filename": spec.filename,
                "source_kind": source_kind,
                "mime_type": mime,
                "edge_case": spec.edge,
                "expected_status": spec.expected_status,
                "expected_rules": spec.expected_rules,
                "fields": expected_fields(spec),
                "line_items": [
                    {"description": d, "quantity": q, "unit_price": u, "amount": a}
                    for d, q, u, a in spec.items
                ],
            }
        )

    for failure in FAILURES:
        mime, source_kind, _ = KIND_META[failure["kind"]]
        (DOCS / failure["filename"]).write_bytes(failure["data"])
        records.append(
            {
                "filename": failure["filename"],
                "source_kind": source_kind,
                "mime_type": mime,
                "edge_case": failure["edge_case"],
                "expected_status": "failed",
                "expected_rules": [],
                "fields": {name: None for name in HEADER_FIELDS},
                "line_items": [],
            }
        )

    (OUT / "ground_truth.json").write_text(json.dumps(records, indent=2) + "\n")

    with (OUT / "ground_truth.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["filename", *HEADER_FIELDS, "line_item_count", "expected_status", "expected_rules", "edge_case"]
        )
        for record in records:
            fields = record["fields"]
            writer.writerow(
                [
                    record["filename"],
                    *[_csv_cell(fields[name]) for name in HEADER_FIELDS],
                    len(record["line_items"]),
                    record["expected_status"],
                    "|".join(record["expected_rules"]),
                    record["edge_case"],
                ]
            )

    print(f"wrote {len(records)} documents to {DOCS}")
    print(f"wrote {OUT / 'ground_truth.json'}")
    print(f"wrote {OUT / 'ground_truth.csv'}")


def _csv_cell(value: object) -> str:
    return "" if value is None else str(value)


if __name__ == "__main__":
    main()
