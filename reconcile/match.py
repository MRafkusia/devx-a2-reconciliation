"""Match PDF documents to ERP entries, classify every document and explain every difference."""

from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from . import checks, explain, rules
from . import results as r
from .erp_load import resolve_erp_dates
from .models import Document, ErpExtraction, Line, PdfExtraction
from .normalize import normalise_reference, normalise_vendor


def _signature(line: Line) -> Tuple:
    return (line.sku.upper(), line.quantity, line.unit_price, line.discount_pct, line.amount)


def _quantity_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _sentence_case(text: str) -> str:
    return text[:1].upper() + text[1:]


def _line_label(pdf_line: Optional[Line], erp_line: Optional[Line]) -> str:
    line = pdf_line or erp_line
    return f"line {line.number} ({line.sku})"


def align_lines(pdf_lines: List[Line], erp_lines: List[Line]) -> List[r.LineDiff]:
    """Pair lines exactly first, then by line number, then by item code; report every difference."""
    remaining_pdf = list(pdf_lines)
    remaining_erp = list(erp_lines)

    for pdf_line in list(remaining_pdf):
        for erp_line in remaining_erp:
            if _signature(pdf_line) == _signature(erp_line):
                remaining_pdf.remove(pdf_line)
                remaining_erp.remove(erp_line)
                break

    pairs: List[Tuple[Line, Line]] = []
    for pdf_line in list(remaining_pdf):
        same_number = [
            line for line in remaining_erp if line.number == pdf_line.number and line.sku.upper() == pdf_line.sku.upper()
        ]
        if same_number:
            pairs.append((pdf_line, same_number[0]))
            remaining_pdf.remove(pdf_line)
            remaining_erp.remove(same_number[0])
    for pdf_line in list(remaining_pdf):
        same_sku = [line for line in remaining_erp if line.sku.upper() == pdf_line.sku.upper()]
        if same_sku:
            pairs.append((pdf_line, same_sku[0]))
            remaining_pdf.remove(pdf_line)
            remaining_erp.remove(same_sku[0])
    for pdf_line in list(remaining_pdf):
        same_number = [line for line in remaining_erp if line.number == pdf_line.number]
        if same_number:
            pairs.append((pdf_line, same_number[0]))
            remaining_pdf.remove(pdf_line)
            remaining_erp.remove(same_number[0])

    diffs: List[r.LineDiff] = []
    for pdf_line, erp_line in pairs:
        codes: List[str] = []
        phrases: List[str] = []
        if pdf_line.sku.upper() != erp_line.sku.upper():
            codes.append("LINE_SKU_DIFF")
            phrases.append(f"item code {pdf_line.sku} on the invoice vs {erp_line.sku} in the ERP")
        if pdf_line.quantity != erp_line.quantity:
            codes.append("LINE_QTY_DIFF")
            phrases.append(
                f"quantity {_quantity_text(pdf_line.quantity)} on the invoice vs {_quantity_text(erp_line.quantity)} in the ERP"
            )
        if pdf_line.unit_price != erp_line.unit_price:
            codes.append("LINE_PRICE_DIFF")
            phrases.append(
                f"unit price {pdf_line.unit_price:,} on the invoice vs {erp_line.unit_price:,} in the ERP"
            )
        if pdf_line.discount_pct != erp_line.discount_pct:
            codes.append("LINE_DISCOUNT_DIFF")
            phrases.append(
                f"discount {pdf_line.discount_pct.normalize():f}% on the invoice vs {erp_line.discount_pct.normalize():f}% in the ERP"
            )
        if not codes:
            codes.append("LINE_AMOUNT_DIFF")
            phrases.append(f"amount {pdf_line.amount:,} on the invoice vs {erp_line.amount:,} in the ERP")
        amount_diff = pdf_line.amount - erp_line.amount
        detail = f"{_sentence_case(_line_label(pdf_line, erp_line))}: {'; '.join(phrases)}, amount difference {amount_diff:+,}."
        diffs.append(r.LineDiff(codes, pdf_line, erp_line, amount_diff, detail))

    for pdf_line in remaining_pdf:
        detail = (
            f"{_sentence_case(_line_label(pdf_line, None))} ({pdf_line.description or pdf_line.sku}, "
            f"{pdf_line.amount:,}) is on the invoice but not in the ERP."
        )
        diffs.append(r.LineDiff(["LINE_ONLY_IN_PDF"], pdf_line, None, pdf_line.amount, detail))
    for erp_line in remaining_erp:
        detail = (
            f"{_sentence_case(_line_label(None, erp_line))} ({erp_line.description or erp_line.sku}, "
            f"{erp_line.amount:,}) is in the ERP but not on the invoice."
        )
        diffs.append(r.LineDiff(["LINE_ONLY_IN_ERP"], None, erp_line, -erp_line.amount, detail))

    return sorted(diffs, key=lambda diff: (diff.pdf_line or diff.erp_line).number)


