"""Data records shared by extraction, matching and reporting."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional

INVOICE = "INVOICE"
CREDIT_NOTE = "CREDIT_NOTE"


@dataclass
class Line:
    number: int
    sku: str
    description: str
    quantity: Decimal
    unit: str
    unit_price: int
    discount_pct: Decimal
    amount: int
    source: str
    raw: str = ""


@dataclass
class Document:
    side: str
    doc_type: str
    number: str
    key: str
    date: Optional[date] = None
    date_raw: str = ""
    date_ambiguous: bool = False
    po: str = ""
    reference: str = ""
    vendor: str = ""
    currency: str = "IDR"
    subtotal: Optional[int] = None
    dpp: Optional[int] = None
    ppn: Optional[int] = None
    total: Optional[int] = None
    lines: List[Line] = field(default_factory=list)
    sources: Dict[str, str] = field(default_factory=dict)
    location: str = ""
    pages: List[int] = field(default_factory=list)
    entry_id: str = ""
    erp_status: str = ""
    posted_by: str = ""
    ocr_used: bool = False
    ocr_verified: bool = True
    issues: List[str] = field(default_factory=list)
    normalised: List[str] = field(default_factory=list)
    order: int = 0

    @property
    def is_credit_note(self) -> bool:
        return self.doc_type == CREDIT_NOTE

    def lines_total(self) -> int:
        return sum(line.amount for line in self.lines)


@dataclass
class PageLog:
    page: int
    kind: str
    method: str
    detail: str = ""


@dataclass
class UnreadablePage:
    page: int
    reason: str


@dataclass
class PdfExtraction:
    documents: List[Document]
    pages: List[PageLog]
    unreadable: List[UnreadablePage]
    file_name: str


@dataclass
class ErpExtraction:
    documents: List[Document]
    sheets: Dict[str, str]
    file_name: str
    info: Dict[str, str]
