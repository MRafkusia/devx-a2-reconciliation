from datetime import date

import pytest

from reconcile import results as r
from reconcile.match import align_lines, reconcile
from reconcile.models import CREDIT_NOTE, ErpExtraction, PdfExtraction, UnreadablePage

from .factories import make_document, make_line


def lines():
    return [make_line(1, "AAA-1", 10, 10000, 5), make_line(2, "BBB-2", 4, 25000), make_line(3, "CCC-3", 7, 3250, "2.5")]


def run(pdf_docs, erp_docs, unreadable=()):
    pdf = PdfExtraction(list(pdf_docs), [], list(unreadable), "test.pdf")
    erp = ErpExtraction(list(erp_docs), {}, "test.xlsx", {})
    return reconcile(pdf, erp)


def one(reconciliation, number=None):
    results = [item for item in reconciliation.results if number is None or item.number == number]
    assert len(results) == 1
    return results[0]


def assert_fully_explained(reconciliation):
    totals = reconciliation.totals
    assert totals.unexplained == 0
    for result in reconciliation.results:
        assert sum(result.components.values()) == result.difference, result.number


def test_identical_documents_match():
    result = one(run([make_document("pdf", "INV-1", lines())], [make_document("erp", "INV-1", lines(), entry_id="E1")]))
    assert result.status == r.MATCHED and result.difference == 0 and result.reasons == []


def test_format_differences_still_match_and_are_noted():
    erp = make_document("erp", "inv 1", lines(), entry_id="E1")
    result = one(run([make_document("pdf", "INV-1", lines())], [erp]))
    assert result.status == r.MATCHED and "FORMAT_NORMALISED" in result.reasons


def test_difference_of_one_rupiah_in_vat_is_matched_within_tolerance():
    erp = make_document("erp", "INV-1", lines(), entry_id="E1")
    erp.ppn += 1
    erp.total += 1
    result = one(run([make_document("pdf", "INV-1", lines())], [erp]))
    assert result.status == r.MATCHED_WITHIN_TOLERANCE
    assert "ROUNDING_DIFF" in result.reasons and result.difference == -1


def test_difference_above_ten_without_line_difference_is_not_rounding():
    erp = make_document("erp", "INV-1", lines(), entry_id="E1")
    erp.ppn += 11
    erp.total += 11
    result = one(run([make_document("pdf", "INV-1", lines())], [erp]))
    assert result.status != r.MATCHED_WITHIN_TOLERANCE


def test_quantity_difference_is_an_amount_mismatch_with_line_detail():
    changed = lines()
    changed[1] = make_line(2, "BBB-2", 5, 25000)
    reconciliation = run([make_document("pdf", "INV-1", changed)], [make_document("erp", "INV-1", lines(), entry_id="E1")])
    result = one(reconciliation)
    assert result.status == r.AMOUNT_MISMATCH
    assert "LINE_QTY_DIFF" in result.reasons
    assert result.line_diffs[0].amount_diff == 25000
    assert "quantity 5 on the invoice vs 4 in the ERP" in result.line_diffs[0].detail
    assert_fully_explained(reconciliation)


def test_price_and_discount_differences_are_named():
    changed = lines()
    changed[0] = make_line(1, "AAA-1", 10, 11000, 0)
    result = one(run([make_document("pdf", "INV-1", changed)], [make_document("erp", "INV-1", lines(), entry_id="E1")]))
    assert {"LINE_PRICE_DIFF", "LINE_DISCOUNT_DIFF"} <= set(result.reasons)


def test_extra_invoice_line_is_reported_as_only_in_pdf():
    extra = lines() + [make_line(4, "DLV-JKT", 1, 250000)]
    reconciliation = run([make_document("pdf", "INV-1", extra)], [make_document("erp", "INV-1", lines(), entry_id="E1")])
    result = one(reconciliation)
    assert result.status == r.AMOUNT_MISMATCH and "LINE_ONLY_IN_PDF" in result.reasons
    assert_fully_explained(reconciliation)


def test_missing_in_erp_and_missing_in_pdf():
    reconciliation = run(
        [make_document("pdf", "INV-1", lines())],
        [make_document("erp", "INV-2", lines(), entry_id="E2", po="PO-9", day=date(2026, 9, 20))],
    )
    first, second = reconciliation.results
    assert first.status == r.MISSING_IN_ERP and first.difference == first.pdf_total
    assert second.status == r.MISSING_IN_PDF and second.difference == -second.erp_total
    assert_fully_explained(reconciliation)


def test_parked_erp_entry_is_flagged():
    erp = make_document("erp", "INV-2", lines(), entry_id="E2", erp_status="Parked")
    result = one(run([], [erp]))
    assert result.status == r.MISSING_IN_PDF and "ERP_NOT_POSTED" in result.reasons


def test_duplicate_erp_entries_are_counted_once_against_the_invoice():
    pdf = make_document("pdf", "INV-1", lines())
    erp = [make_document("erp", "INV-1", lines(), entry_id="E1"), make_document("erp", "INV-1", lines(), entry_id="E9")]
    reconciliation = run([pdf], erp)
    result = one(reconciliation)
    assert result.status == r.DUPLICATE_IN_ERP
    assert result.difference == -pdf.total
    assert result.components == {"duplicate_entry_in_erp": -pdf.total}
    assert_fully_explained(reconciliation)


def test_duplicate_pdf_copies_are_flagged():
    pdf = [make_document("pdf", "INV-1", lines()), make_document("pdf", "INV-1", lines())]
    result = one(run(pdf, [make_document("erp", "INV-1", lines(), entry_id="E1")]))
    assert result.status == r.DUPLICATE_IN_PDF


