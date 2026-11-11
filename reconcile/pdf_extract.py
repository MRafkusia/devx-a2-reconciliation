"""Extract invoices and credit notes from a supplier PDF.

Text pages are read from the PDF text layer. Pages that are scans are read with OCR and
accepted only when the recovered figures pass the arithmetic checks of R1-R4; otherwise the
page is kept but marked unverified so the matcher routes it to review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import pdfplumber

from . import checks
from .models import (
    CREDIT_NOTE,
    INVOICE,
    Document,
    Line,
    PageLog,
    PdfExtraction,
    UnreadablePage,
)
from .normalize import (
    NormalisationError,
    clean_unit,
    normalise_key,
    parse_date,
    parse_decimal,
    parse_idr,
)

OCR_ATTEMPTS: Tuple[Tuple[int, int], ...] = ((300, 6), (300, 4), (400, 6), (400, 4), (200, 6))


@dataclass(frozen=True)
class SupplierLayout:
    """Label patterns of one supplier's invoice layout."""

    name: str
    detect: re.Pattern
    document_number: re.Pattern
    date: re.Pattern
    po: re.Pattern
    reference: re.Pattern
    credit_note_marker: re.Pattern
    vendor: re.Pattern
    subtotal_label: re.Pattern
    dpp_label: re.Pattern
    ppn_label: re.Pattern
    total_label: re.Pattern
    row_start: re.Pattern


PRIMA_KERTAS = SupplierLayout(
    name="prima-kertas",
    detect=re.compile(r"Invoice\s*No|Faktur|Subtotal", re.I),
    document_number=re.compile(r"Invoice\s*No\.?\s*[_\W]*([A-Z0-9][A-Z0-9/\-.]+)", re.I),
    date=re.compile(r"Tanggal\s*/\s*Date\s+(\d{1,2}[-/.]\d{1,2}[-/.]\d{4})", re.I),
    po=re.compile(r"No\.\s*PO\s+([A-Z0-9\-]+)", re.I),
    reference=re.compile(r"Referensi\s*/\s*Reference\s+([A-Z0-9/\-.]+)", re.I),
    credit_note_marker=re.compile(r"NOTA\s+KREDIT|CREDIT\s+NOTE", re.I),
    vendor=re.compile(r"^\s*(PT\.?\s+[A-Z][A-Z .&]+?)\s*(?:FAKTUR|NOTA|$)", re.M),
    subtotal_label=re.compile(r"^\s*Subtotal\b", re.I),
    dpp_label=re.compile(r"^\s*DPP\b", re.I),
    ppn_label=re.compile(r"^\s*PPN\b", re.I),
    total_label=re.compile(r"^\s*TOTAL\b", re.I),
    row_start=re.compile(r"^\s*(\d{1,3})\s+([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)\s*(.*)$"),
)

LAYOUTS: Tuple[SupplierLayout, ...] = (PRIMA_KERTAS,)

AMOUNT_TOKEN = re.compile(r"^[\d.,]+$")
UNIT_TOKEN = re.compile(r"^[^\d\s]{2,}$")


@dataclass
class PageParse:
    page: int
    text: str
    header: bool
    doc_type: str = INVOICE
    number: str = ""
    date_raw: str = ""
    po: str = ""
    reference: str = ""
    vendor: str = ""
    lines: List[Line] = field(default_factory=list)
    unparsed_rows: List[str] = field(default_factory=list)
    subtotal: Optional[int] = None
    dpp: Optional[int] = None
    ppn: Optional[int] = None
    total: Optional[int] = None
    ocr: bool = False

    @property
    def has_totals(self) -> bool:
        return self.total is not None

    @property
    def has_content(self) -> bool:
        return bool(self.lines) or self.has_totals


def detect_layout(text: str) -> Optional[SupplierLayout]:
    for layout in LAYOUTS:
        if layout.detect.search(text):
            return layout
    return None


def _last_amount(line: str) -> Optional[int]:
    tokens = line.split()
    if not tokens or not AMOUNT_TOKEN.match(tokens[-1]):
        return None
    try:
        return parse_idr(tokens[-1])
    except NormalisationError:
        return None


