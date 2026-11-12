from pathlib import Path

import pytest

from reconcile import pdf_extract
from reconcile import results as r
from reconcile.models import CREDIT_NOTE
from reconcile.pdf_extract import PRIMA_KERTAS, extract_pdf, ocr_available, parse_page_text
from reconcile.pipeline import run

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


CREDIT_NOTE_TEXT = """PT PRIMA KERTAS INDONESIA NOTA KREDIT / CREDIT NOTE
Kepada / Bill to: No. Nota Kredit / CN No. PKI/CN/2026/10/0013
Tanggal / Date 21-10-2026
Referensi / Reference PKI/INV/2026/09/0141
# Kode / SKU Uraian / Description Qty Sat. Unit Price Disc % Amount (Rp)
1 MAP-PLS-FC Map plastik folio, isi 12 10 pak 36.000 360.000
2 STP-NO10 Isi staples no. 10, box 25 48 box 3.500 168.000
Subtotal 528.000
DPP Nilai Lain (11/12) 484.000
PPN 12% 58.080
TOTAL (Rp) 586.080
"""

INVOICE_HEAD = """PT PRIMA KERTAS INDONESIA FAKTUR / INVOICE{suffix}
Kepada / Bill to: No. Faktur / Invoice No. PKI/INV/2026/10/0215
Tanggal / Date 20-10-2026
No. PO PO-88315
# Kode / SKU Uraian / Description Qty Sat. Unit Price Disc % Amount (Rp)
"""
ROWS_FIRST = """1 MAP-PLS-FC Map plastik folio, isi 12 11 pak 36.000 396.000
2 STP-NO10 Isi staples no. 10, box 25 20 box 3.500 70.000
"""
ROWS_SECOND = """3 KTR-L500 Cutter Besar L-500 Joyko 4 pcs 12.000 48.000
4 GNT-ST-8 Gunting Kantor Stainless Steel 3 pcs 14.000 42.000
"""
TOTALS = """Subtotal 556.000
DPP Nilai Lain (11/12) 509.667
PPN 12% 61.160
TOTAL (Rp) 617.160
"""
FIRST_PAGE = INVOICE_HEAD.format(suffix="") + ROWS_FIRST + "(Bersambung ke halaman 2 / Continued on page 2)\n"
CONTINUATION_PAGE = INVOICE_HEAD.format(suffix=" (Lanjutan)") + ROWS_SECOND + TOTALS
COMPLETE_PAGE = INVOICE_HEAD.format(suffix="") + ROWS_FIRST + "Subtotal 466.000\nDPP Nilai Lain (11/12) 427.167\nPPN 12% 51.260\nTOTAL (Rp) 478.427\n"


class StubPage:
    def __init__(self, text: str, scanned: bool) -> None:
        self.text = text
        self.images = [object()] if scanned else []

    def extract_text(self) -> str:
        return "" if self.images else self.text


class StubPdf:
    def __init__(self, pages) -> None:
        self.pages = pages

    def __enter__(self) -> "StubPdf":
        return self

    def __exit__(self, *exc) -> None:
        return None


def extract_stub(monkeypatch, texts, scanned):
    pdf = StubPdf([StubPage(text, scanned) for text in texts])
    monkeypatch.setattr(pdf_extract.pdfplumber, "open", lambda path: pdf)
    return extract_pdf("stub.pdf", ocr_func=lambda page, resolution, psm: page.text)


def test_credit_note_with_a_cn_number_label_is_read():
    parse = parse_page_text(PRIMA_KERTAS, 16, CREDIT_NOTE_TEXT)
    assert parse.header
    assert parse.number == "PKI/CN/2026/10/0013"
    assert parse.doc_type == CREDIT_NOTE
    assert parse.reference == "PKI/INV/2026/09/0141"
    assert [line.amount for line in parse.lines] == [360000, 168000]
    assert (parse.subtotal, parse.dpp, parse.ppn, parse.total) == (528000, 484000, 58080, 586080)


@pytest.mark.parametrize("label", ["Credit Note No.", "CN No.", "Invoice No."])
def test_every_document_number_label_is_accepted(label):
    text = CREDIT_NOTE_TEXT.replace("Nota Kredit / CN No.", label)
    assert parse_page_text(PRIMA_KERTAS, 1, text).number == "PKI/CN/2026/10/0013"


@pytest.mark.parametrize("scanned", [False, True])
def test_continuation_page_with_a_repeated_header_is_merged(monkeypatch, scanned):
    extraction = extract_stub(monkeypatch, [FIRST_PAGE, CONTINUATION_PAGE], scanned)
    assert [doc.number for doc in extraction.documents] == ["PKI/INV/2026/10/0215"]
    document = extraction.documents[0]
    assert document.pages == [1, 2]
    assert [line.number for line in document.lines] == [1, 2, 3, 4]
    assert document.total == 617160
    assert not any(issue.startswith(("PDF_ROW_GAP", "PDF_INCOMPLETE_DOCUMENT")) for issue in document.issues)


@pytest.mark.parametrize("scanned", [False, True])
def test_same_number_after_the_totals_still_starts_a_new_document(monkeypatch, scanned):
    extraction = extract_stub(monkeypatch, [COMPLETE_PAGE, COMPLETE_PAGE], scanned)
    assert [doc.number for doc in extraction.documents] == ["PKI/INV/2026/10/0215"] * 2
    assert [doc.pages for doc in extraction.documents] == [[1], [2]]


OCT_DIR = Path(
    "/Users/kusuma/Library/CloudStorage/GoogleDrive-rafikusuma35@gmail.com/My Drive/"
    "03 Career & Work/Work Apply/Data Testing - Invoice Reconciliation Oct 2026"
)
OCT_PDF = OCT_DIR / "Supplier_Invoices_PT_Prima_Kertas_Oct2026.pdf"
OCT_ERP = OCT_DIR / "ERP_AP_Export_Oct2026.xlsx"


@pytest.mark.skipif(
    not (OCT_PDF.exists() and OCT_ERP.exists()) or not ocr_available(),
    reason="October dummy dataset or tesseract is not available",
)
def test_october_dummy_dataset_fixed_documents(tmp_path):
    reconciliation, _, _ = run(str(OCT_PDF), str(OCT_ERP), str(tmp_path))
    by_suffix = {result.number[-12:]: result for result in reconciliation.results}
    assert by_suffix["2026/10/0215"].status == r.MATCHED
    assert by_suffix["2026/10/0013"].status == r.MATCHED
    assert by_suffix["2026/10/0014"].status == r.NEEDS_REVIEW
    assert "KEY_CN_REFERENCE_MISMATCH" in by_suffix["2026/10/0014"].reasons
    assert by_suffix["2026/10/0226"].status == r.NEEDS_REVIEW
    assert reconciliation.totals.unexplained == 0
