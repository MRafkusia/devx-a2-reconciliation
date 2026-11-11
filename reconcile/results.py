"""Result records produced by matching."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .checks import Finding
from .models import Document, Line

MATCHED = "MATCHED"
MATCHED_WITHIN_TOLERANCE = "MATCHED_WITHIN_TOLERANCE"
AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
MISSING_IN_ERP = "MISSING_IN_ERP"
MISSING_IN_PDF = "MISSING_IN_PDF"
DUPLICATE_IN_ERP = "DUPLICATE_IN_ERP"
DUPLICATE_IN_PDF = "DUPLICATE_IN_PDF"
NEEDS_REVIEW = "NEEDS_REVIEW"

STATUSES = (
    MATCHED,
    MATCHED_WITHIN_TOLERANCE,
    AMOUNT_MISMATCH,
    MISSING_IN_ERP,
    MISSING_IN_PDF,
    DUPLICATE_IN_ERP,
    DUPLICATE_IN_PDF,
    NEEDS_REVIEW,
)

CLEAN_STATUSES = (MATCHED, MATCHED_WITHIN_TOLERANCE)


@dataclass
class LineDiff:
    codes: List[str]
    pdf_line: Optional[Line]
    erp_line: Optional[Line]
    amount_diff: int
    detail: str


@dataclass
class DocumentResult:
    key: str
    number: str
    doc_type: str
    status: str
    reasons: List[str]
    pdf_total: int
    erp_total: int
    difference: int
    explanation: str = ""
    suggested_action: str = ""
    pdf: Optional[Document] = None
    erp: List[Document] = field(default_factory=list)
    line_diffs: List[LineDiff] = field(default_factory=list)
    components: Dict[str, int] = field(default_factory=dict)
    findings: List[Finding] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def needs_attention(self) -> bool:
        return self.status not in CLEAN_STATUSES


@dataclass
class ControlTotals:
    pdf_documents: int
    erp_entries: int
    pdf_total: int
    erp_total: int
    difference: int
    components: Dict[str, int]
    explained: int
    unexplained: int
    by_status: Dict[str, Dict[str, int]]
    invoices_pdf: int
    invoices_erp: int
    credit_notes_pdf: int
    credit_notes_erp: int


@dataclass
class Reconciliation:
    results: List[DocumentResult]
    totals: ControlTotals
    pdf_file: str
    erp_file: str
    unreadable_pages: List[str]
    pages: List[Dict[str, str]]
    erp_sheets: Dict[str, str]
    erp_exported_at: str
