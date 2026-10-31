# Evaluation report — document intelligence pipeline

- **Generated:** 2026-10-30T11:19:44+00:00
- **Model:** `openai/gpt-oss-20b` (LLM pass enabled)
- **Corpus:** 31 documents from `seed/eval/`
- **Workers:** 4 · **Database:** dedicated Supabase dev project

## 1. Headline

| Metric | Value |
|---|---|
| Validated (success rate) | 24 (0.7742) |
| Needs review | 5 (0.1613) |
| Failed | 2 (0.0645) |
| Expected-status accuracy | 1.0000 |
| Macro field accuracy (exact) | 0.9957 |
| Macro field accuracy (fuzzy) | 0.9957 |
| Line-item recall | 1.0000 |
| Line-item precision | 1.0000 |
| Validation rule F1 | 1.0000 |
| Wall time | 228.17 s (0.1359 docs/s) |
| LLM tokens | 30865 total, 995.6 / doc |

## 2. Field extraction

| Field | Exact | Fuzzy | Null precision | Null recall | Hallucination rate |
|---|---|---|---|---|---|
| invoice_number | 1.0000 | 1.0000 | — | — | — |
| invoice_date | 0.9655 | 0.9655 | — | — | — |
| supplier_name | 1.0000 | 1.0000 | — | — | — |
| customer_name | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.0000 |
| subtotal | 1.0000 | 1.0000 | — | — | — |
| tax | 1.0000 | 1.0000 | — | — | — |
| total | 1.0000 | 1.0000 | — | — | — |
| currency | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.0000 |

Null precision/recall treat "field absent" as the positive class: a high hallucination rate means the model invented values for fields the source omitted.

## 3. Line items

| Metric | Value |
|---|---|
| Expected items | 45 |
| Extracted items | 45 |
| Matched items | 45 |
| Recall | 1.0000 |
| Precision | 1.0000 |
| Documents with all items matched | 28/28 |

Per-attribute accuracy over matched items:

| Attribute | Accuracy |
|---|---|
| description | 1.0000 |
| quantity | 1.0000 |
| unit_price | 1.0000 |
| amount | 1.0000 |

## 4. Validation rules

Micro precision **1.0000**, recall **1.0000**, F1 **1.0000** (TP 7, FP 0, FN 0).

| Rule | TP | FP | FN |
|---|---|---|---|
| duplicate_invoice | 2 | 0 | 0 |
| line_items_sum | 1 | 0 | 0 |
| missing_field | 2 | 0 | 0 |
| subtotal_tax_total | 1 | 0 | 0 |
| type_and_format | 1 | 0 | 0 |

## 5. Performance

| Stage | n | p50 (s) | p95 (s) |
|---|---|---|---|
| parse | 31 | 2.20 | 5.84 |
| extract | 29 | 12.89 | 27.17 |
| validate | 29 | 1.99 | 2.79 |
| index | 29 | 1.05 | 1.47 |

Per-document total: p50 18.62 s · p95 31.77 s · max 58.68 s.

## 6. Per-document results

| Document | Edge case | Expected | Actual | Rules (expected / actual) |
|---|---|---|---|---|
| eval_clean_csv_01.csv | clean | validated | validated | — / — |
| eval_clean_csv_02.csv | clean | validated | validated | — / — |
| eval_clean_csv_03.csv | clean | validated | validated | — / — |
| eval_comma_money_csv_04.csv | comma_money | validated | validated | — / — |
| eval_missing_tax_csv_05.csv | missing_tax | validated | validated | — / — |
| eval_us_date_csv_06.csv | us_date | needs_review | needs_review | type_and_format / type_and_format |
| eval_missing_currency_csv_07.csv | missing_currency | needs_review | needs_review | missing_field / missing_field |
| eval_no_line_items_csv_08.csv | no_line_items | validated | validated | — / — |
| eval_clean_xlsx_01.xlsx | clean | validated | validated | — / — |
| eval_clean_xlsx_02.xlsx | clean | validated | validated | — / — |
| eval_multiline_xlsx_03.xlsx | clean | validated | validated | — / — |
| eval_line_sum_xlsx_04.xlsx | line_items_sum | needs_review | needs_review | line_items_sum / line_items_sum |
| eval_duplicate_a_xlsx_05.xlsx | duplicate_pair_first | validated | validated | duplicate_invoice / duplicate_invoice |
| eval_long_date_xlsx_06.xlsx | long_date | validated | validated | — / — |
| eval_clean_xlsx_07.xlsx | clean | validated | validated | — / — |
| eval_clean_pdf_01.pdf | clean | validated | validated | — / — |
| eval_clean_pdf_02.pdf | clean | validated | validated | — / — |
| eval_multipage_pdf_03.pdf | clean | validated | validated | — / — |
| eval_multipage_pdf_04.pdf | clean | validated | validated | — / — |
| eval_arithmetic_pdf_05.pdf | arithmetic_mismatch | needs_review | needs_review | subtotal_tax_total / subtotal_tax_total |
| eval_no_tax_pdf_06.pdf | missing_tax | validated | validated | — / — |
| eval_duplicate_b_pdf_07.pdf | duplicate_pair_second | validated | validated | duplicate_invoice / duplicate_invoice |
| eval_missing_customer_pdf_08.pdf | missing_customer | needs_review | needs_review | missing_field / missing_field |
| eval_clean_pdf_09.pdf | clean | validated | validated | — / — |
| eval_clean_png_01.png | clean | validated | validated | — / — |
| eval_clean_png_02.png | clean | validated | validated | — / — |
| eval_clean_png_03.png | clean | validated | validated | — / — |
| eval_clean_png_04.png | clean | validated | validated | — / — |
| eval_clean_png_05.png | clean | validated | validated | — / — |
| eval_corrupt_csv_01.csv | empty_file_failure | failed | failed | — / — |
| eval_corrupt_csv_02.csv | blank_file_failure | failed | failed | — / — |

## 7. Failures

| Document | Edge case | Error |
|---|---|---|
| eval_corrupt_csv_01.csv | empty_file_failure | parse: EmptyDataError: No columns to parse from file |
| eval_corrupt_csv_02.csv | blank_file_failure | parse: EmptyDataError: No columns to parse from file |

## 8. Known limitations

- Negative line-item values are blocked by DB `CHECK` constraints, so the
  `negative_or_impossible_values` rule can only be covered by unit tests, not by
  persisted corpus documents.
- `duplicate_invoice` compares each extraction against every *other* persisted
  extraction, so both members of a duplicate pair are flagged (a warning never
  moves a document to review on its own).
- Heuristic dates are literal evidence: a non-ISO date (e.g. `MM/DD/YYYY`) is kept
  verbatim and flagged by `type_and_format` rather than auto-converted.
- OCR (PaddleOCR-VL) and the LLM are nondeterministic providers; reruns can move
  per-document results by a small amount.
