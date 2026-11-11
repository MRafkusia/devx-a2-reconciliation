from datetime import date
from decimal import Decimal

from reconcile import rules
from reconcile.models import CREDIT_NOTE, INVOICE, Document, Line
from reconcile.normalize import normalise_key


def make_line(number, sku, qty, price, discount=0, amount=None, source="test"):
    computed = rules.line_amount(qty, price, discount) if amount is None else amount
    return Line(
        number=number,
        sku=sku,
        description=sku,
        quantity=Decimal(str(qty)),
        unit="pcs",
        unit_price=price,
        discount_pct=Decimal(str(discount)),
        amount=computed,
        source=source,
    )


def make_document(side, number, lines, po="PO-1", day=date(2026, 9, 1), doc_type=INVOICE, entry_id="", **overrides):
    sign = -1 if doc_type == CREDIT_NOTE else 1
    lines = [Line(**{**line.__dict__, "amount": sign * abs(line.amount)}) for line in lines]
    subtotal = sum(line.amount for line in lines)
    tax = rules.tax_breakdown(subtotal)
    document = Document(
        side=side,
        doc_type=doc_type,
        number=number,
        key=normalise_key(number),
        date=day,
        date_raw=day.isoformat(),
        po=po if doc_type == INVOICE else "",
        reference="INV-ORIG" if doc_type == CREDIT_NOTE else "",
        vendor="PT TEST SUPPLIER",
        subtotal=tax.subtotal,
        dpp=tax.dpp,
        ppn=tax.ppn,
        total=tax.total,
        lines=lines,
        entry_id=entry_id,
        erp_status="Posted" if side == "erp" else "",
        pages=[1] if side == "pdf" else [],
    )
    for name, value in overrides.items():
        setattr(document, name, value)
    return document
