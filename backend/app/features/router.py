from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import ADMIN_ROLES, OrgContext, get_current_user, get_org_context
from app.auth.models import OrganizationMember, User
from app.core.db import get_db
from app.core.enums import AccountingMethod, UserRole
from app.features import service
from app.features.models import Feature, OrganizationFeature, OrganizationTaxRegime
from app.features.schemas import (
    FeatureDisable,
    FeatureEnable,
    FeatureOut,
    OrgFeatureOut,
    UiProfile,
    WizardAnswers,
    WizardCreate,
    WizardPreview,
    WizardResult,
)
from app.workspaces.models import Organization, Workspace
from app.workspaces.schemas import OrganizationBrief, WorkspaceOut

router = APIRouter(tags=["profiluri"])

# schimbarea metodului de evidență nu se face prin comutarea unei funcționalități
METHOD_FEATURES = {"double_entry", "single_entry"}


def _out(f: Feature) -> FeatureOut:
    return FeatureOut(code=f.code, name=f.name, modules=f.modules, default_for=f.default_for)


def _answers(body: WizardAnswers) -> service.Answers:
    bad = set(body.activities) - service.ACTIVITIES
    if bad:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Genuri de activitate necunoscute: {', '.join(sorted(bad))}")
    method = body.accounting_method or service.default_method(body.entity_type)
    if method == AccountingMethod.single_entry and body.entity_type not in service.SINGLE_ENTRY_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Partida simplă e posibilă doar pentru ÎI și GȚ")
    return service.Answers(body.entity_type, method, body.vat_payer, frozenset(body.activities), body.has_employees)


