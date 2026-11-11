"""Payment position, reviewer decisions and the plain-language run summary, all built from the report data."""

from __future__ import annotations

from typing import Any, Dict, List

DECISION_LABELS = {"approve": "Approved for payment", "hold": "On hold", "escalate": "Escalated"}
PENDING = "Pending"
NOT_REQUIRED = "Not required"


def _decision(document: Dict[str, Any], decisions: Dict[str, Any]) -> str:
    return decisions.get(document["key"], {}).get("decision", "")


def payment_position(documents: List[Dict[str, Any]], decisions: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    cleared = [doc for doc in documents if not doc["needs_attention"]]
    flagged = [doc for doc in documents if doc["needs_attention"]]
    released = [doc for doc in flagged if _decision(doc, decisions) == "approve"]
    held = [doc for doc in flagged if _decision(doc, decisions) != "approve"]
    return {
        "cleared": {"documents": len(cleared), "amount": sum(doc["erp_total"] for doc in cleared)},
        "released": {"documents": len(released), "amount": sum(doc["erp_total"] for doc in released)},
        "held": {
            "documents": len(held),
            "erp_amount": sum(doc["erp_total"] for doc in held),
            "pdf_amount": sum(doc["pdf_total"] for doc in held),
            "at_stake": sum(abs(doc["difference"]) for doc in held),
        },
    }


def decision_rows(documents: List[Dict[str, Any]], decisions: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for doc in documents:
        saved = decisions.get(doc["key"], {})
        if saved:
            label = DECISION_LABELS.get(saved.get("decision", ""), saved.get("decision", ""))
        else:
            label = PENDING if doc["needs_attention"] else NOT_REQUIRED
        rows.append(
            {
                "document_no": doc["document_no"],
                "status": doc["status"],
                "pdf_total": doc["pdf_total"],
                "erp_total": doc["erp_total"],
                "difference": doc["difference"],
                "decision": label,
                "note": saved.get("note", ""),
                "decided_at": saved.get("at", ""),
                "suggested_action": doc["suggested_action"],
            }
        )
    return rows


def action_queue(documents: List[Dict[str, Any]], decisions: Dict[str, Any]) -> List[Dict[str, Any]]:
    open_items = [doc for doc in documents if doc["needs_attention"] and _decision(doc, decisions) != "approve"]
    return sorted(open_items, key=lambda doc: (-abs(doc["difference"]), doc["document_no"]))


def _idr(value: int, signed: bool = False) -> str:
    return f"IDR {value:+,}" if signed and value else f"IDR {value:,}"


def render_summary(report: Dict[str, Any], decisions: Dict[str, Any]) -> str:
    meta, totals, documents = report["meta"], report["totals"], report["documents"]
    position = payment_position(documents, decisions)
    queue = action_queue(documents, decisions)
    lines = [
        "# Reconciliation summary",
        "",
        f"Supplier PDF: {meta['pdf_file']}  ",
        f"ERP export: {meta['erp_file']}  ",
        f"Run: {meta['run_id']} (generated {meta['generated_at']})",
        "",
    ]
    if meta.get("warnings"):
        lines += ["## Warnings", ""] + [f"- {warning}" for warning in meta["warnings"]] + [""]
    lines += [
        "## Position",
        "",
        "| Item | Documents | Amount |",
        "|---|---|---|",
        f"| Supplier PDF total | {totals['pdf_documents']} | {_idr(totals['pdf_total'])} |",
        f"| ERP total | {totals['erp_entries']} | {_idr(totals['erp_total'])} |",
        f"| Difference (PDF minus ERP) | | {_idr(totals['difference'], True)} |",
        f"| Unexplained difference | | {_idr(totals['unexplained'])} |",
        f"| Cleared for payment (as booked in the ERP) | {position['cleared']['documents']} | {_idr(position['cleared']['amount'])} |",
        f"| Released by a reviewer | {position['released']['documents']} | {_idr(position['released']['amount'])} |",
        f"| On hold (as booked in the ERP) | {position['held']['documents']} | {_idr(position['held']['erp_amount'])} |",
        f"| Differences still to resolve | | {_idr(position['held']['at_stake'])} |",
        "",
        "Credit notes count as negative amounts.",
        "",
        "## Act on these first",
        "",
    ]
    if not queue:
        lines += ["Nothing is waiting for action.", ""]
    for index, doc in enumerate(queue, start=1):
        saved = decisions.get(doc["key"], {})
        decision = DECISION_LABELS.get(saved.get("decision", ""), PENDING)
        note = f" Reviewer note: {saved['note']}" if saved.get("note") else ""
        lines += [
            f"{index}. **{doc['document_no']}** ({doc['status']}, difference {_idr(doc['difference'], True)})  ",
            f"   {doc['explanation']}  ",
            f"   Action: {doc['suggested_action']}  ",
            f"   Decision: {decision}.{note}",
            "",
        ]
    done = [doc for doc in documents if doc not in queue]
    lines += ["## Cleared or released", ""]
    if not done:
        lines += ["None.", ""]
    for doc in done:
        how = "released by a reviewer" if doc["needs_attention"] else doc["status"]
        lines.append(f"- {doc['document_no']}: {_idr(doc['erp_total'])} ({how})")
    lines += [
        "",
        "## Method",
        "",
        f"All figures were computed by deterministic code ({meta['llm_calls']} model calls). "
        f"Differences of up to IDR {meta['tolerance_idr']} count as rounding only when every line agrees. "
        "Each figure can be traced to its PDF page or ERP cell in the audit trail of the Excel report.",
        "",
    ]
    return "\n".join(lines)