def _issue_code(issue: str) -> str:
    return issue.split(":", 1)[0].strip()


def _key_reference_reasons(pdf: Document, erp: Document) -> List[str]:
    reasons: List[str] = []
    if pdf.po and erp.po and normalise_reference(pdf.po) != normalise_reference(erp.po):
        reasons.append("KEY_PO_MISMATCH")
    if pdf.is_credit_note and (pdf.reference or erp.reference):
        if normalise_reference(pdf.reference) != normalise_reference(erp.reference):
            reasons.append("KEY_CN_REFERENCE_MISMATCH")
    if pdf.date != erp.date or erp.date_ambiguous:
        reasons.append("KEY_DATE_MISMATCH")
    if pdf.vendor and erp.vendor and normalise_vendor(pdf.vendor) != normalise_vendor(erp.vendor):
        reasons.append("KEY_VENDOR_MISMATCH")
    if erp.currency.upper() != "IDR":
        reasons.append("KEY_CURRENCY_MISMATCH")
    return reasons


def _components(pdf: Document, erp: Document, line_diffs: List[r.LineDiff]) -> Dict[str, int]:
    pdf_lines = pdf.lines_total()
    erp_lines = erp.lines_total()
    pdf_subtotal = pdf.subtotal or 0
    erp_subtotal = erp.subtotal or 0
    total_difference = (pdf.total or 0) - (erp.total or 0)

    subtotal_difference = pdf_subtotal - erp_subtotal
    ppn_difference = (pdf.ppn or 0) - (erp.ppn or 0)
    expected_vat = rules.tax_breakdown(pdf_subtotal).ppn - rules.tax_breakdown(erp_subtotal).ppn

    components = {
        "line_items": sum(diff.amount_diff for diff in line_diffs),
        "pdf_subtotal_error": pdf_subtotal - pdf_lines,
        "erp_subtotal_error": -(erp_subtotal - erp_lines),
        "vat_on_subtotal_difference": expected_vat,
        "vat_rounding_or_error": ppn_difference - expected_vat,
        "total_inconsistency": total_difference - subtotal_difference - ppn_difference,
    }
    drift = (pdf_lines - erp_lines) - components["line_items"]
    components["line_items"] += drift
    return {name: value for name, value in components.items() if value}


