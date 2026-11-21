"""Cursul oficial BNM pe zile: introducere manuală sau descărcare de pe bnm.md.

Cursul unei zile fără curs publicat (zi de odihnă) = ultimul curs anterior.
"""

import urllib.request
import uuid
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.bank.models import ExchangeRate

BNM_URL = "https://www.bnm.md/ro/official_exchange_rates?get_xml=1&date={date:%d.%m.%Y}"
RATE_PLACES = Decimal("0.0001")


class RateError(Exception):
    pass


def rate_on(db: Session, organization_id: uuid.UUID, currency: str, on_date: date) -> ExchangeRate | None:
    return db.scalar(
        select(ExchangeRate)
        .where(
            ExchangeRate.organization_id == organization_id,
            ExchangeRate.currency == currency.upper(),
            ExchangeRate.rate_date <= on_date,
        )
        .order_by(ExchangeRate.rate_date.desc())
        .limit(1)
    )


def save_rate(
    db: Session, organization_id: uuid.UUID, currency: str, rate_date: date, rate: Decimal, source: str = "manual"
) -> None:
    stmt = insert(ExchangeRate).values(
        organization_id=organization_id, currency=currency.upper(), rate_date=rate_date, rate=rate, source=source
    )
    db.execute(
        stmt.on_conflict_do_update(
            index_elements=["organization_id", "currency", "rate_date"],
            set_={"rate": stmt.excluded.rate, "source": stmt.excluded.source},
        )
    )


def parse_bnm_xml(data: bytes) -> dict[str, Decimal]:
    """`ValCurs/Valute` → {cod: MDL pentru o unitate}."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise RateError(f"Răspunsul BNM nu este XML valid: {exc}") from None
    rates = {}
    for valute in root.iter("Valute"):
        code = (valute.findtext("CharCode") or "").strip().upper()
        try:
            nominal = Decimal((valute.findtext("Nominal") or "1").strip())
            value = Decimal((valute.findtext("Value") or "").strip().replace(",", "."))
        except InvalidOperation:
            continue
        if code and nominal.is_finite() and value.is_finite() and nominal > 0 and value > 0:
            try:
                rates[code] = (value / nominal).quantize(RATE_PLACES)
            except InvalidOperation:
                continue
    if not rates:
        raise RateError("Răspunsul BNM nu conține cursuri")
    return rates


def download_bnm(on_date: date, timeout: float = 15) -> dict[str, Decimal]:
    try:
        with urllib.request.urlopen(BNM_URL.format(date=on_date), timeout=timeout) as response:  # noqa: S310
            return parse_bnm_xml(response.read())
    except OSError as exc:
        raise RateError(f"bnm.md nu răspunde ({exc}); introduceți cursul manual") from None
