import openpyxl

from reconcile.erp_load import load_erp


def build_workbook(path):
    workbook = openpyxl.Workbook()
    invoices = workbook.active
    invoices.title = "Supplier docs"
    invoices.append(["Grand Total", "Posted By", "Entry ID", "Vendor", "Vendor Inv. No", "Doc Date", "PO No",
                     "Curr", "Subtotal", "DPP", "PPN", "Doc Status"])
    invoices.append(["3,323,676", "u1", "E-1", "PT PRIMA", "PKI-INV-2026-09-0141", "09/13/2026", "PO-1",
                     "IDR", 2994303, 2744778, 329373, "Posted"])
    lines = workbook.create_sheet("Detail")
    lines.append(["Item Code", "Entry ID", "Line", "Qty", "Unit Price", "Disc %", "Line Amount", "Item Description"])
    lines.append(["LKB-48", "E-1", 1, 99, 13900, 10, 1238490, "TAPE"])
    credit = workbook.create_sheet("Credits")
    credit.append(["Entry ID", "Vendor", "Vendor CN No", "Doc Date", "Original Invoice", "Curr", "Subtotal",
                   "DPP", "PPN", "Grand Total", "Doc Status"])
    credit.append(["E-2", "PT PRIMA", "PKI/CN/1", "2026-09-15", "PKI/INV/OLD", "IDR", 876000, 803000, 96360, 972360, "Posted"])
    credit_lines = workbook.create_sheet("Credit detail")
    credit_lines.append(["Entry ID", "Line", "Item Code", "Qty", "Unit Price", "Disc %", "Line Amount"])
    credit_lines.append(["E-2", 1, "PK-A4-70-RM", -15, 44000, 0, -660000])
    workbook.create_sheet("Notes").append(["Exported at", "today"])
    workbook.save(path)


def test_sheets_and_columns_are_recognised_by_their_headers(tmp_path):
    path = tmp_path / "erp.xlsx"
    build_workbook(path)
    extraction = load_erp(str(path))

    assert extraction.sheets == {
        "Supplier docs": "invoices", "Detail": "lines", "Credits": "credit_notes",
        "Credit detail": "lines", "Notes": "ignored",
    }
    invoice = next(doc for doc in extraction.documents if not doc.is_credit_note)
    assert invoice.total == 3323676
    assert invoice.entry_id == "E-1" and invoice.po == "PO-1"
    assert invoice.date is None and invoice.date_raw == "09/13/2026"
    assert "total stored as text" in invoice.normalised
    assert len(invoice.lines) == 1 and invoice.lines[0].amount == 1238490
    assert invoice.sources["total"] == "Supplier docs!A2"


def test_credit_notes_are_forced_negative(tmp_path):
    path = tmp_path / "erp.xlsx"
    build_workbook(path)
    note = next(doc for doc in load_erp(str(path)).documents if doc.is_credit_note)
    assert (note.subtotal, note.total) == (-876000, -972360)
    assert note.lines[0].amount == -660000 and note.lines[0].quantity == 15
    assert note.reference == "PKI/INV/OLD"


def test_sample_export_loads_all_entries(sample_erp):
    extraction = load_erp(sample_erp)
    assert len(extraction.documents) == 16
    assert sum(len(doc.lines) for doc in extraction.documents) == 96
