"""Plain-language explanations and suggested actions for reconciliation results."""

from __future__ import annotations

from typing import Dict, List, Tuple

from . import results as r
from .models import CREDIT_NOTE

REASON_LABELS: Dict[str, str] = {
    "MISSING_IN_ERP": "Invoice is in the supplier PDF but not booked in the ERP",
    "MISSING_IN_PDF": "ERP entry has no matching supplier document in the PDF",
    "DUPLICATE_IN_ERP": "Same supplier document booked more than once in the ERP",
    "DUPLICATE_IN_PDF": "Same document number appears more than once in the PDF",
    "DUPLICATE_ENTRIES_DIFFER": "Duplicate ERP entries do not carry identical figures",
    "ERP_NOT_POSTED": "ERP entry is not in Posted status",
    "PDF_PAGE_UNREADABLE": "A PDF page could not be read",
    "PDF_LINE_AMOUNT_WRONG": "A PDF line amount differs from quantity x price x discount",
    "PDF_SUBTOTAL_NOT_SUM_OF_LINES": "PDF subtotal differs from the sum of its own lines",
    "PDF_DPP_NOT_11_12": "PDF DPP is not subtotal x 11/12",
    "PDF_PPN_NOT_12_PCT": "PDF PPN is not DPP x 12%",
    "PDF_TOTAL_NOT_SUBTOTAL_PLUS_PPN": "PDF total is not subtotal + PPN",
    "PDF_FIELD_MISSING": "A figure or the line items could not be found in the PDF",
    "PDF_ROW_UNPARSED": "A PDF line item row could not be read",
    "PDF_ROW_GAP": "PDF line numbers are not consecutive",
    "PDF_INCOMPLETE_DOCUMENT": "PDF document has no totals block",
    "OCR_UNVERIFIED": "Scanned page figures failed the arithmetic checks",
    "ERP_LINE_AMOUNT_WRONG": "An ERP line amount differs from quantity x price x discount",
    "ERP_SUBTOTAL_NOT_SUM_OF_LINES": "ERP subtotal differs from the sum of its own lines",
    "ERP_DPP_NOT_11_12": "ERP DPP is not subtotal x 11/12",
    "ERP_PPN_NOT_12_PCT": "ERP PPN is not DPP x 12%",
    "ERP_TOTAL_NOT_SUBTOTAL_PLUS_PPN": "ERP total is not subtotal + PPN",
    "ERP_FIELD_MISSING": "A figure could not be read from the ERP entry",
    "ERP_NO_LINES": "ERP entry has no line items",
    "ERP_UNREADABLE_FIELD": "An ERP cell could not be read as a number",
    "PDF_ROUNDING": "PDF figure is within IDR 10 of the rule",
    "ERP_ROUNDING": "ERP figure is within IDR 10 of the rule",
    "KEY_PO_MISMATCH": "PO number differs between PDF and ERP",
    "KEY_DATE_MISMATCH": "Document date differs between PDF and ERP",
    "KEY_CN_REFERENCE_MISMATCH": "Credit note references a different invoice",
    "KEY_INVOICE_NO_MISMATCH": "Paired by PO and amount, but document numbers differ",
    "KEY_VENDOR_MISMATCH": "Vendor name differs between PDF and ERP",
    "KEY_CURRENCY_MISMATCH": "ERP currency is not IDR",
    "LINE_QTY_DIFF": "Quantity differs on a line",
    "LINE_PRICE_DIFF": "Unit price differs on a line",
    "LINE_DISCOUNT_DIFF": "Discount differs on a line",
    "LINE_AMOUNT_DIFF": "Line amount differs although quantity, price and discount agree",
    "LINE_SKU_DIFF": "Item code differs on the same line",
    "LINE_ONLY_IN_PDF": "Line exists on the invoice but not in the ERP",
    "LINE_ONLY_IN_ERP": "Line exists in the ERP but not on the invoice",
    "HEADER_AMOUNT_DIFF": "Totals differ with no line-level difference",
    "ROUNDING_DIFF": "Difference of IDR 10 or less, treated as rounding (R5)",
    "FORMAT_NORMALISED": "Matched after normalising format differences",
}