def _parse_row(layout: SupplierLayout, page: int, text_line: str) -> Tuple[Optional[Line], bool]:
    """Return (line, looked_like_row)."""
    match = layout.row_start.match(text_line)
    if not match:
        return None, False
    number = int(match.group(1))
    sku = match.group(2)
    tokens = text_line.split()
    if len(tokens) < 6 or not AMOUNT_TOKEN.match(tokens[-1]):
        return None, True

    try:
        amount = parse_idr(tokens[-1])
        third_from_end_is_unit = bool(UNIT_TOKEN.match(tokens[-3])) and not AMOUNT_TOKEN.match(tokens[-3])
        if third_from_end_is_unit:
            discount = Decimal(0)
            price = parse_idr(tokens[-2])
            unit = tokens[-3]
            quantity = parse_decimal(tokens[-4])
            description_tokens = tokens[2:-4]
        else:
            discount = parse_decimal(tokens[-2])
            price = parse_idr(tokens[-3])
            unit = tokens[-4]
            quantity = parse_decimal(tokens[-5])
            description_tokens = tokens[2:-5]
    except NormalisationError:
        return None, True

    if None in (amount, price, quantity, discount) or not clean_unit(unit):
        return None, True
    return (
        Line(
            number=number,
            sku=sku,
            description=" ".join(description_tokens),
            quantity=quantity,
            unit=clean_unit(unit),
            unit_price=price,
            discount_pct=discount,
            amount=amount,
            source=f"p{page} row {number}",
            raw=text_line.strip(),
        ),
        True,
    )


def parse_page_text(layout: SupplierLayout, page: int, text: str, ocr: bool = False) -> PageParse:
    number_match = layout.document_number.search(text)
    parse = PageParse(page=page, text=text, header=bool(number_match), ocr=ocr)
    if number_match:
        parse.number = number_match.group(1).strip("._")
        date_match = layout.date.search(text)
        parse.date_raw = date_match.group(1) if date_match else ""
        po_match = layout.po.search(text)
        parse.po = po_match.group(1) if po_match else ""
        reference_match = layout.reference.search(text)
        parse.reference = reference_match.group(1) if reference_match else ""
        vendor_match = layout.vendor.search(text)
        parse.vendor = re.sub(r"\s+", " ", vendor_match.group(1)).strip() if vendor_match else ""
        parse.doc_type = CREDIT_NOTE if layout.credit_note_marker.search(text) else INVOICE

    for text_line in text.splitlines():
        line, looked_like_row = _parse_row(layout, page, text_line)
        if line:
            parse.lines.append(line)
        elif looked_like_row:
            parse.unparsed_rows.append(text_line.strip())
            continue
        if layout.subtotal_label.match(text_line):
            parse.subtotal = _last_amount(text_line)
        elif layout.dpp_label.match(text_line):
            parse.dpp = _last_amount(text_line)
        elif layout.ppn_label.match(text_line):
            parse.ppn = _last_amount(text_line)
        elif layout.total_label.match(text_line):
            parse.total = _last_amount(text_line)
    return parse


def _document_from_parse(parse: PageParse, file_name: str) -> Document:
    document = Document(
        side="pdf",
        doc_type=parse.doc_type,
        number=parse.number,
        key=normalise_key(parse.number),
        date_raw=parse.date_raw,
        po=parse.po,
        reference=parse.reference,
        vendor=parse.vendor,
        pages=[parse.page],
        location=file_name,
        ocr_used=parse.ocr,
    )
    document.date = parse_date(parse.date_raw).value
    document.sources = {
        field_name: f"p{parse.page}"
        for field_name in ("number", "date", "po", "reference", "vendor")
    }
    return document


def _apply_sign(document: Document) -> None:
    if not document.is_credit_note:
        return
    for line in document.lines:
        line.quantity = abs(line.quantity)
        line.amount = -abs(line.amount)
    for name in ("subtotal", "dpp", "ppn", "total"):
        value = getattr(document, name)
        if value is not None:
            setattr(document, name, -abs(value))


def _absorb(document: Document, parse: PageParse) -> None:
    document.lines.extend(parse.lines)
    for name in ("subtotal", "dpp", "ppn", "total"):
        value = getattr(parse, name)
        if value is not None:
            setattr(document, name, value)
            document.sources[name] = f"p{parse.page}"
    for row in parse.unparsed_rows:
        document.issues.append(f"PDF_ROW_UNPARSED: p{parse.page}: {row}")
    if parse.ocr:
        document.ocr_used = True
    if parse.page not in document.pages:
        document.pages.append(parse.page)


def _row_numbers_consistent(document: Document) -> bool:
    numbers = [line.number for line in document.lines]
    return numbers == list(range(1, len(numbers) + 1))


def _ocr_candidates(page: "pdfplumber.page.Page", ocr_func: Callable[[object, int, int], str]):
    for resolution, psm in OCR_ATTEMPTS:
        yield resolution, psm, ocr_func(page, resolution, psm)