@router.get("/features", response_model=list[FeatureOut])
def feature_catalog(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[FeatureOut]:
    return [_out(f) for f in db.scalars(select(Feature).order_by(Feature.code))]


@router.post("/workspaces/wizard/preview", response_model=WizardPreview)
def wizard_preview(
    body: WizardAnswers, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> WizardPreview:
    """Rezumatul expertului: ce se pornește după răspunsuri („Vor fi pornite: …”)."""
    a = _answers(body)
    return WizardPreview(
        accounting_method=a.accounting_method,
        tax_regime=service.propose_regime(a.entity_type),
        coa_template=service.coa_template_code(a.entity_type, a.accounting_method),
        features=[_out(f) for f in service.propose_features(db, a)],
    )


@router.post("/workspaces/wizard", response_model=WizardResult, status_code=status.HTTP_201_CREATED)
def wizard_create(
    body: WizardCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> WizardResult:
    a = _answers(body)
    if db.scalar(select(Organization.id).where(Organization.idno == body.idno)):
        raise HTTPException(status.HTTP_409_CONFLICT, "O organizație cu acest IDNO există deja")
    regime = body.tax_regime or service.propose_regime(a.entity_type)
    if regime not in service.TAX_REGIMES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Regim fiscal necunoscut")
    if body.vat_payer and body.vat_payer_from is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Indicați data de la care e plătitor de TVA")

    codes = [f.code for f in service.propose_features(db, a)] if body.features is None else list(dict.fromkeys(body.features))
    known = set(db.scalars(select(Feature.code)))
    if set(codes) - known:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Funcționalitate necunoscută")
    method_code = "single_entry" if a.accounting_method == AccountingMethod.single_entry else "double_entry"
    # metoda de evidență a organizației nu poate fi contrazisă de lista de funcționalități
    codes = [c for c in codes if c not in METHOD_FEATURES] + [method_code]

    start = body.start_date or date.today()
    ws = Workspace(name=body.name, created_by=user.id, source=body.source)
    db.add(ws)
    db.flush()
    org = Organization(
        workspace_id=ws.id,
        name=body.organization_name,
        idno=body.idno,
        entity_type=body.entity_type,
        accounting_method=a.accounting_method,
        vat_payer_from=body.vat_payer_from if body.vat_payer else None,
    )
    db.add(org)
    db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=UserRole.admin))
    for code in codes:
        db.add(OrganizationFeature(organization_id=org.id, feature_code=code, enabled_from=start))
    db.add(OrganizationTaxRegime(organization_id=org.id, regime_code=regime, valid_from=start, basis="expertul „Bază nouă”"))
    created = service.copy_coa_template(db, org.id, service.coa_template_code(a.entity_type, a.accounting_method))
    write_audit(
        db,
        action="create",
        entity="workspaces",
        entity_id=ws.id,
        organization_id=org.id,
        user_id=user.id,
        new_values={"name": ws.name, "idno": org.idno, "features": codes, "tax_regime": regime},
    )
    db.commit()
    return WizardResult(
        workspace=WorkspaceOut(
            id=ws.id,
            name=ws.name,
            source=ws.source,
            created_at=ws.created_at,
            organizations=[
                OrganizationBrief(
                    id=org.id,
                    name=org.name,
                    idno=org.idno,
                    entity_type=org.entity_type,
                    accounting_method=org.accounting_method,
                    role=UserRole.admin,
                )
            ],
        ),
        features=codes,
        accounts_created=created,
    )


@router.get("/organizations/{organization_id}/features", response_model=list[OrgFeatureOut])
def organization_features(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[OrgFeatureOut]:
    """Administrare → Funcționalitate: toate perioadele de activare ale organizației."""
    rows = db.execute(
        select(OrganizationFeature, Feature.name)
        .join(Feature, Feature.code == OrganizationFeature.feature_code)
        .where(OrganizationFeature.organization_id == ctx.organization_id)
        .order_by(Feature.name, OrganizationFeature.enabled_from)
    ).all()
    return [
        OrgFeatureOut(
            id=r.id, feature_code=r.feature_code, name=name, enabled_from=r.enabled_from, enabled_to=r.enabled_to
        )
        for r, name in rows
    ]


def _open_row(db: Session, organization_id, code: str) -> OrganizationFeature | None:
    return db.scalar(
        select(OrganizationFeature).where(
            OrganizationFeature.organization_id == organization_id,
            OrganizationFeature.feature_code == code,
            OrganizationFeature.enabled_to.is_(None),
        )
    )


@router.post("/organizations/{organization_id}/features", response_model=OrgFeatureOut, status_code=status.HTTP_201_CREATED)
def enable_feature(
    body: FeatureEnable, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> OrgFeatureOut:
    ctx.require(ADMIN_ROLES)
    feature = db.get(Feature, body.feature_code)
    if feature is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Funcționalitate necunoscută")
    if feature.code in METHOD_FEATURES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Metoda de evidență nu se schimbă de aici")
    if _open_row(db, ctx.organization_id, feature.code):
        raise HTTPException(status.HTTP_409_CONFLICT, "Funcționalitatea este deja pornită")
    clash = db.scalar(
        select(OrganizationFeature.id).where(
            OrganizationFeature.organization_id == ctx.organization_id,
            OrganizationFeature.feature_code == feature.code,
            OrganizationFeature.enabled_to >= body.enabled_from,
        )
    )
    if clash:
        raise HTTPException(status.HTTP_409_CONFLICT, "Data se suprapune cu o perioadă anterioară de activare")
    row = OrganizationFeature(
        organization_id=ctx.organization_id, feature_code=feature.code, enabled_from=body.enabled_from
    )
    db.add(row)
    db.flush()
    write_audit(
        db,
        action="enable",
        entity="organization_features",
        entity_id=row.id,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        new_values={"feature": feature.code, "from": body.enabled_from.isoformat()},
    )
    db.commit()
    return OrgFeatureOut(
        id=row.id, feature_code=feature.code, name=feature.name, enabled_from=row.enabled_from, enabled_to=None
    )


@router.post("/organizations/{organization_id}/features/{feature_code}/disable", response_model=OrgFeatureOut)
def disable_feature(
    feature_code: str, body: FeatureDisable, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> OrgFeatureOut:
    ctx.require(ADMIN_ROLES)
    if feature_code in METHOD_FEATURES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Metoda de evidență nu se schimbă de aici")
    row = _open_row(db, ctx.organization_id, feature_code)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Funcționalitatea nu este pornită")
    if body.enabled_to < row.enabled_from:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Data opririi e anterioară datei pornirii")
    row.enabled_to = body.enabled_to
    write_audit(
        db,
        action="disable",
        entity="organization_features",
        entity_id=row.id,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        new_values={"feature": feature_code, "to": body.enabled_to.isoformat()},
    )
    name = db.scalar(select(Feature.name).where(Feature.code == feature_code))
    db.commit()
    return OrgFeatureOut(
        id=row.id, feature_code=feature_code, name=name or feature_code, enabled_from=row.enabled_from, enabled_to=row.enabled_to
    )


@router.get("/organizations/{organization_id}/ui-profile", response_model=UiProfile)
def ui_profile(
    on: date | None = None, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> UiProfile:
    """Ce secțiuni și ecrane arată interfața: tot ce e legat de o funcționalitate apare doar dacă e pornită."""
    on = on or date.today()
    active = service.active_features(db, ctx.organization_id, on)
    everything = db.scalars(select(Feature)).all()

    def collect(features, key: str) -> list[str]:
        return sorted({x for f in features for x in f.modules.get(key, [])})

    return UiProfile(
        enabled=[f.code for f in active],
        gated_sections=collect(everything, "sections"),
        visible_sections=collect(active, "sections"),
        gated_screens=collect(everything, "screens"),
        visible_screens=collect(active, "screens"),
    )
