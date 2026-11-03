"""Generate the PDF parser fixtures. Dev-only (needs reportlab).

    python tests/fixtures/make_pdf_fixture.py

Writes, under tests/fixtures/demo_pdf/:
  statement_dec.pdf            two-page statement; the table header is printed again on page 2
  statement_dec.expected.json  what the parser must return, computed from ROWS below
  no_text.pdf                  a page with only a drawn rectangle (stands in for a scan)

The expected JSON is derived from the same source rows that are drawn into the PDF, not from
the parser, so the golden test checks extraction against the data, not against itself.
"""

from __future__ import annotations

import json
from pathlib import Path

from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

rl_config.invariant = 1  # no timestamps or random ids, so regenerating gives identical bytes

OUT = Path(__file__).parent / "demo_pdf"
OPENING_PAISE = 25_000_000
ROWS_ON_PAGE_1 = 30
HEADER = ["Date", "Narration", "Withdrawal", "Deposit", "Balance"]

# (day of December 2026, narration, debit paise, credit paise, utr)
ROWS: list[tuple[int, str, int, int, str | None]] = []
for i in range(48):
    day = 1 + i * 30 // 48
    if i % 3 == 0:
        utr = f"41230010{i:04d}"
        ROWS.append((day, f"UPI/{utr}/CUSTOMER {i}/c{i}@okaxis", 0, 1_500_000 + i * 10_000, utr))
    elif i % 3 == 1:
        ROWS.append((day, f"NEFT DR-SUPPLIER {i}-INV {1000 + i}", 900_000 + i * 5_000, 0, None))
    else:
        ROWS.append((day, f"POS {i:02d} STATIONERY MART", 250_050, 0, None))


def rupees(paise: int) -> str:
    rupee, rest = divmod(paise, 100)
    return f"{rupee:,}.{rest:02d}"


def styled_table(rows: list[list[str]]) -> Table:
    table = Table(rows, colWidths=[70, 220, 70, 70, 80])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    return table


def build_statement() -> dict[str, object]:
    balance = OPENING_PAISE
    pages: list[list[list[str]]] = [[HEADER], [HEADER]]
    expected_rows = []
    for i, (day, narration, debit, credit, utr) in enumerate(ROWS):
        balance += credit - debit
        page = 0 if i < ROWS_ON_PAGE_1 else 1
        pages[page].append([f"{day:02d}/12/2026", narration, rupees(debit) if debit else "",
                            rupees(credit) if credit else "", rupees(balance)])
        expected_rows.append({
            # page number * 1000 + row index within that page's table (header is row 0)
            "line_no": (page + 1) * 1000 + len(pages[page]) - 1,
            "txn_date": f"2026-12-{day:02d}", "amount_paise": debit or credit,
            "direction": "debit" if debit else "credit", "balance_after_paise": balance,
            "narration": narration, "utr": utr,
        })

    styles = getSampleStyleSheet()
    story = [
        Paragraph("DEMO BANK - Account Statement, December 2026", styles["Title"]),
        Paragraph(f"Opening Balance: {rupees(OPENING_PAISE)}", styles["Normal"]),
        Spacer(1, 12),
        styled_table(pages[0]),
        PageBreak(),
        styled_table(pages[1]),
        Spacer(1, 12),
        Paragraph(f"Closing Balance: {rupees(balance)}", styles["Normal"]),
    ]
    SimpleDocTemplate(str(OUT / "statement_dec.pdf"), pagesize=A4).build(story)
    return {"parser_version": "demo-pdf/1", "opening_paise": OPENING_PAISE,
            "closing_paise": balance, "rows": expected_rows}


def build_no_text() -> None:
    c = canvas.Canvas(str(OUT / "no_text.pdf"), pagesize=A4)
    c.rect(100, 400, 300, 200, fill=1)
    c.showPage()
    c.save()


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    expected = build_statement()
    (OUT / "statement_dec.expected.json").write_text(json.dumps(expected, indent=1) + "\n")
    build_no_text()
    print(f"wrote fixtures to {OUT}")
