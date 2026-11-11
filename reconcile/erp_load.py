"""Load an ERP AP export workbook into documents.

Sheets and columns are recognised by their headers, not by sheet name or column order, so a
re-exported batch with a different layout still loads.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import openpyxl

from .models import CREDIT_NOTE, INVOICE, Document, ErpExtraction, Line
from .normalize import (
    NormalisationError,
    normalise_key,
    parse_date,
    parse_decimal,
    parse_idr,
)

HEADER_ALIASES: Dict[str, Tuple[str, ...]] = {
    "entry_id": ("entry id", "entry no", "entry"),
    "vendor": ("vendor", "supplier", "vendor name"),
    "number": ("vendor inv. no", "vendor inv no", "vendor invoice no", "invoice no", "vendor cn no", "vendor credit note no", "credit note no"),
    "date": ("doc date", "document date", "invoice date", "date"),
    "po": ("po no", "po", "po number"),
    "reference": ("original invoice", "original inv. no", "reference", "ref invoice"),
    "currency": ("curr", "currency"),
    "subtotal": ("subtotal", "sub total", "net amount"),
    "dpp": ("dpp", "tax base"),
    "ppn": ("ppn", "vat", "tax"),
    "total": ("grand total", "total", "gross amount"),
    "status": ("doc status", "status"),
    "posted_by": ("posted by", "created by"),
    "line": ("line", "line no", "line number"),
    "item_code": ("item code", "sku", "item"),
    "description": ("item description", "description"),
    "quantity": ("qty", "quantity"),
    "unit": ("uom", "unit"),
    "unit_price": ("unit price", "price"),
    "discount": ("disc %", "disc", "discount %", "discount"),
    "line_amount": ("line amount", "amount"),
}

INVOICE_NUMBER_HEADERS = {"vendor inv. no", "vendor inv no", "vendor invoice no", "invoice no"}
CREDIT_NUMBER_HEADERS = {"vendor cn no", "vendor credit note no", "credit note no"}


def _canonical(header: Any) -> Optional[str]:
    text = str(header or "").strip().lower()
    for canonical, aliases in HEADER_ALIASES.items():
        if text in aliases:
            return canonical
    return None


def _column_map(header_row: Tuple[Any, ...]) -> Tuple[Dict[str, int], str]:
    mapping: Dict[str, int] = {}
    number_header = ""
    for index, header in enumerate(header_row):
        canonical = _canonical(header)
        if canonical and canonical not in mapping:
            mapping[canonical] = index
            if canonical == "number":
                number_header = str(header).strip().lower()
    return mapping, number_header


def _classify(mapping: Dict[str, int], number_header: str) -> str:
    if {"line", "item_code", "quantity"} <= mapping.keys():
        return "lines"
    if "number" in mapping and "total" in mapping:
        return "credit_notes" if number_header in CREDIT_NUMBER_HEADERS else "invoices"
    return "ignored"


def _cell(row: Tuple[Any, ...], mapping: Dict[str, int], name: str) -> Any:
    index = mapping.get(name)
    return row[index] if index is not None and index < len(row) else None


def _column_letter(mapping: Dict[str, int], name: str) -> str:
    return openpyxl.utils.get_column_letter(mapping[name] + 1) if name in mapping else ""


def _amount(value: Any, label: str, document: Document) -> Optional[int]:
    try:
        parsed = parse_idr(value)
    except NormalisationError:
        document.issues.append(f"ERP_UNREADABLE_FIELD: {label} = {value!r}")
        return None
    if isinstance(value, str) and value.strip() and parsed is not None:
        document.normalised.append(f"{label} stored as text")
    return parsed


def _read_documents(
    sheet_name: str, rows: List[Tuple[int, Tuple[Any, ...]]], mapping: Dict[str, int], doc_type: str, file_name: str
) -> List[Document]:
    documents: List[Document] = []
    for excel_row, row in rows:
        if all(value in (None, "") for value in row):
            continue
        number = str(_cell(row, mapping, "number") or "").strip()
        document = Document(
            side="erp",
            doc_type=doc_type,
            number=number,
            key=normalise_key(number),
            vendor=str(_cell(row, mapping, "vendor") or "").strip(),
            po=str(_cell(row, mapping, "po") or "").strip() if doc_type == INVOICE else "",
            reference=str(_cell(row, mapping, "reference") or "").strip() if doc_type == CREDIT_NOTE else "",
            currency=str(_cell(row, mapping, "currency") or "IDR").strip() or "IDR",
            entry_id=str(_cell(row, mapping, "entry_id") or "").strip(),
            erp_status=str(_cell(row, mapping, "status") or "").strip(),
            posted_by=str(_cell(row, mapping, "posted_by") or "").strip(),
            location=f"{file_name} / {sheet_name}",
        )
        raw_date = _cell(row, mapping, "date")
        document.date_raw = raw_date.strftime("%Y-%m-%d") if isinstance(raw_date, datetime) else str(raw_date or "")
        if isinstance(raw_date, str):
            document.normalised.append("date stored as text")
        document.date = parse_date(raw_date).value if not isinstance(raw_date, str) else None
        document.date_ambiguous = False
        document.subtotal = _amount(_cell(row, mapping, "subtotal"), "subtotal", document)
        document.dpp = _amount(_cell(row, mapping, "dpp"), "DPP", document)
        document.ppn = _amount(_cell(row, mapping, "ppn"), "PPN", document)
        document.total = _amount(_cell(row, mapping, "total"), "total", document)
        for name in ("number", "date", "po", "reference", "subtotal", "dpp", "ppn", "total", "vendor"):
            letter = _column_letter(mapping, name if name != "number" else "number")
            if letter:
                document.sources[name] = f"{sheet_name}!{letter}{excel_row}"
        document.sources["entry"] = f"{sheet_name}!row {excel_row}"
        document.pages = []
        documents.append(document)
    return documents


def _read_lines(
    sheet_name: str, rows: List[Tuple[int, Tuple[Any, ...]]], mapping: Dict[str, int]
) -> Dict[str, List[Line]]:
    by_entry: Dict[str, List[Line]] = defaultdict(list)
    for excel_row, row in rows:
        if all(value in (None, "") for value in row):
            continue
        entry_id = str(_cell(row, mapping, "entry_id") or "").strip()
        try:
            quantity = parse_decimal(_cell(row, mapping, "quantity"))
            unit_price = parse_idr(_cell(row, mapping, "unit_price"))
            discount = parse_decimal(_cell(row, mapping, "discount")) or Decimal(0)
            amount = parse_idr(_cell(row, mapping, "line_amount"))
            number = int(_cell(row, mapping, "line"))
        except (NormalisationError, TypeError, ValueError):
            by_entry[entry_id].append(
                Line(0, str(_cell(row, mapping, "item_code") or ""), "", Decimal(0), "", 0, Decimal(0), 0,
                     f"{sheet_name}!row {excel_row}", raw="UNREADABLE")
            )
            continue
        if None in (quantity, unit_price, amount):
            by_entry[entry_id].append(
                Line(number, str(_cell(row, mapping, "item_code") or ""), "", Decimal(0), "", 0, Decimal(0), 0,
                     f"{sheet_name}!row {excel_row}", raw="UNREADABLE")
            )
            continue
        by_entry[entry_id].append(
            Line(
                number=number,
                sku=str(_cell(row, mapping, "item_code") or "").strip(),
                description=str(_cell(row, mapping, "description") or "").strip(),
                quantity=quantity,
                unit=str(_cell(row, mapping, "unit") or "").strip().lower(),
                unit_price=unit_price,
                discount_pct=discount,
                amount=amount,
                source=f"{sheet_name}!row {excel_row}",
            )
        )
    return by_entry


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


def load_erp(path: str) -> ErpExtraction:
    file_name = Path(path).name
    workbook = openpyxl.load_workbook(path, data_only=True)
    document_sheets: List[Tuple[str, str, Dict[str, int], List[Tuple[int, Tuple[Any, ...]]]]] = []
    line_sheets: List[Tuple[str, Dict[str, int], List[Tuple[int, Tuple[Any, ...]]]]] = []
    kinds: Dict[str, str] = {}
    info: Dict[str, str] = {}

    for sheet in workbook.worksheets:
        all_rows = list(sheet.iter_rows(values_only=True))
        if not all_rows:
            kinds[sheet.title] = "empty"
            continue
        mapping, number_header = _column_map(all_rows[0])
        kind = _classify(mapping, number_header)
        kinds[sheet.title] = kind
        data_rows = [(index, row) for index, row in enumerate(all_rows[1:], start=2)]
        if kind in ("invoices", "credit_notes"):
            document_sheets.append((sheet.title, kind, mapping, data_rows))
        elif kind == "lines":
            line_sheets.append((sheet.title, mapping, data_rows))
        else:
            for _, row in data_rows:
                if len(row) >= 2 and row[0] not in (None, ""):
                    info[str(row[0])] = str(row[1] if row[1] is not None else "")

    lines_by_entry: Dict[str, List[Line]] = defaultdict(list)
    for sheet_name, mapping, rows in line_sheets:
        for entry_id, lines in _read_lines(sheet_name, rows, mapping).items():
            lines_by_entry[entry_id].extend(lines)

    documents: List[Document] = []
    for sheet_name, kind, mapping, rows in document_sheets:
        doc_type = CREDIT_NOTE if kind == "credit_notes" else INVOICE
        documents.extend(_read_documents(sheet_name, rows, mapping, doc_type, file_name))

    for position, document in enumerate(documents):
        document.order = position
        document.lines = sorted(lines_by_entry.get(document.entry_id, []), key=lambda line: line.number)
        unreadable = [line for line in document.lines if line.raw == "UNREADABLE"]
        for line in unreadable:
            document.issues.append(f"ERP_UNREADABLE_FIELD: line at {line.source}")
        document.lines = [line for line in document.lines if line.raw != "UNREADABLE"]
        _apply_sign(document)

    return ErpExtraction(documents=documents, sheets=kinds, file_name=file_name, info=info)


def resolve_erp_dates(erp_documents: List[Document], pdf_by_key: Dict[str, Document]) -> None:
    """Read text dates, using the matching PDF date to settle day/month order."""
    for document in erp_documents:
        if document.date is not None or not document.date_raw:
            continue
        counterpart = pdf_by_key.get(document.key)
        hint = counterpart.date if counterpart else None
        parsed = parse_date(document.date_raw, hint=hint)
        document.date = parsed.value
        document.date_ambiguous = parsed.ambiguous
