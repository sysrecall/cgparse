"""OpenParser normalization: tables must survive into the page text."""

from types import SimpleNamespace

from app_core.clients.openparser import _normalize


def _element(text=None, *, kind="text", page=1, score=0.9, cells=None, html=None):
    element = SimpleNamespace(
        text=text,
        kind=kind,
        confidence=SimpleNamespace(score=score),
        locations=[SimpleNamespace(page_number=page)],
    )
    if cells is not None:
        element.cells = cells
    if html is not None:
        element.html = html
    return element


def _cell(row, column, text):
    return SimpleNamespace(row_index=row, column_index=column, text=text)


def test_table_cells_become_rows_in_reading_order():
    table = _element(
        kind="table",
        cells=[
            _cell(0, 0, "QTY"),
            _cell(0, 1, "DESCRIPTION"),
            _cell(0, 2, "AMOUNT"),
            _cell(1, 0, "1"),
            _cell(1, 1, "Brake cables"),
            _cell(1, 2, "100.00"),
            _cell(2, 1, "Subtotal"),
            _cell(2, 2, "195.00"),
        ],
    )

    page = _normalize(SimpleNamespace(elements=[table], text=None))["pages"][0]

    assert page["text"] == "QTY | DESCRIPTION | AMOUNT\n1 | Brake cables | 100.00\nSubtotal | 195.00"


def test_empty_cells_are_skipped_but_the_row_is_kept():
    table = _element(
        kind="table",
        cells=[_cell(0, 0, ""), _cell(0, 1, "TOTAL"), _cell(0, 2, "$204.75")],
    )

    page = _normalize(SimpleNamespace(elements=[table], text=None))["pages"][0]

    assert page["text"] == "TOTAL | $204.75"


def test_table_falls_back_to_html_when_cells_are_missing():
    table = _element(
        kind="table",
        cells=[],
        html="<table><tr><td>Subtotal</td><td>195.00</td></tr>"
        "<tr><td>TOTAL</td><td>$204.75</td></tr></table>",
    )

    page = _normalize(SimpleNamespace(elements=[table], text=None))["pages"][0]

    assert page["text"] == "Subtotal | 195.00\nTOTAL | $204.75"


def test_table_keeps_the_element_confidence():
    table = _element(kind="table", score=0.8, cells=[_cell(0, 0, "TOTAL"), _cell(0, 1, "1.00")])

    page = _normalize(SimpleNamespace(elements=[table], text=None))["pages"][0]

    assert page["confidence"] == 0.8


def test_text_and_table_share_a_page_in_element_order():
    result = SimpleNamespace(
        elements=[
            _element("INVOICE"),
            _element(kind="table", cells=[_cell(0, 0, "TOTAL"), _cell(0, 1, "9.99")]),
            _element("Thank you"),
        ],
        text=None,
    )

    page = _normalize(result)["pages"][0]

    assert page["text"] == "INVOICE\nTOTAL | 9.99\nThank you"


def test_pages_are_split_and_sorted():
    result = SimpleNamespace(
        elements=[
            _element("second page", page=2),
            _element("first page", page=1),
        ],
        text=None,
    )

    pages = _normalize(result)["pages"]

    assert [p["page_number"] for p in pages] == [1, 2]
    assert [p["text"] for p in pages] == ["first page", "second page"]


def test_top_level_text_is_used_when_there_are_no_elements():
    page = _normalize(SimpleNamespace(elements=[], text="plain text"))["pages"][0]

    assert page["text"] == "plain text"
    assert page["confidence"] is None
