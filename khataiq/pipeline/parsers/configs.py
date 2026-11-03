"""Column-mapping configs for GenericCsvParser. A new bank with a plain CSV export needs a new
config here, not new code."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CsvBankConfig:
    bank: str
    version: str
    date_column: str
    date_formats: tuple[str, ...]
    narration_column: str
    debit_column: str
    credit_column: str
    balance_column: str
    utr_column: str | None          # None -> extract_utr(narration)
    header_marker: str              # text of the header row's first cell
    opening_label: str | None       # None -> opening derived from the first row
    closing_label: str | None       # None -> closing taken from the last row's balance
    skip_footer_prefixes: tuple[str, ...] = ()


# Modelled on a typical private-bank net-banking export: account details above the header,
# a statement summary below it, no opening-balance line, and a reference column.
HDFC_LIKE = CsvBankConfig(
    bank="hdfc_like",
    version="hdfc-like-csv/1",
    date_column="Date",
    date_formats=("%d/%m/%y",),
    narration_column="Narration",
    debit_column="Withdrawal Amt.",
    credit_column="Deposit Amt.",
    balance_column="Closing Balance",
    utr_column="Chq./Ref.No.",
    header_marker="Date",
    opening_label=None,
    closing_label=None,
    skip_footer_prefixes=("STATEMENT SUMMARY",),
)

# Modelled on a typical public-sector-bank export: explicit opening and closing balance lines,
# dates like '1 Nov 2026', and a reference column that is not a payment reference.
SBI_LIKE = CsvBankConfig(
    bank="sbi_like",
    version="sbi-like-csv/1",
    date_column="Txn Date",
    date_formats=("%d %b %Y",),
    narration_column="Description",
    debit_column="Debit",
    credit_column="Credit",
    balance_column="Balance",
    utr_column=None,
    header_marker="Txn Date",
    opening_label="Opening Balance",
    closing_label="Closing Balance",
    skip_footer_prefixes=("**",),
)

ALL_CSV_CONFIGS: tuple[CsvBankConfig, ...] = (HDFC_LIKE, SBI_LIKE)
