from datetime import date, datetime

import pytest

from reconcile import normalize as n


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1.238.490", 1238490),
        ("15,619,088", 15619088),
        ("Rp 3.323.676", 3323676),
        (3323676, 3323676),
        (3323676.0, 3323676),
        ("-972.360", -972360),
        ("(972.360)", -972360),
        ("1.000,00", 1000),
        ("13.900", 13900),
        ("", None),
        (None, None),
    ],
)
def test_parse_idr(raw, expected):
    assert n.parse_idr(raw) == expected


@pytest.mark.parametrize("raw", ["abc", "12.5.5.5x", 12.5, "1.234,56"])
def test_parse_idr_refuses_unreadable_or_fractional_amounts(raw):
    with pytest.raises(n.NormalisationError):
        n.parse_idr(raw)


@pytest.mark.parametrize("raw, expected", [("2,5", "2.5"), ("10", "10"), (2.5, "2.5"), ("5%", "5"), ("", None)])
def test_parse_decimal_handles_decimal_comma(raw, expected):
    result = n.parse_decimal(raw)
    assert (str(result) if result is not None else None) == expected


def test_document_numbers_compare_regardless_of_punctuation_and_case():
    assert n.normalise_key("PKI/INV/2026/09/0142") == n.normalise_key("pki-inv-2026-09-0142")


def test_vendor_names_ignore_company_prefix_and_punctuation():
    assert n.normalise_vendor("PT. PRIMA KERTAS INDONESIA") == n.normalise_vendor("Prima Kertas Indonesia")


def test_dates_accept_cells_iso_and_text():
    assert n.parse_date(datetime(2026, 9, 1)).value == date(2026, 9, 1)
    assert n.parse_date("2026-09-13").value == date(2026, 9, 13)
    assert n.parse_date("13-09-2026").value == date(2026, 9, 13)
    assert n.parse_date("09/23/2026").value == date(2026, 9, 23)


def test_ambiguous_date_is_settled_by_the_other_document():
    parsed = n.parse_date("05/06/2026", hint=date(2026, 5, 6))
    assert parsed.value == date(2026, 5, 6) and not parsed.ambiguous
    parsed = n.parse_date("05/06/2026", hint=date(2026, 6, 5))
    assert parsed.value == date(2026, 6, 5) and not parsed.ambiguous


def test_ambiguous_date_without_help_is_flagged():
    parsed = n.parse_date("05/06/2026")
    assert parsed.ambiguous


def test_impossible_date_is_none():
    assert n.parse_date("31-02-2026").value is None
