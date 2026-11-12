# Supplier invoice reconciliation (PDF vs ERP)

Reconciles a supplier's invoice PDF against an ERP accounts-payable export and tells an AP team, document by document, what agrees, what does not, why, and what to do next. Built for PT Nusantara Retail Group and its supplier PT Prima Kertas Indonesia (September 2026 sample).

It is a deterministic pipeline: **no language-model calls at run time, 0 API cost, about 2 seconds for the 16-document September batch**, and the same input always gives the same output.

## Run it (5 commands)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
brew install tesseract            # OCR engine for scanned pages (Linux: apt install tesseract-ocr)
python -m reconcile run --pdf data/sept/Supplier_Invoices_PT_Prima_Kertas_Sep2026.pdf --erp data/sept/ERP_AP_Export_Sep2026.xlsx
python -m reconcile serve         # web interface at http://127.0.0.1:8000
```

### Or with Docker (Tesseract included, nothing else to install)

```bash
docker build -t reconcile .
docker run -p 8000:8000 -v reconcile-output:/app/output reconcile
```

Then open http://127.0.0.1:8000. The image contains Python, the dependencies, Tesseract and the September sample.

For the October files: pass the new PDF and workbook to the same command, or open the web interface, choose both files and press **Run reconciliation**. No code change is needed.

Every run is kept in its own folder, `output/<date-time>_<pdf name>/`, so an earlier month is never overwritten:

| File | Purpose |
|---|---|
| `summary.md` | Read this first. Payment position, then the open items ranked by amount, each with its reason, action and reviewer decision |
| `reconciliation_report.xlsx` | Main report for reviewers. Sheets: Control totals, Documents, Decisions, Review queue, Line discrepancies, Audit trail, Extraction log, Reason codes |
| `decisions.csv` | Reviewer decision and note per document |
| `reconciliation_report.csv`, `line_discrepancies.csv`, `control_totals.csv`, `audit_trail.csv` | Same data as flat files |
| `report.json` | Machine-readable result used by the web interface |

The command line exits with a one-line error (exit code 2) when an input file is missing or cannot be read.

If Tesseract is missing, both commands stop immediately with an install message instead of running. `python -m reconcile run ... --no-ocr` skips OCR on purpose; scanned pages are then flagged for review.

Tests: `python -m pytest` (126 tests; the OCR tests are skipped if tesseract is not installed).

## What it does

1. **Extract** the PDF text layer with `pdfplumber`. Invoices that span several pages are joined. A page that is a scanned image is OCR-ed with Tesseract, and the OCR result is accepted only if the invoice's own arithmetic checks pass; otherwise it is flagged `OCR_UNVERIFIED` and sent to review.
2. **Load** the ERP workbook. Sheets and columns are recognised by their header names (aliases), not by position or sheet name. Text dates and text amounts are normalised.
3. **Check each document on its own** against the stated tax rules (below), on both the PDF and the ERP side.
4. **Match** documents on a normalised document number, then compare totals and line by line.
5. **Classify** each document, explain the difference in plain language, and propose an action.
6. **State the payment position**: how much is cleared for payment, how much is on hold until someone reviews it, and how much was released by a reviewer. Cleared plus on hold plus released always equals the ERP total.
7. **Prove the totals**: the difference between the PDF batch total and the ERP batch total is broken into named components that add up exactly; the unexplained remainder is shown (0 for September).

## Business rules implemented

| Rule | Behaviour |
|---|---|
| R1 | Line amount = quantity × unit price × (1 − discount %) |
| R2 | Subtotal = sum of line amounts |
| R3 | Tax base (DPP nilai lain) = subtotal × 11/12 |
| R4 | VAT (PPN) = tax base × 12 %; total = subtotal + VAT |
| R5 | Differences of up to IDR 10 are tolerated only when no line differs, and are labelled `MATCHED_WITHIN_TOLERANCE` |
| R6 | Credit notes are negative; a positive PDF credit note is converted to negative |
| R7 | Supplier or ERP arithmetic errors are never corrected silently; they are flagged `NEEDS_REVIEW` |
| R8 | Statuses: `MATCHED`, `MATCHED_WITHIN_TOLERANCE`, `AMOUNT_MISMATCH`, `MISSING_IN_ERP`, `MISSING_IN_PDF`, `DUPLICATE_IN_ERP`, `DUPLICATE_IN_PDF`, `NEEDS_REVIEW` |

Money is held as whole-rupiah integers and computed with exact fractions; rounding is half-up (ties away from zero, so credit notes mirror invoices). Floats are rejected.

Status precedence when several things are true at once: duplicates, then `NEEDS_REVIEW` (integrity errors, key mismatches such as PO, date or credit-note reference, unverified OCR), then `AMOUNT_MISMATCH`, then tolerance, then `MATCHED`.

## Architecture

```
PDF  ──► pdf_extract ─┐                         ┌─► report.xlsx / csv / json
                      ├─► checks ─► match ─► explain ─┤
