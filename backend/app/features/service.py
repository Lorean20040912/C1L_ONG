"""Profilurile: ce pornește fiecare răspuns din expert și ce e activ la o dată (docs/13 §3)."""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalogs.models import Account
from app.core.enums import AccountingMethod, AccountKind, EntityType
from app.features.models import CoaTemplate, Feature, OrganizationFeature

SINGLE_ENTRY_TYPES = {EntityType.ii, EntityType.gt}
NGO_TYPES = {EntityType.ngo_association, EntityType.ngo_foundation, EntityType.ngo_other}
ACTIVITIES = {"retail", "wholesale", "catering", "production", "services", "accommodation", "agriculture", "grants"}
TAX_REGIMES = {"general", "ivao_sme", "gt", "ngo", "independent_activity"}


@dataclass(frozen=True)
class Answers:
    entity_type: EntityType
    accounting_method: AccountingMethod
    vat_payer: bool = False
    activities: frozenset[str] = frozenset()
    has_employees: bool = False


def default_method(entity_type: EntityType) -> AccountingMethod:
    return AccountingMethod.single_entry if entity_type in SINGLE_ENTRY_TYPES else AccountingMethod.double_entry


def propose_regime(entity_type: EntityType) -> str:
    if entity_type in NGO_TYPES:
        return "ngo"
    return {EntityType.gt: "gt", EntityType.ii: "independent_activity"}.get(entity_type, "general")


def coa_template_code(entity_type: EntityType, method: AccountingMethod) -> str:
    if method == AccountingMethod.single_entry:
        return "ii_single_entry"
    return "ngo" if entity_type in NGO_TYPES else "general"


def _matches(rule: dict | None, a: Answers) -> bool:
    if not rule:
        return False
    return bool(
        rule.get("always")
        or a.entity_type.value in rule.get("entity_types", [])
        or (rule.get("vat") and a.vat_payer)
        or (rule.get("employees") and a.has_employees)
        or a.activities & set(rule.get("activities", []))
    )


def propose_features(db: Session, a: Answers) -> list[Feature]:
    """Funcționalitățile propuse după răspunsuri; regulile stau în `features.default_for`."""
    rows = db.scalars(select(Feature).order_by(Feature.code)).all()
    # metoda aleasă hotărăște între partida dublă și cea simplă, indiferent de tipul entității
    method_code = "single_entry" if a.accounting_method == AccountingMethod.single_entry else "double_entry"
    other = "double_entry" if method_code == "single_entry" else "single_entry"
    return [f for f in rows if f.code != other and (f.code == method_code or _matches(f.default_for, a))]


def active_features(db: Session, organization_id: uuid.UUID, on: date) -> list[Feature]:
    return list(
        db.scalars(
            select(Feature)
            .join(OrganizationFeature, OrganizationFeature.feature_code == Feature.code)
            .where(
                OrganizationFeature.organization_id == organization_id,
                OrganizationFeature.enabled_from <= on,
                (OrganizationFeature.enabled_to.is_(None)) | (OrganizationFeature.enabled_to >= on),
            )
            .order_by(Feature.code)
        )
    )


def copy_coa_template(db: Session, organization_id: uuid.UUID, code: str) -> int:
    """Copiază cea mai nouă versiune a șablonului în `accounts`; întoarce numărul de conturi create."""
    tpl = db.scalar(select(CoaTemplate).where(CoaTemplate.code == code).order_by(CoaTemplate.version.desc()))
    if tpl is None:
        return 0
    for item in tpl.accounts:
        db.add(
            Account(
                organization_id=organization_id,
                code=item["code"],
                name=item["name"],
                account_kind=AccountKind(item["kind"]),
            )
        )
    db.flush()
    return len(tpl.accounts)
