"""End-to-end run: extract, match, report. Every run is kept in its own folder."""

from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Tuple

from . import results as r
from .erp_load import load_erp
from .match import reconcile
from .pdf_extract import extract_pdf
from .report import write_outputs


def new_run_dir(out_dir: Path, pdf_path: str) -> Path:
    label = re.sub(r"[^A-Za-z0-9]+", "-", Path(pdf_path).stem).strip("-")[:60] or "run"
    base = f"{datetime.now():%Y%m%d-%H%M%S}_{label}"
    candidate, attempt = out_dir / base, 1
    while candidate.exists():
        attempt += 1
        candidate = out_dir / f"{base}-{attempt}"
    return candidate


def latest_run_dir(out_dir: Path):
    if not out_dir.is_dir():
        return None
    runs = sorted(path for path in out_dir.iterdir() if path.is_dir() and (path / "report.json").exists())
    return runs[-1] if runs else None


def run(pdf_path: str, erp_path: str, out_dir: str, use_ocr: bool = True) -> Tuple[r.Reconciliation, Dict[str, Path], float]:
    started = time.perf_counter()
    pdf = extract_pdf(pdf_path, use_ocr=use_ocr)
    erp = load_erp(erp_path)
    reconciliation = reconcile(pdf, erp)
    runtime = time.perf_counter() - started
    paths = write_outputs(reconciliation, new_run_dir(Path(out_dir), pdf_path), runtime)
    return reconciliation, paths, runtime
