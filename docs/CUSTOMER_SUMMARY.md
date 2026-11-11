# September supplier reconciliation: what we found

**For:** AP Manager and Finance, PT Nusantara Retail Group
**Supplier:** PT Prima Kertas Indonesia, September 2026
**Checked:** 15 supplier documents (14 invoices, 1 credit note) against 16 ERP entries

## The short version

The supplier PDF totals **IDR 307,896,675** and the ERP holds **IDR 311,153,348**, so the ERP is **IDR 3,256,673 higher**. The whole difference is explained: each rupiah is traced to a specific document.

**7 documents are cleared for payment: IDR 163,542,864.** **9 documents are on hold: IDR 147,610,484 as booked in the ERP**, until someone acts on the list below.

| Result | Documents | What it means |
|---|---|---|
| Agree | 6 | Approve for payment |
| Agree within IDR 1 (rounding) | 1 | Approve; no action |
| Amounts differ | 3 | Quantity, price or an extra line differs |
| Supplier invoice looks wrong | 3 | Supplier's own figures do not add up, or the PO differs |
| Duplicate in ERP | 1 | Booked twice |
| Not in ERP | 1 | Supplier invoice nobody has booked |
| Not in supplier PDF | 1 | Parked ERP entry with no supplier document |

## Do these first

1. **Reverse the duplicate entry for invoice 0147: IDR 17,238,178.** It is booked twice (E-10456 and E-10460). Paying both overpays the supplier by that amount.
2. **Book or reject invoice 0146: IDR 15,688,629.** It is in the supplier's PDF but nowhere in the ERP, so it is a liability not yet recorded.
3. **Ask the supplier to correct invoices 0148 and 0149.** On 0148 the tax base is printed as IDR 20,484,150 but 11/12 of the subtotal is IDR 18,777,138 (printed total is IDR 204,841 too high). On 0149 the subtotal is IDR 100,000 higher than the sum of its lines (the printed total is IDR 111,000 too high). We do not correct the supplier's figures for them.
4. **Resolve three amount differences against the purchase order and delivery receipt:**
   - 0144: invoice says 120 units of AMP-110, ERP says 100 (IDR +527,250).
   - 0145: invoice unit price 52,500, ERP 49,500 for PK-A4-80-RM (IDR +666,000).
   - 0151: a delivery fee of IDR 250,000 is on the invoice but not in the ERP (IDR +277,500).
5. **Check invoice 0154 before paying.** Amounts agree but the PO number is different (PDF PO-88239, ERP PO-88293).
6. **Decide on parked ERP entry 0155: IDR 3,493,714.** The supplier did not send this invoice. Request it or remove the entry.

## Why you can trust the numbers

- Every figure links back to its source: the PDF page, or the ERP sheet and cell.
- The difference between the two batch totals is split into named causes that add up exactly (unexplained: IDR 0).
- One invoice page was a scanned image. It was read by OCR and accepted only because its own arithmetic checked out; if it had not, it would have been sent to review instead.
- Nothing is changed or paid by the tool. It only reports and recommends.
- The same files always give the same answer, and the run takes about two seconds.

## What it does not do

It does not post to the ERP, approve payments, or handle other suppliers' invoice layouts until each layout is added. The IDR 10 rounding tolerance is applied only when no line differs.

## What you get every month

A one-page summary like this one (`summary.md`) is produced automatically with each run, together with an Excel report. Reviewers record approve, hold or escalate per document, and those decisions appear in the same report.

## What we need from you

Confirm that IDR 10 is the right rounding tolerance, and send the October files so the same check can be run on them.
