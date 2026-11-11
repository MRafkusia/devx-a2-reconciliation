"""Normalisation of identifiers, dates and numbers found in invoices and ERP exports."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

THOUSANDS_ONLY = re.compile(r"^\d{1,3}([.,]\d{3})+$")
PLAIN_DIGITS = re.compile(r"^\d+$")
THOUSANDS_WITH_DECIMALS = re.compile(r"^\d{1,3}([.,]\d{3})*[.,]\d{1,2}$")


class NormalisationError(ValueError):
    """Raised when a value cannot be read safely."""


def parse_idr(value: Any) -> Optional[int]:
    """Read a whole-rupiah amount from a number or from text such as '1.238.490' or '15,619,088'."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise NormalisationError(f"not an amount: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, (float, Decimal)):
        decimal_value = Decimal(str(value))
        if decimal_value != decimal_value.to_integral_value():
            raise NormalisationError(f"amount has a fractional part: {value!r}")
        return int(decimal_value)

    text = str(value).strip()
    if not text:
        return None
    negative = text.startswith("-") or (text.startswith("(") and text.endswith(")"))
    text = re.sub(r"(?i)\b(rp|idr)\b\.?", "", text)
    text = re.sub(r"[\s ()\-+]", "", text)
    if not text:
        return None

    if PLAIN_DIGITS.match(text):
        magnitude = int(text)
    elif THOUSANDS_ONLY.match(text):
        magnitude = int(re.sub(r"[.,]", "", text))
    elif THOUSANDS_WITH_DECIMALS.match(text):
        integer_part, decimal_part = re.split(r"[.,](?=\d{1,2}$)", text)
        if int(decimal_part) != 0:
            raise NormalisationError(f"amount has a fractional part: {value!r}")
        magnitude = int(re.sub(r"[.,]", "", integer_part))
    else:
        raise NormalisationError(f"cannot read amount: {value!r}")
    return -magnitude if negative else magnitude


def parse_decimal(value: Any) -> Optional[Decimal]:
    """Read a percentage or quantity that may use a decimal comma ('2,5')."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise NormalisationError(f"not a number: {value!r}")
    if isinstance(value, (int, Decimal)):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    text = str(value).strip().replace(" ", "").replace(" ", "")
    if not text:
        return None
    text = text.replace("%", "")
    if THOUSANDS_ONLY.match(text) and "." in text and "," not in text:
        text = text.replace(".", "")
    text = text.replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation as error:
        raise NormalisationError(f"cannot read number: {value!r}") from error


def normalise_key(document_number: Any) -> str:
    """Comparison key for a document number: upper case, letters and digits only."""
    return re.sub(r"[^A-Z0-9]", "", str(document_number or "").upper())


def normalise_reference(reference: Any) -> str:
    return normalise_key(reference)


def normalise_sku(sku: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(sku or "").upper())


def normalise_vendor(name: Any) -> str:
    cleaned = re.sub(r"[^A-Z0-9 ]", " ", str(name or "").upper())
    cleaned = re.sub(r"\b(PT|CV|TBK|UD)\b", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


@dataclass(frozen=True)
class ParsedDate:
    value: Optional[date]
    ambiguous: bool = False


def _valid(year: int, month: int, day: int) -> Optional[date]:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_date(raw: Any, hint: Optional[date] = None, day_first: bool = True) -> ParsedDate:
    """Read a date from a cell value or text.

    ISO dates and real date cells are unambiguous. For 'aa/bb/yyyy' both day-first and
    month-first readings are tried: a single valid reading wins, two valid readings are
    settled with ``hint`` (the date on the other document), otherwise ``day_first`` decides
    and the result is flagged ambiguous.
    """
    if raw is None or raw == "":
        return ParsedDate(None)
    if isinstance(raw, datetime):
        return ParsedDate(raw.date())
    if isinstance(raw, date):
        return ParsedDate(raw)

    text = str(raw).strip()
    iso = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[T\s].*)?$", text)
    if iso:
        return ParsedDate(_valid(int(iso.group(1)), int(iso.group(2)), int(iso.group(3))))

    parts = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$", text)
    if not parts:
        return ParsedDate(None)
    first, second, year = int(parts.group(1)), int(parts.group(2)), int(parts.group(3))
    day_month = _valid(year, second, first)
    month_day = _valid(year, first, second)

    if day_month and not month_day:
        return ParsedDate(day_month)
    if month_day and not day_month:
        return ParsedDate(month_day)
    if not day_month and not month_day:
        return ParsedDate(None)
    if day_month == month_day:
        return ParsedDate(day_month)
    if hint in (day_month, month_day):
        return ParsedDate(hint)
    return ParsedDate(day_month if day_first else month_day, ambiguous=True)


def clean_unit(unit: Any) -> str:
    """Unit of measure without OCR noise: lower-case letters only."""
    return re.sub(r"[^a-z]", "", str(unit or "").lower())