def default_ocr(page, resolution: int, psm: int) -> str:
    import pytesseract

    image = page.to_image(resolution=resolution).original
    return pytesseract.image_to_string(image, config=f"--psm {psm}")


def ocr_available() -> bool:
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _verified(layout: SupplierLayout, parse: PageParse) -> bool:
    if not parse.header or not parse.lines or not parse.has_totals or parse.unparsed_rows:
        return False
    document = _document_from_parse(parse, "")
    document.lines = list(parse.lines)
    for name in ("subtotal", "dpp", "ppn", "total"):
        setattr(document, name, getattr(parse, name))
    _apply_sign(document)
    return not checks.errors(checks.check_document(document)) and _row_numbers_consistent(document)


def _best_ocr(layout: SupplierLayout, page, page_number: int, ocr_func) -> Tuple[Optional[PageParse], bool, str]:
    best: Optional[PageParse] = None
    best_score = -1
    for resolution, psm, text in _ocr_candidates(page, ocr_func):
        parse = parse_page_text(layout, page_number, text, ocr=True)
        if _verified(layout, parse):
            return parse, True, f"ocr {resolution}dpi psm{psm}"
        score = len(parse.lines) + (2 if parse.has_totals else 0) + (2 if parse.header else 0)
        score -= len(parse.unparsed_rows)
        if score > best_score:
            best, best_score = parse, score
    return best, False, "ocr unverified"


def extract_pdf(
    path: str,
    use_ocr: bool = True,
    ocr_func: Optional[Callable[[object, int, int], str]] = None,
) -> PdfExtraction:
    file_name = Path(path).name
    documents: List[Document] = []
    pages: List[PageLog] = []
    unreadable: List[UnreadablePage] = []
    current: Optional[Document] = None
    ocr_func = ocr_func or default_ocr
    ocr_ready = use_ocr and (ocr_func is not default_ocr or ocr_available())

    def finish() -> None:
        nonlocal current
        if current is None:
            return
        if current.total is None:
            current.issues.append("PDF_INCOMPLETE_DOCUMENT: totals block not found")
        if current.lines and not _row_numbers_consistent(current):
            current.issues.append("PDF_ROW_GAP: line numbers are not consecutive from 1")
        _apply_sign(current)
        documents.append(current)
        current = None

    with pdfplumber.open(path) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            layout = detect_layout(text)
            parse = parse_page_text(layout, index, text) if layout else None
            method = "text layer"

            if parse is None or not (parse.header or parse.has_content):
                if page.images and not _has_document_markers(text):
                    if not ocr_ready:
                        reason = "scanned page and OCR is not available"
                        unreadable.append(UnreadablePage(index, reason))
                        pages.append(PageLog(index, "scan", "skipped", reason))
                        continue
                    layout = layout or LAYOUTS[0]
                    parse, verified, method = _best_ocr(layout, page, index, ocr_func)
                    if parse is None or not (parse.header or parse.has_content):
                        reason = "scanned page could not be read by OCR"
                        unreadable.append(UnreadablePage(index, reason))
                        pages.append(PageLog(index, "scan", "ocr failed", reason))
                        continue
                    kind = "scan"
                    detail = "figures verified by R1-R4 arithmetic" if verified else "figures NOT verified"
                    pages.append(PageLog(index, kind, method, detail))
                    if parse.header:
                        finish()
                        current = _document_from_parse(parse, file_name)
                    elif current is None:
                        unreadable.append(UnreadablePage(index, "continuation page without a document header"))
                        continue
                    _absorb(current, parse)
                    if not verified:
                        current.ocr_verified = False
                        current.issues.append("OCR_UNVERIFIED: scanned figures failed the arithmetic checks")
                    continue
                pages.append(PageLog(index, "other", "ignored", "no document content found"))
                continue

            kind = "text"
            if parse.header:
                finish()
                current = _document_from_parse(parse, file_name)
            elif current is None:
                unreadable.append(UnreadablePage(index, "continuation page without a document header"))
                continue
            _absorb(current, parse)
            pages.append(PageLog(index, kind, method, f"{len(parse.lines)} lines"))
        finish()

    return PdfExtraction(documents=_ordered(documents), pages=pages, unreadable=unreadable, file_name=file_name)


def _has_document_markers(text: str) -> bool:
    return bool(re.search(r"Invoice\s*No|Subtotal|TOTAL\s*\(", text, re.I))


def _ordered(documents: List[Document]) -> List[Document]:
    for position, document in enumerate(documents):
        document.order = position
    return documents
