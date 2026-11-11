"""Customer business rules R1-R5 as pure integer/fraction arithmetic.

All money is whole rupiah held as ``int``. Every rounding is half-up, applied
symmetrically so a credit note (negative amounts) rounds like its invoice.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Iterable, Union

Number = Union[int, str, Decimal, Fraction]

DPP_FACTOR = Fraction(11, 12)
PPN_RATE = Fraction(12, 100)
TOLERANCE_IDR = 10


def as_fraction(value: Number) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if isinstance(value, float):
        raise TypeError("floats are not accepted in money arithmetic; pass str, int or Decimal")
    if isinstance(value, Decimal):
        return Fraction(value)
    return Fraction(str(value))


def round_half_up(value: Number) -> int:
    """Round to a whole number, ties away from zero (0.5 -> 1, -0.5 -> -1)."""
    fraction = as_fraction(value)
    magnitude = abs(fraction)
    whole = magnitude.numerator // magnitude.denominator
    if magnitude - whole >= Fraction(1, 2):
        whole += 1
    return -whole if fraction < 0 else whole


def line_amount(quantity: Number, unit_price: Number, discount_pct: Number = 0) -> int:
    """R1: quantity x unit price x (1 - discount % / 100), rounded half-up."""
    factor = 1 - as_fraction(discount_pct) / 100
    return round_half_up(as_fraction(quantity) * as_fraction(unit_price) * factor)


def subtotal(line_amounts: Iterable[int]) -> int:
    """R2: subtotal is the sum of the line amounts."""
    return sum(line_amounts)


def dpp_nilai_lain(subtotal_amount: int) -> int:
    """R3: other tax base = subtotal x 11/12, rounded half-up."""
    return round_half_up(as_fraction(subtotal_amount) * DPP_FACTOR)


def ppn(dpp_amount: int) -> int:
    """R4: VAT = DPP x 12%, rounded half-up."""
    return round_half_up(as_fraction(dpp_amount) * PPN_RATE)


@dataclass(frozen=True)
class TaxBreakdown:
    subtotal: int
    dpp: int
    ppn: int
    total: int


def tax_breakdown(subtotal_amount: int) -> TaxBreakdown:
    """R3 and R4 applied to a subtotal; total = subtotal + PPN."""
    dpp_amount = dpp_nilai_lain(subtotal_amount)
    ppn_amount = ppn(dpp_amount)
    return TaxBreakdown(subtotal_amount, dpp_amount, ppn_amount, subtotal_amount + ppn_amount)


def within_tolerance(difference: int, tolerance: int = TOLERANCE_IDR) -> bool:
    """R5: a total difference up to the tolerance counts as rounding."""
    return abs(difference) <= tolerance
