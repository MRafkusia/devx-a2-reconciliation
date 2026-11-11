import csv
import json

import openpyxl
import pytest

from reconcile import results as r
from reconcile.pdf_extract import ocr_available
from reconcile.pipeline import run

EXPECTED = {
    "0141": (r.MATCHED, 0),
    "0142": (r.MATCHED, 0),
    "0143": (r.MATCHED_WITHIN_TOLERANCE, -1),
    "0144": (r.AMOUNT_MISMATCH, 527250),
    "0145": (r.AMOUNT_MISMATCH, 666000),
    "0146": (r.MISSING_IN_ERP, 15688629),
    "0147": (r.DUPLICATE_IN_ERP, -17238178),
    "0148": (r.NEEDS_REVIEW, 204841),
    "0149": (r.NEEDS_REVIEW, 111000),
    "0150": (r.MATCHED, 0),
    "0151": (r.AMOUNT_MISMATCH, 277500),
    "0152": (r.MATCHED, 0),
    "0153": (r.MATCHED, 0),
    "0154": (r.NEEDS_REVIEW, 0),
    "0155": (r.MISSING_IN_PDF, -3493714),
    "0012": (r.MATCHED, 0),
}

pytestmark = pytest.mark.skipif(not ocr_available(), reason="tesseract is not installed")


@pytest.fixture(scope="module")
def september(tmp_path_factory, sample_pdf, sample_erp):
    out = tmp_path_factory.mktemp("out")
    reconciliation, paths, _ = run(sample_pdf, sample_erp, str(out))
    return reconciliation, paths, paths["json"].parent


def test_every_september_document_gets_the_expected_status_and_difference(september):
    reconciliation, _, _ = september
    by_suffix = {result.number[-4:]: result for result in reconciliation.results}
    assert set(by_suffix) == set(EXPECTED)
    for suffix, (status, difference) in EXPECTED.items():
        assert (by_suffix[suffix].status, by_suffix[suffix].difference) == (status, difference), suffix


def test_batch_totals_are_fully_explained(september):
    totals = september[0].totals
    assert (totals.pdf_total, totals.erp_total, totals.difference) == (307896675, 311153348, -3256673)
    assert totals.unexplained == 0
    assert sum(totals.components.values()) == totals.difference


def test_outputs_are_written(september):
    _, paths, out = september
    for name in ("reconciliation_report.xlsx", "reconciliation_report.csv", "line_discrepancies.csv",
                 "control_totals.csv", "audit_trail.csv", "decisions.csv", "summary.md", "report.json"):
        assert (out / name).exists(), name


def test_workbook_has_all_review_sheets(september):
    workbook = openpyxl.load_workbook(september[2] / "reconciliation_report.xlsx")
    assert workbook.sheetnames == ["Control totals", "Documents", "Decisions", "Review queue", "Line discrepancies",
                                   "Audit trail", "Extraction log", "Reason codes"]


def test_csv_rows_match_documents(september):
    with open(september[2] / "reconciliation_report.csv", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == len(EXPECTED)


def test_json_report_carries_status_and_audit_sources(september):
    report = json.loads((september[2] / "report.json").read_text(encoding="utf-8"))
    assert report["totals"]["unexplained"] == 0
    flagged = next(doc for doc in report["documents"] if doc["document_no"].endswith("0144"))
    assert flagged["pdf_source"] and flagged["erp_source"] and flagged["lines"]


def test_running_twice_gives_identical_results(tmp_path, sample_pdf, sample_erp):
    first, _, _ = run(sample_pdf, sample_erp, str(tmp_path / "a"))
    second, _, _ = run(sample_pdf, sample_erp, str(tmp_path / "b"))
    assert [(x.number, x.status, x.difference) for x in first.results] == [(x.number, x.status, x.difference) for x in second.results]


def test_payment_position_splits_the_erp_total(september):
    reconciliation, paths, _ = september
    position = json.loads(paths["json"].read_text(encoding="utf-8"))["payment"]
    assert position["cleared"] == {"documents": 7, "amount": 163542864}
    assert position["held"]["documents"] == 9
    assert position["cleared"]["amount"] + position["held"]["erp_amount"] == reconciliation.totals.erp_total


def test_summary_ranks_open_items_by_amount(september):
    summary = (september[2] / "summary.md").read_text(encoding="utf-8")
    assert summary.index("0147") < summary.index("0146") < summary.index("0145")
    assert "Decision: Pending." in summary


def test_matched_credit_note_is_applied_not_paid(september):
    note = next(result for result in september[0].results if result.number.endswith("0012"))
    assert note.suggested_action == "Apply the credit note against the supplier balance."


def test_each_run_gets_its_own_folder(tmp_path, sample_pdf, sample_erp):
    first = run(sample_pdf, sample_erp, str(tmp_path), use_ocr=False)[1]["json"].parent
    second = run(sample_pdf, sample_erp, str(tmp_path), use_ocr=False)[1]["json"].parent
    assert first != second and first.parent == second.parent == tmp_path
