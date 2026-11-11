# Evaluation

Evaluated on the September 2026 sample (15 supplier documents, 16 ERP entries). Expected results were worked out by hand from the PDF and the workbook before the code was run, and are asserted in `tests/test_integration.py`.

## Result per document

Difference is PDF total minus ERP total, in IDR.

| Document | Expected | Actual | Difference | Correct |
|---|---|---|---|---|
| INV 0141 | Matched | MATCHED | 0 | yes |
| INV 0142 | Matched (number format differs) | MATCHED | 0 | yes |
| INV 0143 | Within tolerance | MATCHED_WITHIN_TOLERANCE | -1 | yes |
| INV 0144 | Amount mismatch (quantity) | AMOUNT_MISMATCH | +527,250 | yes |
| INV 0145 | Amount mismatch (unit price) | AMOUNT_MISMATCH | +666,000 | yes |
| INV 0146 | Missing in ERP | MISSING_IN_ERP | +15,688,629 | yes |
| INV 0147 | Duplicate in ERP | DUPLICATE_IN_ERP | -17,238,178 | yes |
| INV 0148 | Supplier DPP wrong | NEEDS_REVIEW | +204,841 | yes |
| INV 0149 | Supplier subtotal wrong | NEEDS_REVIEW | +111,000 | yes |
| INV 0150 | Matched (scanned page) | MATCHED | 0 | yes |
| INV 0151 | Extra line only in PDF | AMOUNT_MISMATCH | +277,500 | yes |
| INV 0152 | Matched (text date and total) | MATCHED | 0 | yes |
| INV 0153 | Matched (two pages, 34 lines) | MATCHED | 0 | yes |
| INV 0154 | PO mismatch | NEEDS_REVIEW | 0 | yes |
| CN 0012 | Matched credit note | MATCHED | 0 | yes |
| INV 0155 | In ERP only, parked | MISSING_IN_PDF | -3,493,714 | yes |

16 of 16 results as expected. Payment position: 7 documents cleared for payment (IDR 163,542,864 as booked in the ERP), 9 on hold (IDR 147,610,484); the two add up to the ERP total. Batch: PDF IDR 307,896,675, ERP IDR 311,153,348, difference IDR -3,256,673, unexplained IDR 0.

## Test suite

117 tests: rules and rounding, normalisation, PDF extraction (including OCR accepted and OCR rejected), ERP loading with shuffled columns, every status, the bridge adding up exactly, the web API (including cross-origin and download restrictions), the payment position, reviewer decisions flowing into the exports, command-line error handling, password protection, and the end-to-end September golden results.

## Cost and speed

0 model calls, USD 0 per run, about 2 seconds for the September batch including OCR of one page.

## Failures, weak points and honest limits

- **Only one supplier layout has been tested.** The extractor is built around PT Prima Kertas' invoice layout; another supplier will fall back to "page unreadable" until a layout profile is added. This is the biggest risk for the October demo if the October file has a different layout.
- **October files have not been seen.** Behaviour on them is expected to be the same because nothing is hard-coded to September, but this is untested.
- **OCR depends on Tesseract.** Without it the program stops with an install message; with `--no-ocr` the scanned page is reported, not read. With it, the one scanned page verified on the first attempt; a noisier scan might fail all five attempts and go to review.
- **Verification can reject a correct reading.** If a scanned invoice is itself wrong arithmetically, the page is flagged unverified even if OCR read it perfectly; that is intended, but a reviewer has to look.
- **Matching is one document to one document.** One payment covering several invoices, or partial deliveries, are not modelled.
- **No gap detection.** ERP entry IDs E-10457 to E-10459 are missing from the export and the tool does not say so.
- **IDR only.** The tolerance and rules assume Indonesian rupiah and 12 % VAT on 11/12 of the base.
- **Python version.** Tested on Python 3.13 only.