COMPONENT_LABELS: Dict[str, str] = {
    "line_items": "Line-item differences (quantity, price, discount, missing lines)",
    "pdf_subtotal_error": "PDF subtotal does not equal the sum of its own lines",
    "erp_subtotal_error": "ERP subtotal does not equal the sum of its own lines",
    "vat_on_subtotal_difference": "VAT that follows from the subtotal difference",
    "vat_rounding_or_error": "VAT or tax-base rounding / error beyond the subtotal difference",
    "total_inconsistency": "Total not equal to subtotal + PPN on one side",
    "document_missing_in_erp": "Invoice not booked in the ERP",
    "document_missing_in_pdf": "ERP entry without a supplier document",
    "duplicate_entry_in_erp": "Extra duplicate ERP entries",
    "duplicate_in_pdf": "Extra duplicate copies in the PDF",
}

LINE_CODE_PHRASES = {
    "LINE_QTY_DIFF": "quantity",
    "LINE_PRICE_DIFF": "unit price",
    "LINE_DISCOUNT_DIFF": "discount",
    "LINE_AMOUNT_DIFF": "amount",
    "LINE_SKU_DIFF": "item code",
}


def money(value: int, signed: bool = False) -> str:
    return f"{value:+,}" if signed and value else f"{value:,}"


def _clean_action(result: r.DocumentResult) -> str:
    if result.doc_type == CREDIT_NOTE:
        return "Apply the credit note against the supplier balance."
    return "Approve for payment."


def _line_sentences(result: r.DocumentResult, limit: int = 3) -> List[str]:
    sentences: List[str] = []
    for diff in result.line_diffs[:limit]:
        sentences.append(diff.detail)
    extra = len(result.line_diffs) - limit
    if extra > 0:
        sentences.append(f"{extra} more line difference(s) are listed in the line discrepancy sheet")
    return sentences


def _integrity_sentences(result: r.DocumentResult) -> List[str]:
    sentences = []
    for finding in result.findings:
        if finding.severity != "error":
            continue
        side = "The supplier PDF" if finding.code.startswith("PDF") else "The ERP entry"
        sentences.append(f"{side}: {finding.message}.")
    return sentences


