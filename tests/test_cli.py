import pytest

from reconcile import __main__ as cli


@pytest.fixture()
def without_tesseract(monkeypatch):
    monkeypatch.setattr(cli, "ocr_available", lambda: False)


def test_run_stops_with_a_clear_message_when_tesseract_is_missing(without_tesseract, capsys, sample_pdf, sample_erp, tmp_path):
    code = cli.main(["run", "--pdf", sample_pdf, "--erp", sample_erp, "--out", str(tmp_path)])
    assert code == 1
    assert "Tesseract OCR is not installed" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


def test_serve_stops_when_tesseract_is_missing(without_tesseract, capsys):
    assert cli.main(["serve"]) == 1
    assert "brew install tesseract" in capsys.readouterr().err


def test_no_ocr_flag_runs_without_tesseract(without_tesseract, sample_pdf, sample_erp, tmp_path):
    assert cli.main(["run", "--pdf", sample_pdf, "--erp", sample_erp, "--out", str(tmp_path), "--no-ocr"]) == 0
    assert len(list(tmp_path.glob("*/report.json"))) == 1


def test_missing_input_file_gives_a_clear_error(capsys, sample_erp, tmp_path):
    assert cli.main(["run", "--pdf", "missing.pdf", "--erp", sample_erp, "--out", str(tmp_path), "--no-ocr"]) == 2
    assert "was not found" in capsys.readouterr().err


def test_unreadable_input_file_gives_a_clear_error(capsys, sample_erp, tmp_path):
    assert cli.main(["run", "--pdf", sample_erp, "--erp", sample_erp, "--out", str(tmp_path), "--no-ocr"]) == 2
    assert "could not be reconciled" in capsys.readouterr().err
