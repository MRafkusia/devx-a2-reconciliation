from decimal import Decimal
from fractions import Fraction

import pytest

from reconcile import rules


@pytest.mark.parametrize(
    "value, expected",
    [("2.5", 3), ("2.4999", 2), ("0.5", 1), ("-0.5", -1), ("-2.5", -3), ("1238490.0", 1238490), (Fraction(7, 2), 4)],
)
def test_round_half_up_ties_go_away_from_zero(value, expected):
    assert rules.round_half_up(value) == expected


def test_floats_are_rejected():
    with pytest.raises(TypeError):
        rules.round_half_up(2.5)


@pytest.mark.parametrize(
    "qty, price, discount, expected",
    [
        (99, 13900, 10, 1238490),
        (65, 4750, 5, 293313),
        (13, 112500, 0, 1462500),
        (130, 68000, "2.5", 8619000),
        (30, 4750, "2.5", 138938),
        (1, 250000, 0, 250000),
    ],
)
def test_line_amount_r1_matches_invoice_lines(qty, price, discount, expected):
    assert rules.line_amount(qty, price, discount) == expected


def test_line_amount_accepts_decimal_input():
    assert rules.line_amount(Decimal("65"), 4750, Decimal("5")) == 293313


def test_subtotal_is_sum_of_lines():
    assert rules.subtotal([1238490, 293313, 1462500]) == 2994303


def test_tax_breakdown_r3_r4_for_invoice_0141():
    tax = rules.tax_breakdown(2994303)
    assert (tax.dpp, tax.ppn, tax.total) == (2744778, 329373, 3323676)


def test_tax_breakdown_rounds_each_step_half_up():
    tax = rules.tax_breakdown(20484150)
    assert tax.dpp == 18777138
    assert tax.ppn == 2253257


def test_credit_note_tax_mirrors_the_invoice():
    tax = rules.tax_breakdown(-876000)
    assert (tax.dpp, tax.ppn, tax.total) == (-803000, -96360, -972360)


@pytest.mark.parametrize("difference, expected", [(0, True), (10, True), (-10, True), (11, False), (-11, False)])
def test_tolerance_is_ten_rupiah_either_way(difference, expected):
    assert rules.within_tolerance(difference) is expected
