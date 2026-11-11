import pytest

from reconcile.pdf_extract import extract_pdf, ocr_available

SCAN_TEXT = """PT PRIMA KERTAS INDONESIA FAKTUR / INVOICE
Kepada / Bill to: No. Faktur / Invoice No. PKI/INV/2026/09/0150
Tanggal / Date 19-09-2026
No. PO PO-88227
# Kode / SKU Uraian / Description Qty Sat. Unit Price Disc % Amount (Rp)
1 MAP-PLS-FC Map plastik folio, isi 12 11 pak 36.000 396.000
2 STP-NO10 Isi staples no. 10, box 25 box 3.250 5 77.188
Subtotal 473.188
DPP Nilai Lain (11/12) 433.756
PPN 12% 52.051
TOTAL (Rp) 525.239
"""


def test_every_document_in_the_sample_is_found(sample_pdf):
    extraction = extract_pdf(sample_pdf, use_ocr=ocr_available())
    numbers = [doc.number for doc in extraction.documents]
    assert len(numbers) == 15
    assert numbers[0] == "PKI/INV/2026/09/0141"
    assert numbers[-1] == "PKI/CN/2026/09/0012"


def test_invoice_header_and_totals_are_read(sample_pdf):
    extraction = extract_pdf(sample_pdf, use_ocr=False)
    first = extraction.documents[0]
    assert (first.po, first.subtotal, first.dpp, first.ppn, first.total) == ("PO-88200", 2994303, 2744778, 329373, 3323676)
    assert [line.amount for line in first.lines] == [1238490, 293313, 1462500]
    assert first.lines[0].discount_pct == 10 and first.lines[2].discount_pct == 0


def test_decimal_comma_discounts_are_read(sample_pdf):
    extraction = extract_pdf(sample_pdf, use_ocr=False)
    sixth = next(doc for doc in extraction.documents if doc.number.endswith("0146"))
    wrapped_description_line = next(line for line in sixth.lines if line.sku == "KW-A4-80-RM")
    assert str(wrapped_description_line.discount_pct) == "2.5"
    assert wrapped_description_line.amount == 8619000


def test_invoice_spanning_two_pages_is_one_document(sample_pdf):
    extraction = extract_pdf(sample_pdf, use_ocr=False)
    long_invoice = next(doc for doc in extraction.documents if doc.number.endswith("0153"))
    assert long_invoice.pages == [13, 14]
    assert len(long_invoice.lines) == 34
    assert long_invoice.total == 101656444


def test_credit_note_is_negative_and_keeps_its_reference(sample_pdf):
    extraction = extract_pdf(sample_pdf, use_ocr=False)
    note = extraction.documents[-1]
    assert note.is_credit_note
    assert (note.subtotal, note.total) == (-876000, -972360)
    assert note.reference == "PKI/INV/2026/08/0131"
    assert all(line.amount < 0 and line.quantity > 0 for line in note.lines)


def test_scanned_page_is_reported_unreadable_when_ocr_is_off(sample_pdf):
    extraction = extract_pdf(sample_pdf, use_ocr=False)
    assert [page.page for page in extraction.unreadable] == [10]
    assert len(extraction.documents) == 14


@pytest.mark.skipif(not ocr_available(), reason="tesseract is not installed")
def test_scanned_page_is_read_by_ocr_and_verified(sample_pdf):
    extraction = extract_pdf(sample_pdf)
    scanned = next(doc for doc in extraction.documents if doc.number.endswith("0150"))
    assert scanned.ocr_used and scanned.ocr_verified
    assert (scanned.subtotal, scanned.total) == (19456428, 21596635)
    assert len(scanned.lines) == 5


def test_ocr_output_that_fails_the_arithmetic_is_not_trusted(sample_pdf):
    broken = SCAN_TEXT.replace("473.188", "473.881")
    extraction = extract_pdf(sample_pdf, ocr_func=lambda page, resolution, psm: broken)
    scanned = next(doc for doc in extraction.documents if doc.number.endswith("0150"))
    assert scanned.ocr_used and not scanned.ocr_verified
    assert any(issue.startswith("OCR_UNVERIFIED") for issue in scanned.issues)


def test_ocr_output_that_passes_the_arithmetic_is_verified(sample_pdf):
    extraction = extract_pdf(sample_pdf, ocr_func=lambda page, resolution, psm: SCAN_TEXT)
    scanned = next(doc for doc in extraction.documents if doc.number.endswith("0150"))
    assert scanned.ocr_verified and not scanned.issues
