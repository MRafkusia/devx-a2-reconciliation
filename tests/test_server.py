import base64
import io
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import openpyxl
import pytest

from reconcile import server


@pytest.fixture()
def base_url(tmp_path):
    state = server.AppState(tmp_path / "output")
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(state))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def call(url, data=None, headers=None, method=None):
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def post_json(url, payload, headers=None):
    merged = {"Content-Type": "application/json", **(headers or {})}
    return call(url, json.dumps(payload).encode(), merged)


def test_index_page_is_served(base_url):
    status, body = call(base_url + "/")
    assert status == 200 and b"<!doctype html>" in body.lower()


def test_report_is_not_available_before_a_run(base_url):
    assert call(base_url + "/api/report")[0] == 404


def test_run_with_the_sample_then_read_report(base_url):
    status, body = post_json(base_url + "/api/run", {"sample": True})
    assert status == 200 and json.loads(body)["documents"] == 16
    status, body = call(base_url + "/api/report")
    assert status == 200 and json.loads(body)["totals"]["unexplained"] == 0


def test_run_without_files_is_rejected(base_url):
    status, body = post_json(base_url + "/api/run", {})
    assert status == 400 and "Choose both" in json.loads(body)["error"]


def test_upload_rejects_wrong_content(base_url):
    status, _ = call(base_url + "/api/upload/pdf", b"not a pdf", {"X-File-Name": "a.pdf"})
    assert status == 400
    status, _ = call(base_url + "/api/upload/erp", b"PK\x03\x04data", {"X-File-Name": "a.pdf"})
    assert status == 400


def test_upload_then_run(base_url):
    root = Path(server.SAMPLE_DIR)
    pdf = next(root.glob("*.pdf"))
    erp = next(root.glob("*.xlsx"))
    assert call(base_url + "/api/upload/pdf", pdf.read_bytes(), {"X-File-Name": pdf.name})[0] == 200
    assert call(base_url + "/api/upload/erp", erp.read_bytes(), {"X-File-Name": erp.name})[0] == 200
    status, body = post_json(base_url + "/api/run", {})
    assert status == 200 and json.loads(body)["ok"]


def first_flagged_key(base_url):
    report = json.loads(call(base_url + "/api/report")[1])
    return next(doc for doc in report["documents"] if doc["needs_attention"] and doc["erp_total"])


def test_decisions_are_validated_and_saved(base_url):
    post_json(base_url + "/api/run", {"sample": True})
    key = first_flagged_key(base_url)["key"]
    assert post_json(base_url + "/api/decisions", {"key": key, "decision": "delete"})[0] == 400
    assert post_json(base_url + "/api/decisions", {"decision": "hold"})[0] == 400
    assert post_json(base_url + "/api/decisions", {"key": "UNKNOWN", "decision": "hold"})[0] == 404
    status, _ = post_json(base_url + "/api/decisions", {"key": key, "decision": "hold", "note": "ask supplier"})
    assert status == 200
    saved = json.loads(call(base_url + "/api/decisions")[1])
    assert saved[key]["decision"] == "hold" and saved[key]["note"] == "ask supplier"


def test_decision_before_any_run_is_rejected(base_url):
    assert post_json(base_url + "/api/decisions", {"key": "A", "decision": "hold"})[0] == 404


def test_approval_moves_the_document_out_of_hold_and_into_the_exports(base_url):
    post_json(base_url + "/api/run", {"sample": True})
    document = first_flagged_key(base_url)
    before = json.loads(call(base_url + "/api/report")[1])["payment"]
    status, body = post_json(base_url + "/api/decisions", {"key": document["key"], "decision": "approve", "note": "PO confirmed"})
    after = json.loads(body)["payment"]
    assert status == 200
    assert after["released"] == {"documents": 1, "amount": document["erp_total"]}
    assert after["held"]["documents"] == before["held"]["documents"] - 1

    decisions_csv = call(base_url + "/api/download/decisions.csv")[1].decode("utf-8-sig")
    assert "Approved for payment" in decisions_csv and "PO confirmed" in decisions_csv
    summary = call(base_url + "/api/download/summary.md")[1].decode("utf-8")
    assert "released by a reviewer" in summary
    workbook = openpyxl.load_workbook(io.BytesIO(call(base_url + "/api/download/reconciliation_report.xlsx")[1]))
    decisions = [row for row in workbook["Decisions"].iter_rows(values_only=True) if row[0] == document["document_no"]]
    assert decisions[0][5] == "Approved for payment" and decisions[0][6] == "PO confirmed"


def test_a_new_run_starts_with_no_decisions(base_url):
    post_json(base_url + "/api/run", {"sample": True})
    key = first_flagged_key(base_url)["key"]
    post_json(base_url + "/api/decisions", {"key": key, "decision": "hold"})
    post_json(base_url + "/api/run", {"sample": True})
    assert json.loads(call(base_url + "/api/decisions")[1]) == {}


def test_unmatched_files_produce_a_warning(tmp_path):
    from reconcile.models import ErpExtraction, PdfExtraction
    from reconcile.match import reconcile
    from reconcile.report import build_report
    from .factories import make_document, make_line

    lines = [make_line(1, "AAA-1", 1, 1000)]
    pdf = PdfExtraction([make_document("pdf", "INV-1", lines)], [], [], "a.pdf")
    erp = ErpExtraction([make_document("erp", "ZZZ-9", lines, entry_id="E1", po="PO-X")], {}, "b.xlsx", {})
    warnings = build_report(reconcile(pdf, erp))["meta"]["warnings"]
    assert any("same supplier and period" in warning for warning in warnings)


def test_cross_origin_posts_are_blocked(base_url):
    status, _ = post_json(base_url + "/api/decisions", {"key": "A", "decision": "hold"}, {"Origin": "http://evil.example"})
    assert status == 403


def test_downloads_are_limited_to_the_whitelist(base_url):
    assert call(base_url + "/api/download/..%2Fserver.py")[0] == 404
    assert call(base_url + "/api/download/report.json")[0] == 404
    post_json(base_url + "/api/run", {"sample": True})
    status, body = call(base_url + "/api/download/reconciliation_report.csv")
    assert status == 200 and body


@pytest.fixture()
def protected_url(tmp_path):
    state = server.AppState(tmp_path / "output", ("reviewer", "s3cret"))
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def basic(user, password):
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_password_protects_pages_and_api(protected_url):
    assert call(protected_url + "/")[0] == 401
    assert call(protected_url + "/api/sample")[0] == 401
    assert post_json(protected_url + "/api/run", {"sample": True})[0] == 401
    assert call(protected_url + "/", headers=basic("reviewer", "wrong"))[0] == 401
    assert call(protected_url + "/", headers=basic("reviewer", "s3cret"))[0] == 200
    assert post_json(protected_url + "/api/run", {"sample": True}, basic("reviewer", "s3cret"))[0] == 200


def test_health_check_needs_no_password(protected_url):
    assert call(protected_url + "/healthz")[0] == 200


def test_credentials_come_from_the_environment(monkeypatch):
    monkeypatch.delenv("RECONCILE_PASSWORD", raising=False)
    assert server.configured_credentials() is None
    monkeypatch.setenv("RECONCILE_PASSWORD", "pw")
    assert server.configured_credentials() == ("reviewer", "pw")
    monkeypatch.setenv("RECONCILE_USER", "ap-team")
    assert server.configured_credentials() == ("ap-team", "pw")
