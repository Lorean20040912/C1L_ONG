"""Granturi avansat: donatori, donatorii grantului, versiunile bugetului, tranșe (docs/02 §9a, docs/11 §2.1).

- versiune nouă de buget = liniile vechi rămân pentru istoric, execuția se compară cu versiunea
  în vigoare la data cheltuielii (`app/grants/budget.py`);
- tranșa: „recunoaștere” (Dt 234.4 — Kt 425 / 537, doar cu politica „la semnare”) și legătura cu
  ordinul de plată (încasare) care a primit-o.
"""

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import POSTING_ROLES, OrgContext, get_org_context
from app.core.db import get_db
from app.core.enums import DocumentType, PaymentDirection
from app.documents.models import Document, PaymentOrder
from app.documents.posting import _term
from app.grants.admin_router import _grant, current_version_id
from app.grants.models import BudgetLine, BudgetVersion, Donor, Grant, GrantDonor, GrantTranche
from app.posting.models import EntryLine
from app.posting.engine import PostingError, post_document, unpost_document
from app.posting.router import http_error
from app.posting.rules import OperationInput, build_lines, policy_in_force

router = APIRouter(prefix="/organizations/{organization_id}", tags=["granturi avansat"])


# ───────────────────────────── donatori ─────────────────────────────


class DonorIn(BaseModel):
    name: str = Field(min_length=1)
    country: str | None = None


class DonorOut(DonorIn):
    id: uuid.UUID
    grants_count: int = 0


def _donor(db: Session, ctx: OrgContext, donor_id: uuid.UUID | None) -> Donor:
    donor = (
        db.scalar(select(Donor).where(Donor.id == donor_id, Donor.organization_id == ctx.organization_id))
        if donor_id
        else None
    )
    if donor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Donatorul nu a fost găsit")
    return donor


def _donor_out(db: Session, donor: Donor) -> DonorOut:
    count = db.scalar(select(func.count()).select_from(GrantDonor).where(GrantDonor.donor_id == donor.id)) or 0
    return DonorOut(id=donor.id, name=donor.name, country=donor.country, grants_count=count)


