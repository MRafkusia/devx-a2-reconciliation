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

## October dummy dataset

A second, synthetic dataset (PT Prima Kertas, October 2026) with an answer key was run after two extractor fixes: credit notes labelled "CN No." / "Credit Note No." are now read, and a continuation page that repeats the header is merged into its document when the document has no totals yet. Batch: PDF IDR 38,664,890, ERP IDR 41,875,818, difference IDR -3,210,928, unexplained IDR 0. The September results are unchanged.

| Group | Result against the answer key |
|---|---|
| Must-pass (M01-M18) | 18 of 18 with the expected status and difference, including INV 0215 (two pages, MATCHED), CN 0013 (MATCHED) and CN 0014 (NEEDS_REVIEW, KEY_CN_REFERENCE_MISMATCH). M11 shows the difference as -949,050 (the ERP total of the duplicate pair) where the answer key says 0, the same convention as September INV 0147. |
| Scanned (S01-S06) | S01, S02 matched; S05 NEEDS_REVIEW as expected. S03, S04 and S06 do not match the key (see below), all three end up for review or on hold, none is paid. |
| Limit probes (L01-L05) | L04 NEEDS_REVIEW as expected. L01 MATCHED (the key allows review; the decimal quantity and discount were read correctly). L02, L03 and L05 are not recognised as the case the key describes (see below). |

Still failing, or handled only by sending to review:

- **S03, low-quality scan (150 dpi, JPEG quality 40):** OCR misreads the page, the arithmetic check fails, and the invoice goes to review (OCR_UNVERIFIED) instead of matching.
- **S04, unreadable page (page 22):** the page is held for review as an unreadable page, but it is not linked to ERP entry E-10525 (INV 0224), which shows as MISSING_IN_PDF.
- **S06, two-page scan (INV 0226, pages 24-25):** each page is verified on its own, so the invoice stays NEEDS_REVIEW with OCR_UNVERIFIED. This is the intended, safe behaviour for now.
- **L05, USD entry:** the ERP entry shows as MISSING_IN_PDF with a -1,332 difference; it is not flagged as a currency issue.
- **L02, one ERP entry covering two invoices:** shown as missing on both sides (the PDF invoice as MISSING_IN_ERP, the ERP entry as MISSING_IN_PDF) rather than as one reviewed case.
- **L03, other supplier layout:** its PDF was not part of this run, so the ERP entry shows as MISSING_IN_PDF.

## Test suite

126 tests: rules and rounding, normalisation, PDF extraction (including OCR accepted and OCR rejected), ERP loading with shuffled columns, every status, the bridge adding up exactly, the web API (including cross-origin and download restrictions), the payment position, reviewer decisions flowing into the exports, command-line error handling, password protection, the end-to-end September golden results, credit notes with a different number label, and continuation pages that repeat the header.

## Cost and speed

0 model calls, USD 0 per run, about 2 seconds for the September batch including OCR of one page.

## Failures, weak points and honest limits

- **Only one supplier layout has been tested.** The extractor is built around PT Prima Kertas' invoice layout; another supplier will fall back to "page unreadable" until a layout profile is added. This is the biggest risk for the October demo if the October file has a different layout.
- **One synthetic October dataset has been run** (see above). A real October file may still differ from it.
- **OCR depends on Tesseract.** Without it the program stops with an install message; with `--no-ocr` the scanned page is reported, not read. With it, the one scanned page verified on the first attempt; a noisier scan might fail all five attempts and go to review.
- **Verification can reject a correct reading.** If a scanned invoice is itself wrong arithmetically, the page is flagged unverified even if OCR read it perfectly; that is intended, but a reviewer has to look.
- **Matching is one document to one document.** One payment covering several invoices, or partial deliveries, are not modelled.
- **No gap detection.** ERP entry IDs E-10457 to E-10459 are missing from the export and the tool does not say so.
- **IDR only.** The tolerance and rules assume Indonesian rupiah and 12 % VAT on 11/12 of the base.
- **Python version.** Tested on Python 3.13 only.
