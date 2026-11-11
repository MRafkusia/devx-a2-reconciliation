"""Arithmetic self-checks of a single document against rules R1-R4 (R7: flag, never fix)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from . import rules
from .models import Document

ERROR = "error"
ROUNDING = "rounding"


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    message: str
    amount: int = 0
    line: Optional[int] = None


def _format(amount: int) -> str:
    return f"{amount:,}"


def check_document(document: Document) -> List[Finding]:
    """Recompute every figure of ``document`` from its own lines and compare with what it prints."""
    prefix = "PDF" if document.side == "pdf" else "ERP"
    findings: List[Finding] = []
    sign = -1 if document.is_credit_note else 1

    if not document.lines:
        code = f"{prefix}_FIELD_MISSING" if prefix == "PDF" else "ERP_NO_LINES"
        findings.append(Finding(code, ERROR, "no line items were found"))

    for line in document.lines:
        expected = sign * rules.line_amount(abs(line.quantity), line.unit_price, line.discount_pct)
        if expected != line.amount:
            findings.append(
                Finding(
                    f"{prefix}_LINE_AMOUNT_WRONG",
                    ERROR,
                    f"line {line.number} ({line.sku}) shows {_format(line.amount)} but "
                    f"quantity x price x discount gives {_format(expected)}",
                    line.amount - expected,
                    line.number,
                )
            )

    printed = {
        "subtotal": document.subtotal,
        "DPP": document.dpp,
        "PPN": document.ppn,
        "total": document.total,
    }
    missing = [name for name, value in printed.items() if value is None]
    if missing:
        findings.append(
            Finding(f"{prefix}_FIELD_MISSING", ERROR, f"missing figures: {', '.join(missing)}")
        )
        return findings

    lines_sum = document.lines_total()
    if document.lines and document.subtotal != lines_sum:
        findings.append(
            Finding(
                f"{prefix}_SUBTOTAL_NOT_SUM_OF_LINES",
                ERROR,
                f"subtotal {_format(document.subtotal)} differs from the sum of its lines "
                f"{_format(lines_sum)}",
                document.subtotal - lines_sum,
            )
        )

    expected_dpp = rules.dpp_nilai_lain(document.subtotal)
    findings.extend(
        _tax_finding(prefix, "DPP", document.dpp, expected_dpp, f"{prefix}_DPP_NOT_11_12", "subtotal x 11/12")
    )
    expected_ppn = rules.ppn(document.dpp)
    findings.extend(
        _tax_finding(prefix, "PPN", document.ppn, expected_ppn, f"{prefix}_PPN_NOT_12_PCT", "DPP x 12%")
    )

    expected_total = document.subtotal + document.ppn
    if document.total != expected_total:
        findings.append(
            Finding(
                f"{prefix}_TOTAL_NOT_SUBTOTAL_PLUS_PPN",
                ERROR,
                f"total {_format(document.total)} differs from subtotal + PPN {_format(expected_total)}",
                document.total - expected_total,
            )
        )
    return findings


def _tax_finding(
    prefix: str, label: str, printed: int, expected: int, code: str, rule: str
) -> List[Finding]:
    difference = printed - expected
    if difference == 0:
        return []
    if rules.within_tolerance(difference):
        return [
            Finding(
                f"{prefix}_ROUNDING",
                ROUNDING,
                f"{label} {_format(printed)} is {abs(difference)} away from {rule} = {_format(expected)}",
                difference,
            )
        ]
    return [
        Finding(
            code,
            ERROR,
            f"{label} {_format(printed)} should be {_format(expected)} ({rule})",
            difference,
        )
    ]


def errors(findings: List[Finding]) -> List[Finding]:
    return [finding for finding in findings if finding.severity == ERROR]
