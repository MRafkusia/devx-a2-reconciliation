from pathlib import Path

import pytest

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "sept"
SAMPLE_PDF = SAMPLE_DIR / "Supplier_Invoices_PT_Prima_Kertas_Sep2026.pdf"
SAMPLE_ERP = SAMPLE_DIR / "ERP_AP_Export_Sep2026.xlsx"


@pytest.fixture(scope="session")
def sample_pdf():
    return str(SAMPLE_PDF)


@pytest.fixture(scope="session")
def sample_erp():
    return str(SAMPLE_ERP)
