"""Local web interface: serves web/index.html and a small JSON API around the pipeline."""

from __future__ import annotations

import base64
import hmac
import json
import os
import re
import threading
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from .pipeline import latest_run_dir, run
from .report import write_decisions
from .summary import payment_position

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
SAMPLE_DIR = ROOT / "data" / "sept"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
DOWNLOADS = {
    "reconciliation_report.xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "reconciliation_report.csv": "text/csv; charset=utf-8",
    "line_discrepancies.csv": "text/csv; charset=utf-8",
    "control_totals.csv": "text/csv; charset=utf-8",
    "audit_trail.csv": "text/csv; charset=utf-8",
    "decisions.csv": "text/csv; charset=utf-8",
    "summary.md": "text/markdown; charset=utf-8",
}
DECISIONS = ("approve", "hold", "escalate")
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def configured_credentials() -> Optional[Tuple[str, str]]:
    password = os.environ.get("RECONCILE_PASSWORD", "")
    if not password:
        return None
    return os.environ.get("RECONCILE_USER", "reviewer"), password


def _safe_name(name: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ \-]", "_", Path(name or "").name).strip(" .")
    return cleaned or fallback


class AppState:
    def __init__(self, out_dir: Path, credentials: Optional[Tuple[str, str]] = None) -> None:
        self.credentials = credentials
        self.out_dir = out_dir
        self.upload_dir = out_dir.parent / "uploads"
        self.run_dir: Optional[Path] = latest_run_dir(out_dir)
        self.pdf: Optional[Path] = None
        self.erp: Optional[Path] = None
        self.lock = threading.Lock()

    def load_report(self) -> Optional[Dict[str, Any]]:
        if not self.run_dir:
            return None
        try:
            report = json.loads((self.run_dir / "report.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        report["payment"] = payment_position(report["documents"], self.load_decisions())
        return report

    def sample_files(self) -> Optional[Dict[str, Path]]:
        pdfs = sorted(SAMPLE_DIR.glob("*.pdf"))
        workbooks = sorted(SAMPLE_DIR.glob("*.xlsx"))
        if pdfs and workbooks:
            return {"pdf": pdfs[0], "erp": workbooks[0]}
        return None

    def load_decisions(self) -> Dict[str, Any]:
        if not self.run_dir:
            return {}
        try:
            return json.loads((self.run_dir / "decisions.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save_decision(self, key: str, decision: str, note: str) -> Dict[str, Any]:
        with self.lock:
            decisions = self.load_decisions()
            decisions[key] = {
                "decision": decision,
                "note": note[:500],
                "at": datetime.now().isoformat(timespec="seconds"),
            }
            (self.run_dir / "decisions.json").write_text(
                json.dumps(decisions, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            write_decisions(self.run_dir, decisions)
            return decisions[key]


def make_handler(state: AppState):
    class Handler(BaseHTTPRequestHandler):
        server_version = "reconcile"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send(self, status: int, body: bytes, content_type: str, extra: Optional[Dict[str, str]] = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: Any) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _error(self, status: int, message: str) -> None:
            self._json(status, {"ok": False, "error": message})

        def _authorised(self) -> bool:
            if not state.credentials:
                return True
            header = self.headers.get("Authorization", "")
            if not header.startswith("Basic "):
                return False
            try:
                user, _, password = base64.b64decode(header[6:]).decode("utf-8").partition(":")
            except (ValueError, UnicodeDecodeError):
                return False
            expected_user, expected_password = state.credentials
            return hmac.compare_digest(user, expected_user) and hmac.compare_digest(password, expected_password)

        def _require_login(self) -> None:
            self._send(
                HTTPStatus.UNAUTHORIZED,
                b'{"ok": false, "error": "Sign in to use the reconciliation workbench."}',
                "application/json; charset=utf-8",
                {"WWW-Authenticate": 'Basic realm="Reconciliation workbench", charset="UTF-8"'},
            )

        def _same_origin(self) -> bool:
            origin = self.headers.get("Origin")
            if not origin:
                return True
            return urlparse(origin).netloc == self.headers.get("Host", "")

        def _read_body(self) -> Optional[bytes]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return None
            if length <= 0 or length > MAX_UPLOAD_BYTES:
                return None
            return self.rfile.read(length)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/healthz":
                self._json(HTTPStatus.OK, {"ok": True})
                return
            if not self._authorised():
                self._require_login()
                return
            if path in ("/", "/index.html"):
                page = WEB_DIR / "index.html"
                if not page.exists():
                    self._error(HTTPStatus.NOT_FOUND, "web/index.html is missing")
                    return
                self._send(HTTPStatus.OK, page.read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/report":
                report = state.load_report()
                if report is None:
                    self._error(HTTPStatus.NOT_FOUND, "No reconciliation has been run yet.")
                    return
                self._json(HTTPStatus.OK, report)
            elif path == "/api/decisions":
                self._json(HTTPStatus.OK, state.load_decisions())
            elif path == "/api/sample":
                self._json(HTTPStatus.OK, {"available": state.sample_files() is not None})
            elif path.startswith("/api/download/"):
                name = path.rsplit("/", 1)[-1]
                target = state.run_dir / name if state.run_dir else None
                if name not in DOWNLOADS or target is None or not target.exists():
                    self._error(HTTPStatus.NOT_FOUND, "File not found.")
                    return
                self._send(
                    HTTPStatus.OK,
                    target.read_bytes(),
                    DOWNLOADS[name],
                    {"Content-Disposition": f'attachment; filename="{name}"'},
                )
            else:
                self._error(HTTPStatus.NOT_FOUND, "Not found.")

        def do_POST(self) -> None:
            if not self._authorised():
                self._require_login()
                return
            if not self._same_origin():
                self._error(HTTPStatus.FORBIDDEN, "Cross-origin requests are not allowed.")
                return
            path = urlparse(self.path).path
            if path in ("/api/upload/pdf", "/api/upload/erp"):
                self._upload(path.rsplit("/", 1)[-1])
            elif path == "/api/run":
                self._run()
            elif path == "/api/decisions":
                self._decide()
            else:
                self._error(HTTPStatus.NOT_FOUND, "Not found.")

        def _upload(self, kind: str) -> None:
            body = self._read_body()
            if body is None:
                self._error(HTTPStatus.BAD_REQUEST, "Empty or oversized upload (limit 50 MB).")
                return
            expected = ".pdf" if kind == "pdf" else ".xlsx"
            name = _safe_name(self.headers.get("X-File-Name", ""), f"upload{expected}")
            if not name.lower().endswith(expected):
                self._error(HTTPStatus.BAD_REQUEST, f"Expected a {expected} file.")
                return
            signature = body[:4]
            if (kind == "pdf" and signature != b"%PDF") or (kind == "erp" and signature != b"PK\x03\x04"):
                self._error(HTTPStatus.BAD_REQUEST, f"The file is not a valid {expected} document.")
                return
            state.upload_dir.mkdir(parents=True, exist_ok=True)
            target = state.upload_dir / f"{kind}-{name}"
            target.write_bytes(body)
            setattr(state, kind, target)
            self._json(HTTPStatus.OK, {"ok": True, "name": name})

        def _run(self) -> None:
            body = self._read_body() or b"{}"
            try:
                options = json.loads(body.decode("utf-8"))
            except ValueError:
                options = {}
            if options.get("sample"):
                files = state.sample_files()
                if not files:
                    self._error(HTTPStatus.NOT_FOUND, "The bundled sample files are not available.")
                    return
                pdf_path, erp_path = files["pdf"], files["erp"]
            else:
                pdf_path, erp_path = state.pdf, state.erp
            if not pdf_path or not erp_path:
                self._error(HTTPStatus.BAD_REQUEST, "Choose both a supplier PDF and an ERP workbook first.")
                return
            with state.lock:
                try:
                    reconciliation, paths, runtime = run(str(pdf_path), str(erp_path), str(state.out_dir))
                except Exception as error:
                    self._error(HTTPStatus.UNPROCESSABLE_ENTITY, f"The files could not be reconciled: {error}")
                    return
                state.run_dir = paths["json"].parent
            self._json(
                HTTPStatus.OK,
                {"ok": True, "documents": len(reconciliation.results), "runtime_seconds": round(runtime, 2)},
            )

        def _decide(self) -> None:
            body = self._read_body()
            try:
                payload = json.loads((body or b"").decode("utf-8"))
                key = str(payload["key"])
                decision = str(payload["decision"])
                note = str(payload.get("note", ""))
            except (ValueError, KeyError):
                self._error(HTTPStatus.BAD_REQUEST, "Expected JSON with key, decision and optional note.")
                return
            if decision not in DECISIONS:
                self._error(HTTPStatus.BAD_REQUEST, f"decision must be one of {', '.join(DECISIONS)}.")
                return
            report = state.load_report()
            if report is None or key not in {doc["key"] for doc in report["documents"]}:
                self._error(HTTPStatus.NOT_FOUND, "That document is not part of the current reconciliation.")
                return
            saved = state.save_decision(key, decision, note)
            self._json(HTTPStatus.OK, {"ok": True, "saved": saved, "payment": state.load_report()["payment"]})

    return Handler


def serve(host: str, port: int, out_dir: str) -> None:
    credentials = configured_credentials()
    state = AppState(Path(out_dir).resolve(), credentials)
    httpd = ThreadingHTTPServer((host, port), make_handler(state))
    print(f"Reconciliation workbench running at http://{host}:{port}  (Ctrl+C to stop)", flush=True)
    if credentials:
        print(f"Sign-in required (user: {credentials[0]}).", flush=True)
    elif host not in LOOPBACK_HOSTS:
        print(
            "Warning: reachable from the network without a password. "
            "Set RECONCILE_PASSWORD (and optionally RECONCILE_USER) to require sign-in.",
            flush=True,
        )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
