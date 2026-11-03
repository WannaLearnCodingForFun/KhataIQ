# Parsers spec

Every parser implements `khataiq.pipeline.parsers.base.Parser` and returns a `ParsedStatement`.
Parsers are pure: bytes in, `ParsedStatement` out, no DB or network.

## Contract
- `bank`, `format`, `version` class attributes. Bump `version` on any behaviour change.
- Rows are returned in statement order. `line_no` is the 1-based line (CSV) or row index in the
  extracted table plus page offset (PDF) — whatever lets a human find the row.
- `amount_paise > 0` always; `direction` is `debit` or `credit`. A row with both debit and credit
  filled, or neither, is a `ParseError`.
- Opening and closing balances come from the statement header/footer. If a format has no explicit
  opening balance, derive it from the first row: `balance_after − credit + debit`, and say so in the
  parser docstring.
- `narration` is kept as printed (trimmed). Normalisation happens in `fingerprint()`.
- `utr` from `normalize.extract_utr(narration)` unless the format has a reference column.
- Unknown encodings: try UTF-8 (with BOM), then cp1252; anything else → `ParseError(0, ...)`.

## Generic CSV (M0.2)
Config per bank (a frozen dataclass in `parsers/configs.py`):
```
bank, version, date_column, date_formats[], narration_column, debit_column, credit_column,
balance_column, utr_column | None, header_marker (text of the header row's first cell),
opening_label | None, closing_label | None, skip_footer_prefixes[]
```
The parser finds the header row by `header_marker`, reads until a blank line or a footer prefix,
and maps columns by header name (case-insensitive, trimmed), not by position.

## PDF text (M0.3)
- `pdfplumber` → `page.extract_tables()` for each page; concatenate rows; drop repeated header rows.
- Opening/closing balances found with regexes on page text (`Opening Balance`, `Closing Balance`).
- No extractable text → `ParseError(0, "no text layer")`. OCR is out of scope.

## Golden files
Each fixture `X.csv|pdf` has `X.expected.json` (rows as dicts, money as int paise, dates ISO).
The test parses the fixture and compares to the JSON exactly. Changing a golden file requires
saying why in the PR.