def test_po_mismatch_needs_review_even_when_amounts_agree():
    result = one(run([make_document("pdf", "INV-1", lines(), po="PO-88239")],
                     [make_document("erp", "INV-1", lines(), po="PO-88293", entry_id="E1")]))
    assert result.status == r.NEEDS_REVIEW and result.reasons == ["KEY_PO_MISMATCH"]


def test_date_mismatch_needs_review():
    result = one(run([make_document("pdf", "INV-1", lines())],
                     [make_document("erp", "INV-1", lines(), entry_id="E1", day=date(2026, 9, 2))]))
    assert result.status == r.NEEDS_REVIEW and "KEY_DATE_MISMATCH" in result.reasons


def test_supplier_arithmetic_error_is_flagged_not_corrected():
    pdf = make_document("pdf", "INV-1", lines())
    pdf.subtotal += 100000
    pdf.total += 100000
    reconciliation = run([pdf], [make_document("erp", "INV-1", lines(), entry_id="E1")])
    result = one(reconciliation)
    assert result.status == r.NEEDS_REVIEW
    assert "PDF_SUBTOTAL_NOT_SUM_OF_LINES" in result.reasons
    assert pdf.subtotal == sum(line.amount for line in pdf.lines) + 100000
    assert_fully_explained(reconciliation)


def test_wrong_tax_base_on_invoice_is_flagged():
    pdf = make_document("pdf", "INV-1", lines())
    pdf.dpp = pdf.subtotal
    result = one(run([pdf], [make_document("erp", "INV-1", lines(), entry_id="E1")]))
    assert result.status == r.NEEDS_REVIEW and "PDF_DPP_NOT_11_12" in result.reasons


def test_erp_side_errors_are_flagged_too():
    erp = make_document("erp", "INV-1", lines(), entry_id="E1")
    erp.lines[0].amount += 500
    result = one(run([make_document("pdf", "INV-1", lines())], [erp]))
    assert result.status == r.NEEDS_REVIEW and "ERP_LINE_AMOUNT_WRONG" in result.reasons


def test_unverified_ocr_page_goes_to_review():
    pdf = make_document("pdf", "INV-1", lines())
    pdf.issues.append("OCR_UNVERIFIED: scanned figures failed the arithmetic checks")
    result = one(run([pdf], [make_document("erp", "INV-1", lines(), entry_id="E1")]))
    assert result.status == r.NEEDS_REVIEW and "OCR_UNVERIFIED" in result.reasons


def test_credit_notes_reconcile_with_negative_amounts():
    pdf = make_document("pdf", "CN-1", lines(), doc_type=CREDIT_NOTE)
    erp = make_document("erp", "CN-1", lines(), doc_type=CREDIT_NOTE, entry_id="E5")
    result = one(run([pdf], [erp]))
    assert result.status == r.MATCHED and result.pdf_total < 0 and result.pdf_total == result.erp_total


def test_credit_note_reference_must_agree():
    pdf = make_document("pdf", "CN-1", lines(), doc_type=CREDIT_NOTE)
    erp = make_document("erp", "CN-1", lines(), doc_type=CREDIT_NOTE, entry_id="E5", reference="INV-OTHER")
    result = one(run([pdf], [erp]))
    assert result.status == r.NEEDS_REVIEW and "KEY_CN_REFERENCE_MISMATCH" in result.reasons


def test_mistyped_document_number_is_paired_by_po_and_flagged():
    pdf = make_document("pdf", "INV-0146", lines(), po="PO-77")
    erp = make_document("erp", "INV-0164", lines(), po="PO-77", entry_id="E7")
    reconciliation = run([pdf], [erp])
    result = one(reconciliation)
    assert result.status == r.NEEDS_REVIEW and "KEY_INVOICE_NO_MISMATCH" in result.reasons
    assert len(reconciliation.results) == 1


def test_unreadable_pdf_page_becomes_a_review_row():
    reconciliation = run([], [], unreadable=[UnreadablePage(10, "scanned page and OCR is not available")])
    assert reconciliation.results[0].status == r.NEEDS_REVIEW
    assert reconciliation.results[0].reasons == ["PDF_PAGE_UNREADABLE"]


def test_repeated_items_are_paired_without_confusion():
    pdf_lines = [make_line(1, "AAA-1", 5, 1000), make_line(2, "AAA-1", 5, 1000, 10)]
    erp_lines = [make_line(1, "AAA-1", 5, 1000, 10), make_line(2, "AAA-1", 5, 1000)]
    assert align_lines(pdf_lines, erp_lines) == []


def test_batch_totals_add_up_across_mixed_results():
    changed = lines()
    changed[1] = make_line(2, "BBB-2", 9, 25000)
    pdf = [make_document("pdf", "INV-1", changed), make_document("pdf", "INV-2", lines(), po="PO-2"),
           make_document("pdf", "INV-3", lines(), po="PO-3")]
    erp = [make_document("erp", "INV-1", lines(), entry_id="E1"), make_document("erp", "INV-3", lines(), po="PO-3", entry_id="E3"),
           make_document("erp", "INV-3", lines(), po="PO-3", entry_id="E4"),
           make_document("erp", "INV-9", lines(), po="PO-9", entry_id="E9", erp_status="Parked")]
    reconciliation = run(pdf, erp)
    assert_fully_explained(reconciliation)
    assert reconciliation.totals.difference == reconciliation.totals.pdf_total - reconciliation.totals.erp_total