@router.get("/donors", response_model=list[DonorOut])
def list_donors(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[DonorOut]:
    donors = db.scalars(select(Donor).where(Donor.organization_id == ctx.organization_id).order_by(Donor.name)).all()
    return [_donor_out(db, d) for d in donors]


def _name_free(db: Session, ctx: OrgContext, name: str, except_id: uuid.UUID | None = None) -> None:
    query = select(Donor.id).where(Donor.organization_id == ctx.organization_id, func.lower(Donor.name) == name.lower())
    if except_id:
        query = query.where(Donor.id != except_id)
    if db.scalar(query):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Donatorul „{name}” există deja")


@router.post("/donors", response_model=DonorOut, status_code=status.HTTP_201_CREATED)
def create_donor(body: DonorIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> DonorOut:
    ctx.require(POSTING_ROLES)
    _name_free(db, ctx, body.name)
    donor = Donor(organization_id=ctx.organization_id, **body.model_dump())
    db.add(donor)
    db.flush()
    write_audit(
        db, action="create", entity="donors", entity_id=donor.id, organization_id=ctx.organization_id, user_id=ctx.user.id,
        new_values=body.model_dump(mode="json"),
    )  # fmt: skip
    db.commit()
    return _donor_out(db, donor)


@router.put("/donors/{donor_id}", response_model=DonorOut)
def update_donor(
    donor_id: uuid.UUID, body: DonorIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> DonorOut:
    ctx.require(POSTING_ROLES)
    donor = _donor(db, ctx, donor_id)
    _name_free(db, ctx, body.name, except_id=donor.id)
    old = {"name": donor.name, "country": donor.country}
    donor.name, donor.country = body.name, body.country
    db.flush()
    write_audit(
        db, action="update", entity="donors", entity_id=donor.id, organization_id=ctx.organization_id, user_id=ctx.user.id,
        old_values=old, new_values=body.model_dump(mode="json"),
    )  # fmt: skip
    db.commit()
    return _donor_out(db, donor)


@router.delete("/donors/{donor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_donor(donor_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> None:
    ctx.require(POSTING_ROLES)
    donor = _donor(db, ctx, donor_id)
    if db.scalar(select(exists().where(GrantDonor.donor_id == donor.id))) or db.scalar(
        select(exists().where(GrantTranche.donor_id == donor.id))
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "Donatorul e legat de granturi sau tranșe și nu se poate șterge")
    write_audit(
        db, action="delete", entity="donors", entity_id=donor.id, organization_id=ctx.organization_id, user_id=ctx.user.id,
        old_values={"name": donor.name},
    )  # fmt: skip
    db.delete(donor)
    db.commit()


# ───────────────────────── donatorii grantului ─────────────────────────


class GrantDonorIn(BaseModel):
    donor_id: uuid.UUID
    share_percent: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)
    amount: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)


class GrantDonorOut(GrantDonorIn):
    donor_name: str


def _grant_donors(db: Session, grant_id: uuid.UUID) -> list[GrantDonorOut]:
    rows = db.execute(
        select(GrantDonor, Donor.name).join(Donor, Donor.id == GrantDonor.donor_id)
        .where(GrantDonor.grant_id == grant_id).order_by(Donor.name)
    ).all()  # fmt: skip
    return [
        GrantDonorOut(donor_id=gd.donor_id, share_percent=gd.share_percent, amount=gd.amount, donor_name=name)
        for gd, name in rows
    ]


@router.get("/grants/{grant_id}/donors", response_model=list[GrantDonorOut])
def list_grant_donors(
    grant_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> list[GrantDonorOut]:
    _grant(db, ctx, grant_id)
    return _grant_donors(db, grant_id)


@router.put("/grants/{grant_id}/donors", response_model=list[GrantDonorOut])
def set_grant_donors(
    grant_id: uuid.UUID,
    body: list[GrantDonorIn],
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> list[GrantDonorOut]:
    """Înlocuiește lista donatorilor grantului (cota și suma de participare)."""
    ctx.require(POSTING_ROLES)
    grant = _grant(db, ctx, grant_id, lock=True)
    ids = [d.donor_id for d in body]
    if len(set(ids)) != len(ids):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Un donator apare de două ori")
    for donor_id in ids:
        _donor(db, ctx, donor_id)  # 404 dacă nu aparține organizației
    if sum((d.share_percent or Decimal(0) for d in body), Decimal(0)) > 100:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Cotele donatorilor depășesc 100%")
    if sum((d.amount or Decimal(0) for d in body), Decimal(0)) > grant.total_amount:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Sumele donatorilor depășesc totalul grantului")
    old = [d.model_dump(mode="json") for d in _grant_donors(db, grant_id)]
    for existing in db.scalars(select(GrantDonor).where(GrantDonor.grant_id == grant_id)):
        db.delete(existing)
    db.flush()
    for d in body:
        db.add(GrantDonor(grant_id=grant_id, **d.model_dump()))
    db.flush()
    write_audit(
        db, action="update", entity="grant_donors", entity_id=grant_id, organization_id=ctx.organization_id, user_id=ctx.user.id,
        old_values={"donors": old}, new_values={"donors": [d.model_dump(mode="json") for d in body]},
    )  # fmt: skip
    db.commit()
    return _grant_donors(db, grant_id)


# ──────────────────────── versiunile bugetului ────────────────────────


class BudgetVersionOut(BaseModel):
    id: uuid.UUID
    version: int
    valid_from: date
    is_current: bool
    approved_document_id: uuid.UUID | None
    lines_count: int
    total_planned: Decimal


class BudgetVersionIn(BaseModel):
    valid_from: date
    approved_document_id: uuid.UUID | None = None
    # liniile noii versiuni (după cod); cele nemenționate se copiază neschimbate din versiunea curentă
    changes: dict[str, Decimal] = Field(default_factory=dict, description="cod linie → suma planificată nouă")


def _version_out(db: Session, v: BudgetVersion) -> BudgetVersionOut:
    count, total = db.execute(
        select(func.count(), func.coalesce(func.sum(BudgetLine.planned_amount), 0)).where(
            BudgetLine.budget_version_id == v.id, BudgetLine.parent_id.is_(None)
        )
    ).one()
    all_lines = db.scalar(select(func.count()).select_from(BudgetLine).where(BudgetLine.budget_version_id == v.id))
    return BudgetVersionOut(
        id=v.id,
        version=v.version,
        valid_from=v.valid_from,
        is_current=bool(v.is_current),
        approved_document_id=v.approved_document_id,
        lines_count=all_lines or count,
        total_planned=total,
    )


@router.get("/grants/{grant_id}/budget-versions", response_model=list[BudgetVersionOut])
def list_budget_versions(
    grant_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> list[BudgetVersionOut]:
    _grant(db, ctx, grant_id)
    versions = db.scalars(select(BudgetVersion).where(BudgetVersion.grant_id == grant_id).order_by(BudgetVersion.version))
    return [_version_out(db, v) for v in versions]


@router.post(
    "/grants/{grant_id}/budget-versions", response_model=BudgetVersionOut, status_code=status.HTTP_201_CREATED
)
def create_budget_version(
    grant_id: uuid.UUID,
    body: BudgetVersionIn,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> BudgetVersionOut:
    """Modificare de buget aprobată de donator: versiune nouă (copiază liniile curente, aplică `changes`).

    Prima versiune a unui grant „vechi” (cu linii fără versiune) preia acele linii ca versiunea 1."""
    ctx.require(POSTING_ROLES)
    grant = _grant(db, ctx, grant_id, lock=True)
    if body.approved_document_id and db.scalar(
        select(Document.id).where(
            Document.id == body.approved_document_id, Document.organization_id == ctx.organization_id
        )
    ) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Documentul nu aparține organizației")
    last = db.scalar(select(func.max(BudgetVersion.version)).where(BudgetVersion.grant_id == grant_id))
    if last is None:
        v1 = BudgetVersion(grant_id=grant_id, version=1, valid_from=grant.start_date, is_current=True)
        db.add(v1)
        db.flush()
        for line in db.scalars(select(BudgetLine).where(BudgetLine.grant_id == grant_id)):
            line.budget_version_id = v1.id
        db.flush()
        last = 1
    current_id = current_version_id(db, grant_id)
    current = db.get(BudgetVersion, current_id)
    if body.valid_from <= current.valid_from:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Data de aplicare trebuie să fie după cea a versiunii curente"
        )
    old_lines = db.scalars(select(BudgetLine).where(BudgetLine.budget_version_id == current_id)).all()
    unknown = set(body.changes) - {ln.code for ln in old_lines}
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Linii necunoscute: {', '.join(sorted(unknown))}")
    for code, amount in body.changes.items():
        if amount < 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Suma liniei {code} e negativă")
    current.is_current = False
    new = BudgetVersion(
        grant_id=grant_id, version=last + 1, valid_from=body.valid_from,
        approved_document_id=body.approved_document_id, is_current=True,
    )  # fmt: skip
    db.add(new)
    db.flush()
    mapping: dict[uuid.UUID, BudgetLine] = {}
    for line in old_lines:
        planned = body.changes.get(line.code, line.planned_amount)
        donor_amount, cofinancing = line.donor_amount, line.cofinancing_amount
        if line.code in body.changes:  # suma s-a schimbat: contribuțiile pe linie se completează la nevoie
            cofinancing = None if cofinancing is None else min(cofinancing, planned)
            donor_amount = None if donor_amount is None else min(donor_amount, planned)
        copy = BudgetLine(
            grant_id=grant_id, budget_version_id=new.id, code=line.code, name=line.name,
            cost_item_id=line.cost_item_id, unit=line.unit, quantity=line.quantity, unit_cost=line.unit_cost,
            planned_amount=planned, donor_amount=donor_amount, cofinancing_amount=cofinancing,
        )  # fmt: skip
        db.add(copy)
        mapping[line.id] = copy
    db.flush()
    for line in old_lines:
        if line.parent_id:
            mapping[line.id].parent_id = mapping[line.parent_id].id
    db.flush()
    write_audit(
        db, action="create", entity="budget_versions", entity_id=new.id, organization_id=ctx.organization_id, user_id=ctx.user.id,
        new_values={"version": new.version, "valid_from": body.valid_from.isoformat(), "changes": {k: str(v) for k, v in body.changes.items()}},
    )  # fmt: skip
    db.commit()
    return _version_out(db, new)


# ───────────────────────────── tranșe ─────────────────────────────

TRANCHE_STATUSES = ("planned", "recognized", "received", "cancelled")


class TrancheIn(BaseModel):
    donor_id: uuid.UUID | None = None
    planned_date: date | None = None
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    condition: str | None = None
    cancelled: bool = False


class TrancheOut(BaseModel):
    id: uuid.UUID
    grant_id: uuid.UUID
    donor_id: uuid.UUID | None
    number: int
    planned_date: date | None
    amount: Decimal
    currency: str
    condition: str | None
    status: str
    received_document_id: uuid.UUID | None
    recognition_document_id: uuid.UUID | None = None


def _tranche(db: Session, ctx: OrgContext, tranche_id: uuid.UUID, lock: bool = False) -> GrantTranche:
    query = (
        select(GrantTranche)
        .join(Grant, Grant.id == GrantTranche.grant_id)
        .where(GrantTranche.id == tranche_id, Grant.organization_id == ctx.organization_id)
    )
    tranche = db.scalar(query.with_for_update(of=GrantTranche) if lock else query)
    if tranche is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tranșa nu a fost găsită")
    return tranche


def _recognition_number(tranche: GrantTranche, grant: Grant) -> str:
    return f"TR-{grant.code}-{tranche.number}"


def _recognition_document(db: Session, organization_id: uuid.UUID, grant: Grant, tranche: GrantTranche):
    return db.scalar(
        select(Document).where(
            Document.organization_id == organization_id,
            Document.doc_number == _recognition_number(tranche, grant),
            Document.type == DocumentType.other,
        )
    )


def _tranche_out(db: Session, ctx: OrgContext, t: GrantTranche) -> TrancheOut:
    grant = db.get(Grant, t.grant_id)
    doc = _recognition_document(db, ctx.organization_id, grant, t)
    return TrancheOut(
        id=t.id, grant_id=t.grant_id, donor_id=t.donor_id, number=t.number, planned_date=t.planned_date,
        amount=t.amount, currency=t.currency, condition=t.condition, status=t.status or "planned",
        received_document_id=t.received_document_id,
        recognition_document_id=doc.id if doc is not None and doc.is_posted else None,
    )  # fmt: skip


def _check_total(db: Session, grant: Grant, amount: Decimal, except_id: uuid.UUID | None = None) -> None:
    """Verificarea din docs/02 §9a: suma tranșelor (fără cele anulate) nu depășește totalul grantului."""
    query = select(func.coalesce(func.sum(GrantTranche.amount), 0)).where(
        GrantTranche.grant_id == grant.id, GrantTranche.status != "cancelled"
    )
    if except_id:
        query = query.where(GrantTranche.id != except_id)
    if db.scalar(query) + amount > grant.total_amount:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Suma tranșelor depășește totalul grantului")


@router.get("/grants/{grant_id}/tranches", response_model=list[TrancheOut])
def list_tranches(
    grant_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> list[TrancheOut]:
    _grant(db, ctx, grant_id)
    tranches = db.scalars(select(GrantTranche).where(GrantTranche.grant_id == grant_id).order_by(GrantTranche.number))
    return [_tranche_out(db, ctx, t) for t in tranches]


@router.post("/grants/{grant_id}/tranches", response_model=TrancheOut, status_code=status.HTTP_201_CREATED)
def create_tranche(
    grant_id: uuid.UUID, body: TrancheIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> TrancheOut:
    ctx.require(POSTING_ROLES)
    grant = _grant(db, ctx, grant_id, lock=True)
    if body.donor_id:
        _donor(db, ctx, body.donor_id)
    currency = (body.currency or grant.currency).upper()
    if currency != grant.currency:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Tranșa se ține în valuta grantului")
    _check_total(db, grant, body.amount)
    number = (db.scalar(select(func.max(GrantTranche.number)).where(GrantTranche.grant_id == grant_id)) or 0) + 1
    tranche = GrantTranche(
        grant_id=grant_id, donor_id=body.donor_id, number=number, planned_date=body.planned_date,
        amount=body.amount, currency=currency, condition=body.condition, status="planned",
    )  # fmt: skip
    db.add(tranche)
    db.flush()
    write_audit(
        db, action="create", entity="grant_tranches", entity_id=tranche.id, organization_id=ctx.organization_id, user_id=ctx.user.id,
        new_values={**body.model_dump(mode="json"), "number": number},
    )  # fmt: skip
    db.commit()
    return _tranche_out(db, ctx, tranche)


@router.put("/tranches/{tranche_id}", response_model=TrancheOut)
def update_tranche(
    tranche_id: uuid.UUID, body: TrancheIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> TrancheOut:
    ctx.require(POSTING_ROLES)
    tranche = _tranche(db, ctx, tranche_id, lock=True)
    grant = _grant(db, ctx, tranche.grant_id, lock=True)
    if tranche.status in ("recognized", "received"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Tranșa recunoscută sau încasată nu se mai modifică")
    if body.donor_id:
        _donor(db, ctx, body.donor_id)
    if not body.cancelled:
        _check_total(db, grant, body.amount, except_id=tranche.id)
    old = {"amount": str(tranche.amount), "status": tranche.status, "donor_id": str(tranche.donor_id or "")}
    tranche.donor_id, tranche.planned_date, tranche.amount = body.donor_id, body.planned_date, body.amount
    tranche.condition = body.condition
    tranche.status = "cancelled" if body.cancelled else "planned"
    db.flush()
    write_audit(
        db, action="update", entity="grant_tranches", entity_id=tranche.id, organization_id=ctx.organization_id, user_id=ctx.user.id,
        old_values=old, new_values={**body.model_dump(mode="json"), "status": tranche.status},
    )  # fmt: skip
    db.commit()
    return _tranche_out(db, ctx, tranche)


@router.delete("/tranches/{tranche_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tranche(
    tranche_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> None:
    ctx.require(POSTING_ROLES)
    tranche = _tranche(db, ctx, tranche_id, lock=True)
    if tranche.status in ("recognized", "received"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Tranșa recunoscută sau încasată nu se șterge")
    write_audit(
        db, action="delete", entity="grant_tranches", entity_id=tranche.id, organization_id=ctx.organization_id, user_id=ctx.user.id,
        old_values={"number": tranche.number, "amount": str(tranche.amount)},
    )  # fmt: skip
    db.delete(tranche)
    db.commit()


class RecognizeIn(BaseModel):
    recognition_date: date | None = None  # implicit: data planificată sau azi


@router.post("/tranches/{tranche_id}/recognize", response_model=TrancheOut)
def recognize_tranche(
    tranche_id: uuid.UUID,
    body: RecognizeIn,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> TrancheOut:
    """Dt 234.4 (creanța) — Kt 425 / 537 pe suma tranșei, doar cu politica „recunoaștere la semnare” (docs/11 §2.1)."""
    ctx.require(POSTING_ROLES)
    tranche = _tranche(db, ctx, tranche_id, lock=True)
    grant = _grant(db, ctx, tranche.grant_id, lock=True)
    if tranche.status != "planned":
        raise HTTPException(status.HTTP_409_CONFLICT, "Se recunosc doar tranșele planificate")
    on_date = body.recognition_date or tranche.planned_date or date.today()
    policy = policy_in_force(db, ctx.organization_id, on_date)
    if policy is None or policy.grant_recognition != "on_signing":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Politica contabilă recunoaște grantul la încasare: tranșa se înregistrează prin ordinul de plată",
        )
    doc = _recognition_document(db, ctx.organization_id, grant, tranche)
    if doc is None:
        doc = Document(
            organization_id=ctx.organization_id, type=DocumentType.other,
            doc_number=_recognition_number(tranche, grant), doc_date=on_date,
            total_amount=tranche.amount, currency=tranche.currency, uploaded_by=ctx.user.id,
        )  # fmt: skip
        db.add(doc)
        db.flush()
    else:
        doc.doc_date = on_date
    try:
        generated = build_lines(
            db,
            organization_id=ctx.organization_id,
            document_type="grant_income",
            doc_date=on_date,
            operations=[
                OperationInput(
                    operation="recognition",
                    amount=tranche.amount,
                    attributes={"term": _term(grant, on_date)},
                    grant_id=grant.id,
                    description=f"Recunoaștere tranșa {tranche.number} {grant.code}",
                )
            ],
        )
        post_document(
            db, organization_id=ctx.organization_id, document_id=doc.id, lines=[g.line for g in generated],
            user_id=ctx.user.id, rule_refs=[f"{g.rule.id} ({g.rule.source_ref})" for g in generated],
        )  # fmt: skip
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from exc
    tranche.status = "recognized"
    db.flush()
    write_audit(
        db, action="update", entity="grant_tranches", entity_id=tranche.id, organization_id=ctx.organization_id, user_id=ctx.user.id,
        old_values={"status": "planned"}, new_values={"status": "recognized", "document_id": str(doc.id)},
    )  # fmt: skip
    db.commit()
    return _tranche_out(db, ctx, tranche)


@router.post("/tranches/{tranche_id}/unrecognize", response_model=TrancheOut)
def unrecognize_tranche(
    tranche_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> TrancheOut:
    ctx.require(POSTING_ROLES)
    tranche = _tranche(db, ctx, tranche_id, lock=True)
    grant = _grant(db, ctx, tranche.grant_id)
    if tranche.status != "recognized":
        raise HTTPException(status.HTTP_409_CONFLICT, "Tranșa nu este recunoscută")
    doc = _recognition_document(db, ctx.organization_id, grant, tranche)
    try:
        if doc is not None and doc.is_posted:
            unpost_document(db, organization_id=ctx.organization_id, document_id=doc.id, user_id=ctx.user.id)
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from exc
    tranche.status = "planned"
    db.flush()
    write_audit(
        db, action="update", entity="grant_tranches", entity_id=tranche.id, organization_id=ctx.organization_id, user_id=ctx.user.id,
        old_values={"status": "recognized"}, new_values={"status": "planned"},
    )  # fmt: skip
    db.commit()
    return _tranche_out(db, ctx, tranche)


class ReceiveIn(BaseModel):
    document_id: uuid.UUID  # ordinul de plată (încasare) înregistrat


@router.post("/tranches/{tranche_id}/receive", response_model=TrancheOut)
def receive_tranche(
    tranche_id: uuid.UUID, body: ReceiveIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> TrancheOut:
    """Leagă tranșa de încasarea înregistrată (ordin de plată de intrare pe acest grant)."""
    ctx.require(POSTING_ROLES)
    tranche = _tranche(db, ctx, tranche_id, lock=True)
    if tranche.status not in ("planned", "recognized"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Tranșa nu poate fi marcată ca încasată")
    row = db.execute(
        select(Document, PaymentOrder)
        .join(PaymentOrder, PaymentOrder.document_id == Document.id)
        .where(Document.id == body.document_id, Document.organization_id == ctx.organization_id)
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Încasarea nu a fost găsită")
    doc, order = row
    if order.direction != PaymentDirection.incoming or not doc.is_posted:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Alegeți o încasare înregistrată")
    if not db.scalar(
        select(exists().where(EntryLine.document_id == doc.id, EntryLine.grant_id == tranche.grant_id))
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Încasarea nu aparține grantului tranșei")
    if db.scalar(
        select(exists().where(GrantTranche.received_document_id == doc.id, GrantTranche.id != tranche.id))
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "Încasarea e deja legată de altă tranșă")
    old = tranche.status
    tranche.received_document_id = doc.id
    tranche.status = "received"
    db.flush()
    write_audit(
        db, action="update", entity="grant_tranches", entity_id=tranche.id, organization_id=ctx.organization_id, user_id=ctx.user.id,
        old_values={"status": old}, new_values={"status": "received", "document_id": str(doc.id)},
    )  # fmt: skip
    db.commit()
    return _tranche_out(db, ctx, tranche)
