"""Build the reconciliation report and write it as XLSX, CSV and JSON."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import __version__, rules
from . import results as r
from .explain import COMPONENT_LABELS, REASON_LABELS
from .models import Document, Line
from .summary import decision_rows, payment_position, render_summary

DECISION_HEADERS = [
    "document_no", "status", "pdf_total", "erp_total", "difference", "decision", "note", "decided_at", "suggested_action",
]
DECISION_WIDTHS = {
    "document_no": 24, "status": 27, "pdf_total": 15, "erp_total": 15, "difference": 14, "decision": 22,
    "note": 50, "decided_at": 20, "suggested_action": 60,
}
DECISIONS_SHEET = "Decisions"

STATUS_FILLS = {
    r.MATCHED: "E3F1E4",
    r.MATCHED_WITHIN_TOLERANCE: "EEF6E0",
    r.AMOUNT_MISMATCH: "FFF1C9",
    r.MISSING_IN_ERP: "FBDADA",
    r.MISSING_IN_PDF: "FBDADA",
    r.DUPLICATE_IN_ERP: "E9E1F7",
    r.DUPLICATE_IN_PDF: "E9E1F7",
    r.NEEDS_REVIEW: "FFE0C2",
}

STATUS_RANK = {
    r.NEEDS_REVIEW: 0,
    r.AMOUNT_MISMATCH: 1,
    r.DUPLICATE_IN_ERP: 2,
    r.DUPLICATE_IN_PDF: 3,
    r.MISSING_IN_ERP: 4,
    r.MISSING_IN_PDF: 5,
    r.MATCHED_WITHIN_TOLERANCE: 6,
    r.MATCHED: 7,
}

NUMBER_FORMAT = "#,##0;[Red]-#,##0;0"


def _page_range(pages: List[int]) -> str:
    if not pages:
        return ""
    return f"p{pages[0]}" if len(pages) == 1 else f"p{pages[0]}-{pages[-1]}"


def _pdf_source(document: Document, pdf_file: str) -> str:
    return f"{pdf_file} {_page_range(document.pages)}" if document else ""


def _erp_source(documents: List[Document]) -> str:
    return "; ".join(f"{doc.entry_id} ({doc.sources.get('entry', '')})" for doc in documents)


def _line_values(line: Line) -> Dict[str, Any]:
    return {
        "line": line.number,
        "sku": line.sku,
        "quantity": float(line.quantity) if line.quantity % 1 else int(line.quantity),
        "unit_price": line.unit_price,
        "discount_pct": float(line.discount_pct),
        "amount": line.amount,
        "source": line.source,
    }


def _document_rows(rec: r.Reconciliation) -> List[Dict[str, Any]]:
    rows = []
    for result in rec.results:
        rows.append(
            {
                "document_no": result.number,
                "type": result.doc_type,
                "pdf_total": result.pdf_total,
                "erp_total": result.erp_total,
                "difference": result.difference,
                "status": result.status,
                "reason_codes": ", ".join(result.reasons),
                "explanation": result.explanation,
                "suggested_action": result.suggested_action,
                "pdf_source": _pdf_source(result.pdf, rec.pdf_file) if result.pdf else "",
                "erp_source": _erp_source(result.erp),
                "erp_entries": ", ".join(doc.entry_id for doc in result.erp),
            }
        )
    return rows


def _line_rows(rec: r.Reconciliation) -> List[Dict[str, Any]]:
    rows = []
    for result in rec.results:
        for diff in result.line_diffs:
            pdf_line, erp_line = diff.pdf_line, diff.erp_line
            rows.append(
                {
                    "document_no": result.number,
                    "status": result.status,
                    "issue_codes": ", ".join(diff.codes),
                    "pdf_line": pdf_line.number if pdf_line else "",
                    "erp_line": erp_line.number if erp_line else "",
                    "sku": (pdf_line or erp_line).sku,
                    "pdf_quantity": _quantity(pdf_line),
                    "erp_quantity": _quantity(erp_line),
                    "pdf_unit_price": pdf_line.unit_price if pdf_line else "",
                    "erp_unit_price": erp_line.unit_price if erp_line else "",
                    "pdf_discount_pct": float(pdf_line.discount_pct) if pdf_line else "",
                    "erp_discount_pct": float(erp_line.discount_pct) if erp_line else "",
                    "pdf_amount": pdf_line.amount if pdf_line else "",
                    "erp_amount": erp_line.amount if erp_line else "",
                    "amount_difference": diff.amount_diff,
                    "detail": diff.detail,
                    "pdf_source": f"{rec.pdf_file} {pdf_line.source}" if pdf_line else "",
                    "erp_source": erp_line.source if erp_line else "",
                }
            )
    return rows


def _quantity(line: Line) -> Any:
    if line is None:
        return ""
    return float(line.quantity) if line.quantity % 1 else int(line.quantity)


def _audit_rows(rec: r.Reconciliation) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    def add(result: r.DocumentResult, side: str, document: Document, field: str, value: Any, source: str, raw: str = "") -> None:
        rows.append(
            {
                "document_no": result.number,
                "side": side,
                "entry": document.entry_id,
                "field": field,
                "value": value,
                "source": source,
                "raw_text": raw,
            }
        )

    for result in rec.results:
        documents = ([("PDF", result.pdf)] if result.pdf else []) + [("ERP", doc) for doc in result.erp]
        for side, document in documents:
            prefix = f"{rec.pdf_file} " if side == "PDF" else f"{rec.erp_file} "
            for field, attribute in (
                ("document number", "number"),
                ("date", "date_raw"),
                ("PO / reference", "po" if not document.is_credit_note else "reference"),
                ("subtotal", "subtotal"),
                ("DPP", "dpp"),
                ("PPN", "ppn"),
                ("total", "total"),
            ):
                source_key = {"number": "number", "date_raw": "date", "po": "po", "reference": "reference"}.get(attribute, attribute)
                source = document.sources.get(source_key, "")
                add(result, side, document, field, getattr(document, attribute), prefix + source if source else "")
            for line in document.lines:
                for name, value in (
                    ("quantity", _quantity(line)),
                    ("unit price", line.unit_price),
                    ("discount %", float(line.discount_pct)),
                    ("line amount", line.amount),
                ):
                    add(result, side, document, f"line {line.number} {line.sku} {name}", value, prefix + line.source, line.raw)
    return rows


def _warnings(rec: r.Reconciliation) -> List[str]:
    warnings = []
    if rec.totals.pdf_documents == 0:
        warnings.append("No documents could be read from the PDF. Check that it is the supplier invoice file.")
    elif rec.totals.erp_entries == 0:
        warnings.append("No entries could be read from the ERP workbook. Check that it is the AP export.")
    elif not any(result.pdf and result.erp for result in rec.results):
        warnings.append(
            "None of the PDF documents matches an ERP entry. Check that both files are for the same supplier and period."
        )
    if rec.unreadable_pages:
        warnings.append("Some PDF pages could not be read: " + "; ".join(rec.unreadable_pages))
    return warnings


def _control_rows(rec: r.Reconciliation, position: Dict[str, Dict[str, int]]) -> List[Dict[str, Any]]:
    t = rec.totals
    rows: List[Dict[str, Any]] = [
        {"section": "Batch", "item": "PDF documents read", "amount": t.pdf_documents},
        {"section": "Batch", "item": "ERP entries read", "amount": t.erp_entries},
        {"section": "Batch", "item": "PDF invoices / credit notes", "amount": f"{t.invoices_pdf} / {t.credit_notes_pdf}"},
        {"section": "Batch", "item": "ERP invoices / credit notes", "amount": f"{t.invoices_erp} / {t.credit_notes_erp}"},
        {"section": "Totals", "item": "PDF total (credit notes negative)", "amount": t.pdf_total},
        {"section": "Totals", "item": "ERP total (credit notes negative)", "amount": t.erp_total},
        {"section": "Totals", "item": "Difference (PDF - ERP)", "amount": t.difference},
    ]
    for code, amount in sorted(t.components.items(), key=lambda item: -abs(item[1])):
        rows.append({"section": "Explained by", "item": COMPONENT_LABELS.get(code, code), "amount": amount})
    rows.append({"section": "Check", "item": "Total explained", "amount": t.explained})
    rows.append({"section": "Check", "item": "Unexplained difference", "amount": t.unexplained})
    cleared, held = position["cleared"], position["held"]
    rows.append(
        {"section": "Payment", "item": f"Cleared for payment, as booked in the ERP ({cleared['documents']} documents)",
         "amount": cleared["amount"]}
    )
    rows.append(
        {"section": "Payment", "item": f"On hold until reviewed, as booked in the ERP ({held['documents']} documents)",
         "amount": held["erp_amount"]}
    )
    rows.append({"section": "Payment", "item": "Differences still to resolve (absolute)", "amount": held["at_stake"]})
    for status in r.STATUSES:
        bucket = t.by_status.get(status)
        if bucket:
            rows.append(
                {
                    "section": "By status",
                    "item": f"{status} ({bucket['documents']} documents)",
                    "amount": bucket["difference"],
                }
            )
    return rows


def build_report(rec: r.Reconciliation, runtime_seconds: float = 0.0, run_id: str = "") -> Dict[str, Any]:
    documents = []
    for result in rec.results:
        documents.append(
            {
                "key": result.key,
                "document_no": result.number,
                "type": result.doc_type,
                "status": result.status,
                "needs_attention": result.needs_attention,
                "reasons": result.reasons,
                "pdf_total": result.pdf_total,
                "erp_total": result.erp_total,
                "difference": result.difference,
                "explanation": result.explanation,
                "suggested_action": result.suggested_action,
                "pdf_source": _pdf_source(result.pdf, rec.pdf_file) if result.pdf else "",
                "erp_source": _erp_source(result.erp),
                "erp_entries": [doc.entry_id for doc in result.erp],
                "components": [
                    {"code": code, "label": COMPONENT_LABELS.get(code, code), "amount": amount}
                    for code, amount in result.components.items()
                ],
                "lines": [
                    {
                        "codes": diff.codes,
                        "detail": diff.detail,
                        "amount_difference": diff.amount_diff,
                        "pdf": _line_values(diff.pdf_line) if diff.pdf_line else None,
                        "erp": _line_values(diff.erp_line) if diff.erp_line else None,
                    }
                    for diff in result.line_diffs
                ],
                "notes": result.notes,
            }
        )
    totals = rec.totals
    return {
        "meta": {
            "version": __version__,
            "run_id": run_id,
            "warnings": _warnings(rec),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "pdf_file": rec.pdf_file,
            "erp_file": rec.erp_file,
            "erp_exported_at": rec.erp_exported_at,
            "tolerance_idr": rules.TOLERANCE_IDR,
            "runtime_seconds": round(runtime_seconds, 2),
            "llm_calls": 0,
            "api_cost_usd": 0.0,
            "unreadable_pages": rec.unreadable_pages,
        },
        "totals": {
            "pdf_documents": totals.pdf_documents,
            "erp_entries": totals.erp_entries,
            "pdf_total": totals.pdf_total,
            "erp_total": totals.erp_total,
            "difference": totals.difference,
            "explained": totals.explained,
            "unexplained": totals.unexplained,
            "components": [
                {"code": code, "label": COMPONENT_LABELS.get(code, code), "amount": amount}
                for code, amount in sorted(totals.components.items(), key=lambda item: -abs(item[1]))
            ],
            "by_status": [
                {"status": status, **totals.by_status[status]} for status in r.STATUSES if status in totals.by_status
            ],
        },
        "payment": payment_position(documents, {}),
        "documents": documents,
        "extraction_log": rec.pages,
        "reason_catalog": REASON_LABELS,
    }


def _write_csv(path: Path, rows: List[Dict[str, Any]], fallback_headers: List[str]) -> None:
    headers = list(rows[0].keys()) if rows else fallback_headers
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def _style_sheet(sheet, widths: Dict[str, int], wrap: List[str], money: List[str], status_column: str = "") -> None:
    header_fill = PatternFill("solid", fgColor="1F2A37")
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    headers = [cell.value for cell in sheet[1]]
    for index, header in enumerate(headers, start=1):
        letter = get_column_letter(index)
        sheet.column_dimensions[letter].width = widths.get(header, 16)
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            header = headers[cell.column - 1]
            cell.alignment = Alignment(vertical="top", wrap_text=header in wrap)
            if header in money and isinstance(cell.value, (int, float)):
                cell.number_format = NUMBER_FORMAT
        if status_column and status_column in headers:
            status_cell = row[headers.index(status_column)]
            fill = STATUS_FILLS.get(str(status_cell.value))
            if fill:
                status_cell.fill = PatternFill("solid", fgColor=fill)
                status_cell.font = Font(bold=True)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions


def _append_table(sheet, rows: List[Dict[str, Any]], headers: List[str]) -> None:
    sheet.append(headers)
    for row in rows:
        sheet.append([row.get(header, "") for header in headers])


def write_workbook(path: Path, rec: r.Reconciliation, report: Dict[str, Any]) -> None:
    workbook = Workbook()
    control = workbook.active
    control.title = "Control totals"
    control_rows = _control_rows(rec, report["payment"])
    _append_table(control, control_rows, ["section", "item", "amount"])
    control.column_dimensions["A"].width = 16
    control.column_dimensions["B"].width = 72
    control.column_dimensions["C"].width = 20
    for cell in control[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F2A37")
    for row in control.iter_rows(min_row=2):
        if isinstance(row[2].value, (int, float)):
            row[2].number_format = NUMBER_FORMAT
        if row[0].value in ("Totals", "Check", "Payment"):
            for cell in row:
                cell.font = Font(bold=True)
    control.append([])
    control.append(["Source", f"{rec.pdf_file} and {rec.erp_file}", ""])
    control.append(["Method", "All arithmetic and matching in deterministic code; no LLM calls.", ""])

    doc_headers = [
        "document_no", "type", "pdf_total", "erp_total", "difference", "status", "reason_codes",
        "explanation", "suggested_action", "pdf_source", "erp_source",
    ]
    documents = workbook.create_sheet("Documents")
    _append_table(documents, _document_rows(rec), doc_headers)
    _style_sheet(
        documents,
        {"document_no": 24, "type": 13, "pdf_total": 15, "erp_total": 15, "difference": 14, "status": 27,
         "reason_codes": 34, "explanation": 70, "suggested_action": 48, "pdf_source": 34, "erp_source": 34},
        wrap=["explanation", "suggested_action", "reason_codes", "erp_source"],
        money=["pdf_total", "erp_total", "difference"],
        status_column="status",
    )

    queue_rows = sorted(
        (row for row in _document_rows(rec) if row["status"] not in r.CLEAN_STATUSES),
        key=lambda row: (STATUS_RANK[row["status"]], -abs(row["difference"])),
    )
    decisions = workbook.create_sheet(DECISIONS_SHEET)
    _fill_decisions(decisions, decision_rows(report["documents"], {}))

    queue = workbook.create_sheet("Review queue")
    _append_table(queue, queue_rows, doc_headers)
    _style_sheet(
        queue,
        {"document_no": 24, "type": 13, "pdf_total": 15, "erp_total": 15, "difference": 14, "status": 27,
         "reason_codes": 34, "explanation": 70, "suggested_action": 48, "pdf_source": 34, "erp_source": 34},
        wrap=["explanation", "suggested_action", "reason_codes", "erp_source"],
        money=["pdf_total", "erp_total", "difference"],
        status_column="status",
    )

    line_headers = [
        "document_no", "status", "issue_codes", "pdf_line", "erp_line", "sku", "pdf_quantity", "erp_quantity",
        "pdf_unit_price", "erp_unit_price", "pdf_discount_pct", "erp_discount_pct", "pdf_amount", "erp_amount",
        "amount_difference", "detail", "pdf_source", "erp_source",
    ]
    lines = workbook.create_sheet("Line discrepancies")
    _append_table(lines, _line_rows(rec), line_headers)
    _style_sheet(
        lines,
        {"document_no": 24, "status": 24, "issue_codes": 24, "detail": 70, "pdf_source": 36, "erp_source": 26, "sku": 16},
        wrap=["detail"],
        money=["pdf_unit_price", "erp_unit_price", "pdf_amount", "erp_amount", "amount_difference"],
        status_column="status",
    )

    audit = workbook.create_sheet("Audit trail")
    _append_table(audit, _audit_rows(rec), ["document_no", "side", "entry", "field", "value", "source", "raw_text"])
    _style_sheet(
        audit,
        {"document_no": 24, "side": 7, "entry": 10, "field": 34, "value": 18, "source": 60, "raw_text": 70},
        wrap=[],
        money=["value"],
    )

    log = workbook.create_sheet("Extraction log")
    _append_table(log, rec_pages(rec), ["page", "kind", "method", "detail"])
    _style_sheet(log, {"page": 8, "kind": 10, "method": 20, "detail": 60}, wrap=[], money=[])

    catalog = workbook.create_sheet("Reason codes")
    _append_table(
        catalog, [{"code": code, "meaning": label} for code, label in REASON_LABELS.items()], ["code", "meaning"]
    )
    _style_sheet(catalog, {"code": 36, "meaning": 80}, wrap=[], money=[])
    workbook.save(path)


def rec_pages(rec: r.Reconciliation) -> List[Dict[str, Any]]:
    return rec.pages


def _fill_decisions(sheet, rows: List[Dict[str, Any]]) -> None:
    _append_table(sheet, rows, DECISION_HEADERS)
    _style_sheet(
        sheet, DECISION_WIDTHS, wrap=["note", "suggested_action"], money=["pdf_total", "erp_total", "difference"],
        status_column="status",
    )


def write_decisions(run_dir: Path, decisions: Dict[str, Any]) -> None:
    """Refresh the decision sheet, decisions.csv and summary.md of a finished run."""
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    rows = decision_rows(report["documents"], decisions)
    _write_csv(run_dir / "decisions.csv", rows, DECISION_HEADERS)
    (run_dir / "summary.md").write_text(render_summary(report, decisions), encoding="utf-8")
    workbook_path = run_dir / "reconciliation_report.xlsx"
    if workbook_path.exists():
        workbook = load_workbook(workbook_path)
        position = workbook.sheetnames.index(DECISIONS_SHEET) if DECISIONS_SHEET in workbook.sheetnames else 2
        if DECISIONS_SHEET in workbook.sheetnames:
            del workbook[DECISIONS_SHEET]
        _fill_decisions(workbook.create_sheet(DECISIONS_SHEET, position), rows)
        workbook.save(workbook_path)


def write_outputs(rec: r.Reconciliation, out_dir: Path, runtime_seconds: float = 0.0) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = build_report(rec, runtime_seconds, out_dir.name)
    paths = {
        "summary": out_dir / "summary.md",
        "xlsx": out_dir / "reconciliation_report.xlsx",
        "documents_csv": out_dir / "reconciliation_report.csv",
        "lines_csv": out_dir / "line_discrepancies.csv",
        "totals_csv": out_dir / "control_totals.csv",
        "audit_csv": out_dir / "audit_trail.csv",
        "decisions_csv": out_dir / "decisions.csv",
        "json": out_dir / "report.json",
    }
    write_workbook(paths["xlsx"], rec, report)
    _write_csv(paths["documents_csv"], _document_rows(rec), [])
    _write_csv(paths["lines_csv"], _line_rows(rec), [])
    _write_csv(paths["totals_csv"], _control_rows(rec, report["payment"]), ["section", "item", "amount"])
    _write_csv(paths["audit_csv"], _audit_rows(rec), [])
    paths["json"].write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_csv(paths["decisions_csv"], decision_rows(report["documents"], {}), DECISION_HEADERS)
    paths["summary"].write_text(render_summary(report, {}), encoding="utf-8")
    return paths