def _analyse_group(
    key: str, pdf_docs: List[Document], erp_docs: List[Document], paired_by_reference: bool
) -> r.DocumentResult:
    pdf = pdf_docs[0] if pdf_docs else None
    erp = erp_docs[0] if erp_docs else None
    reference_doc = pdf or erp
    pdf_total = sum(doc.total or 0 for doc in pdf_docs)
    erp_total = sum(doc.total or 0 for doc in erp_docs)
    result = r.DocumentResult(
        key=key,
        number=reference_doc.number,
        doc_type=reference_doc.doc_type,
        status=r.MATCHED,
        reasons=[],
        pdf_total=pdf_total,
        erp_total=erp_total,
        difference=pdf_total - erp_total,
        pdf=pdf,
        erp=list(erp_docs),
    )
    reasons: List[str] = []

    for doc in pdf_docs[:1] + erp_docs[:1]:
        result.findings.extend(checks.check_document(doc))
        for issue in doc.issues:
            code = _issue_code(issue)
            reasons.append(code)
            result.findings.append(checks.Finding(code, checks.ERROR, issue.split(":", 1)[-1].strip()))

    if erp_docs and erp_docs[0].erp_status.lower() not in ("", "posted"):
        reasons.append("ERP_NOT_POSTED")
        result.notes.append(f"ERP status is {erp_docs[0].erp_status}")

    if pdf is None:
        result.components = {"document_missing_in_pdf": -erp_total}
        result.status = r.MISSING_IN_PDF
        result.reasons = _unique(["MISSING_IN_PDF"] + reasons + [f.code for f in checks.errors(result.findings)])
        return result

    if erp is None:
        result.components = {"document_missing_in_erp": pdf_total}
        result.status = r.MISSING_IN_ERP
        result.reasons = _unique(["MISSING_IN_ERP"] + reasons + [f.code for f in checks.errors(result.findings)])
        return result

    result.line_diffs = align_lines(pdf.lines, erp.lines)
    result.components = _components(pdf, erp, result.line_diffs)
    if len(erp_docs) > 1:
        extra = sum(doc.total or 0 for doc in erp_docs[1:])
        result.components["duplicate_entry_in_erp"] = -extra
        result.components["document_missing_in_erp"] = result.components.get("document_missing_in_erp", 0)
        result.components = {name: value for name, value in result.components.items() if value}
        first = erp_docs[0]
        if any(
            (doc.total, doc.subtotal, doc.ppn, doc.date, doc.po) != (first.total, first.subtotal, first.ppn, first.date, first.po)
            for doc in erp_docs[1:]
        ):
            reasons.append("DUPLICATE_ENTRIES_DIFFER")
    if len(pdf_docs) > 1:
        extra = sum(doc.total or 0 for doc in pdf_docs[1:])
        result.components["duplicate_in_pdf"] = extra

    key_reasons = _key_reference_reasons(pdf, erp)
    if paired_by_reference:
        key_reasons.append("KEY_INVOICE_NO_MISMATCH")
    reasons.extend(key_reasons)

    if pdf.number.strip().upper() != erp.number.strip().upper():
        result.notes.append(f"document number written as {pdf.number} (PDF) and {erp.number} (ERP)")
    for doc in (pdf, erp):
        for item in doc.normalised:
            result.notes.append(f"{doc.side.upper()}: {item}")

    line_codes = [code for diff in result.line_diffs for code in diff.codes]
    integrity_codes = [f.code for f in checks.errors(result.findings)]
    header_difference = any(
        (getattr(pdf, name) or 0) != (getattr(erp, name) or 0) for name in ("subtotal", "dpp", "ppn", "total")
    )

    if len(erp_docs) > 1:
        status = r.DUPLICATE_IN_ERP
        reasons.insert(0, "DUPLICATE_IN_ERP")
        if len(pdf_docs) > 1:
            reasons.append("DUPLICATE_IN_PDF")
    elif len(pdf_docs) > 1:
        status = r.DUPLICATE_IN_PDF
        reasons.insert(0, "DUPLICATE_IN_PDF")
    elif integrity_codes or key_reasons or any(code in ("OCR_UNVERIFIED",) for code in reasons):
        status = r.NEEDS_REVIEW
    elif line_codes or not rules.within_tolerance(result.difference):
        status = r.AMOUNT_MISMATCH
    elif header_difference:
        status = r.MATCHED_WITHIN_TOLERANCE
        reasons.append("ROUNDING_DIFF")
    else:
        status = r.MATCHED

    if status in (r.NEEDS_REVIEW, r.AMOUNT_MISMATCH, r.DUPLICATE_IN_ERP, r.DUPLICATE_IN_PDF):
        reasons.extend(integrity_codes)
        reasons.extend(line_codes)
        if not line_codes and not integrity_codes and result.difference and status == r.AMOUNT_MISMATCH:
            reasons.append("HEADER_AMOUNT_DIFF")
        if result.difference and not line_codes and not integrity_codes and status == r.NEEDS_REVIEW:
            reasons.append("HEADER_AMOUNT_DIFF")
    if status == r.MATCHED_WITHIN_TOLERANCE:
        reasons.extend(f.code for f in result.findings if f.severity == checks.ROUNDING)

    if status == r.MATCHED and result.notes:
        reasons.append("FORMAT_NORMALISED")
    if status == r.MATCHED_WITHIN_TOLERANCE and result.notes:
        reasons.append("FORMAT_NORMALISED")

    result.status = status
    result.reasons = _unique(reasons)
    return result


def _unique(items: List[str]) -> List[str]:
    return list(OrderedDict.fromkeys(item for item in items if item))


def _group(documents: List[Document]) -> "OrderedDict[str, List[Document]]":
    groups: "OrderedDict[str, List[Document]]" = OrderedDict()
    for document in documents:
        groups.setdefault(document.key, []).append(document)
    return groups


def _secondary_pairs(
    pdf_groups: "OrderedDict[str, List[Document]]", erp_groups: "OrderedDict[str, List[Document]]"
) -> Dict[str, str]:
    """Pair unmatched PDF documents with unmatched ERP entries that share PO and date or total."""
    pairs: Dict[str, str] = {}
    unmatched_erp = [key for key in erp_groups if key not in pdf_groups]
    for pdf_key, pdf_docs in pdf_groups.items():
        if pdf_key in erp_groups:
            continue
        pdf = pdf_docs[0]
        candidates = []
        for erp_key in unmatched_erp:
            if erp_key in pairs.values():
                continue
            erp = erp_groups[erp_key][0]
            if erp.doc_type != pdf.doc_type:
                continue
            anchor = (
                pdf.reference and normalise_reference(pdf.reference) == normalise_reference(erp.reference)
                if pdf.is_credit_note
                else pdf.po and normalise_reference(pdf.po) == normalise_reference(erp.po)
            )
            if anchor and (pdf.total == erp.total or pdf.date == erp.date):
                candidates.append(erp_key)
        if len(candidates) == 1:
            pairs[pdf_key] = candidates[0]
    return pairs


