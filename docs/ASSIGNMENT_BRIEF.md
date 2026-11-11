# Assignment brief and how this submission answers it

**Role:** AI/ML Engineer (Forward Deployed Engineer), devx AI Labs
**Chosen problem:** A2, Transaction Reconciliation
**Customer:** PT Nusantara Retail Group, supplier PT Prima Kertas Indonesia
**Input:** supplier invoice PDF and ERP accounts-payable export for September 2026; October files are used in the demo round
**Time box:** about 6 hours of work, 1 week deadline

## The problem in one paragraph

Each month the AP team compares the supplier's invoice PDF with what was booked in the ERP, by hand. It is slow and misses things such as duplicate entries, scanned pages, text-formatted numbers and supplier arithmetic mistakes. The task is to build a system that reconciles the two, explains every difference, and gives the AP manager a clear list of what to do.

## What the brief asks for and where it is

| Requirement | Where |
|---|---|
| Git repository that runs in 5 commands or fewer | `README.md`, section "Run it" |
| Architecture, decisions and trade-offs | `README.md` |
| Limitations and what to do with another week | `README.md` |
| Evaluation results including failures | `docs/EVALUATION.md` |
| One-page customer summary for a business owner or AP manager | `docs/CUSTOMER_SUMMARY.md` |
| One README paragraph on AI-tool usage | `README.md`, "How AI tools were used" |
| Must run on the October files without code changes | CLI arguments and the web interface take any PDF and workbook |
| Business rules R1 to R8 | `reconcile/rules.py`, `checks.py`, `match.py`; table in `README.md` |

## Traps in the data and how each is handled

| Trap | Handling |
|---|---|
| A scanned (image) page in the PDF | Scan detection, OCR with several attempts, accepted only when arithmetic verifies |
| An invoice that spans two pages with 34 lines | Pages joined by invoice number; row-number gap check |
| Credit note | Normalised to negative on both sides; reference to the original invoice compared |
| Document numbers written differently (`/` vs `-`) | Normalised key; noted as a format difference |
| Dates and totals stored as text in the ERP | Normalised and noted; ambiguous day/month resolved using the PDF date |
| Duplicate entry in the ERP | Counted once against the invoice; excess reported as its own component |
| Parked (unposted) ERP entry with no supplier document | `MISSING_IN_PDF` with a "not posted" note |
| Supplier's own arithmetic wrong (DPP, subtotal) | Flagged, never corrected |
| PO number differs although amounts agree | `NEEDS_REVIEW` |
| IDR 1 rounding difference | `MATCHED_WITHIN_TOLERANCE` |
| Shuffled or renamed ERP columns and sheets | Header-based recognition |

## Design thinking summary

- **Who:** an AP manager who must release payments and an AP clerk who investigates.
- **Their job:** decide what to pay, what to hold, and what to ask the supplier, with evidence.
- **So the output is:** a payment position (cleared, on hold, released), a review queue ranked by amount with one plain-language reason and one action per document, the reviewer's decision recorded in the same report, a batch bridge that proves nothing is unexplained, and a source for every figure.

## Goal to output check

| The AP manager asks | Where the answer is |
|---|---|
| How much can I pay now? | Payment position: web interface, `summary.md`, Control totals sheet |
| What is on hold and why? | `summary.md` "Act on these first", Review queue sheet |
| What do I do about each one? | Suggested action per document |
| Can I trust the numbers? | Batch bridge (unexplained = 0), Audit trail sheet |
| Who decided what? | Decisions sheet, `decisions.csv` |
| What happened last month? | One folder per run under `output/` |
- **Engineering focus:** correctness and traceability over cleverness; deterministic, tested, explainable.
