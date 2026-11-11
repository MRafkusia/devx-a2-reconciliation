"""Command line entry point: ``python -m reconcile run`` and ``python -m reconcile serve``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import results as r
from .pdf_extract import ocr_available
from .pipeline import run

TESSERACT_MISSING = (
    "Tesseract OCR is not installed, so scanned invoice pages cannot be read.\n"
    "Install it, then run the command again:\n"
    "  macOS:         brew install tesseract\n"
    "  Ubuntu/Debian: sudo apt install tesseract-ocr\n"
    "  Windows:       https://github.com/UB-Mannheim/tesseract/wiki\n"
    "To skip OCR on purpose (scanned pages will be flagged for review), add --no-ocr to the run command."
)


def _print_summary(reconciliation: r.Reconciliation, paths, runtime: float) -> None:
    totals = reconciliation.totals
    report_position = json.loads(paths["json"].read_text(encoding="utf-8"))["payment"]
    print(f"PDF: {reconciliation.pdf_file}  ERP: {reconciliation.erp_file}")
    print(f"{totals.pdf_documents} PDF documents, {totals.erp_entries} ERP entries, {runtime:.1f}s")
    for result in reconciliation.results:
        print(f"  {result.number:<26} {result.status:<26} {result.difference:>+15,}")
    print(
        f"PDF total {totals.pdf_total:,}  ERP total {totals.erp_total:,}  "
        f"difference {totals.difference:+,}  unexplained {totals.unexplained:,}"
    )
    cleared, held = report_position["cleared"], report_position["held"]
    print(f"Cleared for payment: {cleared['documents']} documents, IDR {cleared['amount']:,}")
    print(f"On hold until reviewed: {held['documents']} documents, IDR {held['erp_amount']:,} booked in the ERP")
    print(f"Reports written to {paths['json'].parent}")
    print(f"Start with {paths['summary'].name}, then {paths['xlsx'].name}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="reconcile", description="Supplier invoice vs ERP reconciliation")
    commands = parser.add_subparsers(dest="command", required=True)

    run_parser = commands.add_parser("run", help="reconcile one supplier PDF against one ERP export")
    run_parser.add_argument("--pdf", required=True, help="supplier invoice PDF")
    run_parser.add_argument("--erp", required=True, help="ERP export workbook (.xlsx)")
    run_parser.add_argument("--out", default="output", help="output directory (default: output)")
    run_parser.add_argument("--no-ocr", action="store_true", help="do not OCR scanned pages; flag them for review")

    serve_parser = commands.add_parser("serve", help="start the local web interface")
    serve_parser.add_argument("--host", default=os.environ.get("RECONCILE_HOST", "127.0.0.1"))
    serve_parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    serve_parser.add_argument("--out", default="output")

    arguments = parser.parse_args(argv)
    skip_ocr = arguments.command == "run" and arguments.no_ocr
    if not skip_ocr and not ocr_available():
        print(f"Error: {TESSERACT_MISSING}", file=sys.stderr)
        return 1

    if arguments.command == "run":
        for label, path in (("PDF", arguments.pdf), ("ERP workbook", arguments.erp)):
            if not Path(path).is_file():
                print(f"Error: the {label} file was not found: {path}", file=sys.stderr)
                return 2
        try:
            reconciliation, paths, runtime = run(arguments.pdf, arguments.erp, arguments.out, not arguments.no_ocr)
        except Exception as error:
            print(f"Error: the files could not be reconciled: {error}", file=sys.stderr)
            return 2
        _print_summary(reconciliation, paths, runtime)
        return 0

    from .server import serve

    serve(arguments.host, arguments.port, arguments.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