ERP  ──► erp_load ────┘                         └─► web interface (server.py + web/index.html)
```

| Module | Responsibility |
|---|---|
| `reconcile/rules.py` | Tax and rounding arithmetic |
| `reconcile/normalize.py` | Amount, date, document-number, SKU and vendor normalisation |
| `reconcile/pdf_extract.py` | Text-layer parsing, scan detection, verified OCR, supplier layout profiles |
| `reconcile/erp_load.py` | Header-based sheet and column recognition |
| `reconcile/checks.py` | Per-document arithmetic checks |
| `reconcile/match.py` | Pairing, line alignment, status, batch bridge |
| `reconcile/explain.py` | Reason codes to plain-language explanation and action |
| `reconcile/report.py` | XLSX, CSV and JSON output |
| `reconcile/server.py`, `web/index.html` | Local web interface (standard library only, no front-end dependencies) |

## Web interface

`python -m reconcile serve` serves `web/index.html` on localhost. It lets a reviewer upload the two files (or use the bundled September sample), see the payment position and the batch bridge from PDF total to ERP total, filter and search documents, open any document to see the explanation, suggested action, reason codes, line differences and the exact PDF page / ERP cell each figure came from, record an approve / hold / escalate decision with a note, and download the reports. A decision is written straight into that run's Excel report, `decisions.csv` and `summary.md`, and an approval moves the document from "on hold" to "released by a reviewer". A new run starts with no decisions. If the two files do not belong together (no document matches), a warning is shown instead of a page full of "missing" rows. It binds to `127.0.0.1`, accepts only same-origin POSTs, checks upload file signatures and limits uploads to 50 MB.

## Deploying it (Coolify or any container host)

The repository root has a `Dockerfile`, so a container platform can build it straight from Git.

| Setting | Value |
|---|---|
| Build pack | Dockerfile |
| Port | `8000` (or set `PORT`) |
| Health check path | `/healthz` |
| Persistent storage | mount a volume at `/app/output` so runs and decisions survive a redeploy |
| `RECONCILE_PASSWORD` | **set this** on any deployment that is reachable from the internet; the page and API then require sign-in (HTTP Basic) |
| `RECONCILE_USER` | optional sign-in name, default `reviewer` |

Without `RECONCILE_PASSWORD` the application has no login, and it holds supplier invoices and ERP data. It prints a warning at start when it listens on a network address without a password. Serve it over HTTPS (the platform's proxy does this) because Basic sign-in sends the password with every request.

## Key decisions and trade-offs

- **Deterministic code instead of an LLM.** Every rule is arithmetic with a defined answer. A model would add cost, latency and non-repeatability to a job where an auditor needs the same answer every time. The cost is that a new supplier layout needs a new profile (below).
- **No plain workflow tool (n8n, LangGraph).** The work is parsing and arithmetic, not orchestration; plain Python is easier to test and to explain.
- **Verified OCR.** OCR is allowed to read, never to decide: its output counts only when the document's own arithmetic holds, with several resolution/segmentation attempts before giving up.
- **Flag, never fix.** When the supplier's invoice is internally wrong (for example DPP not 11/12 of the subtotal), the system reports it and shows the numbers instead of choosing a side.
- **Exact bridge.** Reviewers see where every rupiah of the batch difference comes from.
- **Audit trail.** Every figure carries its source (PDF page and row text, or ERP sheet and cell).

## Where an LLM would help, and where it would not

Helpful: reading a new, unseen supplier layout once to draft a `SupplierLayout` profile that a human then approves; drafting the wording of a supplier query email. Not used for: arithmetic, matching, status, or anything that decides whether money is paid.

## Onboarding another supplier layout

Layouts live in `reconcile/pdf_extract.py` as `SupplierLayout` entries in `LAYOUTS` (regular expressions for document number, date, PO, totals, item rows, and the markers that identify the supplier). Add an entry, add the supplier's sample PDF under `data/`, add a test in `tests/test_extract.py`. If no layout matches a page, the page is listed in `PDF_PAGE_UNREADABLE` for review rather than guessed.

## Limitations

- Only the PT Prima Kertas Indonesia layout is implemented; other suppliers need a profile.
- Outside Docker, OCR depends on a local Tesseract install; the program refuses to start without it (or with `--no-ocr`, scanned pages go to review).
- Sign-in is a single shared password, not per-user accounts; uploaded files stay on the server's disk until the container is replaced.
- The Docker image has not been built in CI; it was written against `python:3.12-slim` while the test suite ran on Python 3.13.
- IDR documents only; other currencies are not converted.
- OCR verification proves the numbers, not the text: a misread item code or description can pass the arithmetic checks and then show as a line difference against the ERP.
- An unreadable page is held for review but is not yet linked to the ERP entry it probably belongs to; that entry shows as missing in the PDF.
- Foreign-currency ERP entries are not flagged specifically; they show up as an ordinary mismatch or a missing document.
- Matching is per document number with a PO/date/total fallback; it does not do many-to-one payments or partial deliveries.
- The ERP export is read as a file; there is no live ERP connection or posting back.
- Decisions made in the web interface are stored locally in the run folder; there is no login or multi-user control, and the web interface shows only the latest run (earlier runs stay on disk).
- Verified on Python 3.13; the code uses `from __future__ import annotations` so older 3.x versions should work but have not been tested.
- ERP entry IDs E-10457 to E-10459 are absent from the September export; the tool does not report gaps in ERP numbering.

## With another week

1. A second and third supplier layout, to prove the profile approach generalises.
2. A confidence report for OCR pages (per-field) shown in the web interface.
3. Many-to-one and partial matching (one payment against several invoices).
4. Gap detection in the supplier's invoice number sequence and the ERP entry sequence.
5. Optional LLM-assisted layout drafting with human approval.
6. Multi-user review queue with login and an export of decisions back to the ERP.

## How AI tools were used

Claude was used as a pair programmer for this submission: to discuss the approach, to draft the code, tests and web interface, and to draft the documents. The business rules were taken from the assignment brief and checked by running the code against the September files and comparing every document's result with a hand calculation. The deliverable's behaviour is covered by the test suite, and the system itself makes no AI calls when it runs.