def describe(result: r.DocumentResult) -> Tuple[str, str]:
    status = result.status
    reasons = set(result.reasons)
    diff = result.difference
    head = (
        f"PDF total {money(result.pdf_total)} vs ERP total {money(result.erp_total)} "
        f"(difference {money(diff, True)})."
    )
    erp_ids = ", ".join(d.entry_id for d in result.erp if d.entry_id)

    if status == r.MATCHED:
        text = "PDF and ERP agree on every figure and every line."
        if result.notes:
            text += " Format differences were normalised before comparing: " + "; ".join(result.notes) + "."
        return text, _clean_action(result)

    if status == r.MATCHED_WITHIN_TOLERANCE:
        text = (
            f"{head} The only difference is VAT rounding of IDR {abs(diff)} and every line agrees, "
            "so it counts as matched within tolerance (R5)."
        )
        return text, _clean_action(result) + " No action is needed on the rounding difference."

    if status == r.MISSING_IN_ERP:
        text = f"The supplier PDF contains this document ({money(result.pdf_total)}) but nothing with this number is booked in the ERP."
        sentences = _integrity_sentences(result)
        action = "Do not pay yet. Confirm the invoice is valid, then book it in the ERP, or reject it with the supplier."
        return " ".join([text] + sentences), action

    if status == r.MISSING_IN_PDF:
        text = f"The ERP holds this document ({money(result.erp_total)}, entry {erp_ids}) but the supplier PDF does not contain it."
        if "ERP_NOT_POSTED" in reasons:
            text += " The entry is still parked, not posted."
        if "PDF_PAGE_UNREADABLE" in reasons:
            text += " One PDF page could not be read, so check whether this document is on that page."
        action = (
            "Ask the supplier for this invoice, or remove the parked entry if it was created in error."
            if "ERP_NOT_POSTED" in reasons
            else "Ask the supplier for this invoice, or reverse the ERP entry if it was booked in error."
        )
        return text, action

    if status == r.DUPLICATE_IN_ERP:
        text = (
            f"This supplier document is booked {len(result.erp)} times in the ERP ({erp_ids}). "
            f"Paying every entry would overpay by {money(-result.components.get('duplicate_entry_in_erp', 0))}."
        )
        if "DUPLICATE_ENTRIES_DIFFER" in reasons:
            text += " The duplicate entries do not carry identical figures."
        action = "Reverse the extra entry before the payment run so the supplier is paid once."
        return text, action

    if status == r.DUPLICATE_IN_PDF:
        text = f"The same document number appears more than once in the supplier PDF, adding {money(result.components.get('duplicate_in_pdf', 0))} to the PDF total."
        return text, "Ask the supplier which copy is valid and pay only once."

    if status == r.NEEDS_REVIEW:
        parts = [head]
        parts.extend(_integrity_sentences(result))
        for code, label in (
            ("KEY_PO_MISMATCH", "The PO number differs"),
            ("KEY_DATE_MISMATCH", "The document date differs"),
            ("KEY_CN_REFERENCE_MISMATCH", "The referenced invoice differs"),
            ("KEY_INVOICE_NO_MISMATCH", "The document numbers differ"),
            ("KEY_VENDOR_MISMATCH", "The vendor name differs"),
        ):
            if code in reasons:
                parts.append(f"{label} between PDF and ERP{_key_detail(result, code)}.")
        if "OCR_UNVERIFIED" in reasons:
            parts.append("The scanned page could not be verified by arithmetic, so its figures are not trusted.")
        parts.extend(_line_sentences(result))
        if any(code.startswith("PDF_") for code in reasons) and not any(
            code.startswith("ERP_") for code in reasons
        ):
            action = "Ask the supplier for a corrected invoice; do not pay the printed total until it is resolved."
        elif any(code.startswith("ERP_") for code in reasons) and not any(
            code.startswith("PDF_") for code in reasons
        ):
            action = "Ask finance to correct the ERP entry; the supplier invoice is internally consistent."
        else:
            action = "Check the invoice against the purchase order and the supplier's copy before paying."
        return " ".join(parts), action

    parts = [head]
    parts.extend(_line_sentences(result))
    if "HEADER_AMOUNT_DIFF" in reasons:
        parts.append("The totals differ although no line differs, so the difference sits in the tax figures.")
    if "LINE_ONLY_IN_PDF" in reasons:
        action = "Confirm whether the extra invoice line (for example a delivery fee) was agreed; if yes add it to the ERP, if not dispute it."
    elif "LINE_ONLY_IN_ERP" in reasons:
        action = "Ask the supplier why the ERP line is missing from the invoice; correct whichever side is wrong."
    else:
        action = "Compare the listed lines with the purchase order and delivery receipt, then correct the ERP entry or ask for a credit note."
    return " ".join(parts), action


def _key_detail(result: r.DocumentResult, code: str) -> str:
    pdf, erp = result.pdf, result.erp[0] if result.erp else None
    if not pdf or not erp:
        return ""
    if code == "KEY_PO_MISMATCH":
        return f" (PDF {pdf.po or 'blank'}, ERP {erp.po or 'blank'})"
    if code == "KEY_DATE_MISMATCH":
        return f" (PDF {pdf.date_raw or 'blank'}, ERP {erp.date_raw or 'blank'})"
    if code == "KEY_CN_REFERENCE_MISMATCH":
        return f" (PDF {pdf.reference or 'blank'}, ERP {erp.reference or 'blank'})"
    if code == "KEY_INVOICE_NO_MISMATCH":
        return f" (PDF {pdf.number}, ERP {erp.number})"
    if code == "KEY_VENDOR_MISMATCH":
        return f" (PDF {pdf.vendor or 'blank'}, ERP {erp.vendor or 'blank'})"
    return ""