def _control_totals(results: List[r.DocumentResult], pdf_docs: List[Document], erp_docs: List[Document]) -> r.ControlTotals:
    pdf_total = sum(doc.total or 0 for doc in pdf_docs)
    erp_total = sum(doc.total or 0 for doc in erp_docs)
    components: Dict[str, int] = {}
    by_status: Dict[str, Dict[str, int]] = {}
    for result in results:
        for name, value in result.components.items():
            components[name] = components.get(name, 0) + value
        bucket = by_status.setdefault(result.status, {"documents": 0, "difference": 0})
        bucket["documents"] += 1
        bucket["difference"] += result.difference
    explained = sum(components.values())
    return r.ControlTotals(
        pdf_documents=len(pdf_docs),
        erp_entries=len(erp_docs),
        pdf_total=pdf_total,
        erp_total=erp_total,
        difference=pdf_total - erp_total,
        components={name: value for name, value in components.items() if value},
        explained=explained,
        unexplained=(pdf_total - erp_total) - explained,
        by_status=by_status,
        invoices_pdf=sum(1 for doc in pdf_docs if not doc.is_credit_note),
        invoices_erp=sum(1 for doc in erp_docs if not doc.is_credit_note),
        credit_notes_pdf=sum(1 for doc in pdf_docs if doc.is_credit_note),
        credit_notes_erp=sum(1 for doc in erp_docs if doc.is_credit_note),
    )


def reconcile(pdf: PdfExtraction, erp: ErpExtraction) -> r.Reconciliation:
    pdf_groups = _group(pdf.documents)
    erp_groups = _group(erp.documents)
    resolve_erp_dates(erp.documents, {key: docs[0] for key, docs in pdf_groups.items()})
    secondary = _secondary_pairs(pdf_groups, erp_groups)
    secondary_erp_keys = set(secondary.values())

    results: List[r.DocumentResult] = []
    for key, pdf_docs in pdf_groups.items():
        if key in erp_groups:
            results.append(_analyse_group(key, pdf_docs, erp_groups[key], False))
        elif key in secondary:
            erp_docs = erp_groups[secondary[key]]
            resolve_erp_dates(erp_docs, {erp_docs[0].key: pdf_docs[0]})
            results.append(_analyse_group(key, pdf_docs, erp_docs, True))
        else:
            results.append(_analyse_group(key, pdf_docs, [], False))
    for key, erp_docs in erp_groups.items():
        if key in pdf_groups or key in secondary_erp_keys:
            continue
        results.append(_analyse_group(key, [], erp_docs, False))

    unreadable = [f"page {page.page}: {page.reason}" for page in pdf.unreadable]
    for result in results:
        if result.status == r.MISSING_IN_PDF and pdf.unreadable:
            result.reasons = _unique(result.reasons + ["PDF_PAGE_UNREADABLE"])
    for result in results:
        result.explanation, result.suggested_action = explain.describe(result)

    for page in pdf.unreadable:
        unreadable_result = r.DocumentResult(
            key=f"UNREADABLE-P{page.page}",
            number=f"(unreadable page {page.page})",
            doc_type="UNKNOWN",
            status=r.NEEDS_REVIEW,
            reasons=["PDF_PAGE_UNREADABLE"],
            pdf_total=0,
            erp_total=0,
            difference=0,
            explanation=f"PDF page {page.page} could not be read: {page.reason}. Figures on it are not in this reconciliation.",
            suggested_action="Read the page manually or install OCR support and run again.",
        )
        results.append(unreadable_result)

    totals = _control_totals(results, pdf.documents, erp.documents)
    erp_info = erp.info.get("Exported at", "")
    pages = [
        {"page": str(page.page), "kind": page.kind, "method": page.method, "detail": page.detail}
        for page in pdf.pages
    ]
    return r.Reconciliation(
        results=results,
        totals=totals,
        pdf_file=pdf.file_name,
        erp_file=erp.file_name,
        unreadable_pages=unreadable,
        pages=pages,
        erp_sheets=erp.sheets,
        erp_exported_at=erp_info,
    )
