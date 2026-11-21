import uuid
from datetime import date

from pydantic import BaseModel, Field

from app.core.enums import AccountingMethod, EntityType
from app.workspaces.schemas import WorkspaceOut


class FeatureOut(BaseModel):
    code: str
    name: str
    modules: dict
    default_for: dict | None = None


class WizardAnswers(BaseModel):
    entity_type: EntityType
    accounting_method: AccountingMethod | None = Field(None, description="implicit: ÎI/GȚ partidă simplă, restul dublă")
    vat_payer: bool = False
    vat_payer_from: date | None = None
    activities: list[str] = []
    has_employees: bool = False


class WizardPreview(BaseModel):
    accounting_method: AccountingMethod
    tax_regime: str
    coa_template: str
    features: list[FeatureOut]


class WizardCreate(WizardAnswers):
    name: str = Field(min_length=1)
    organization_name: str = Field(min_length=1)
    idno: str = Field(pattern=r"^\d{13}$")
    source: str = Field("empty", pattern="^(empty|onec_import|excel_import)$")
    tax_regime: str | None = None
    features: list[str] | None = Field(None, description="lista finală din rezumat; implicit cea propusă")
    start_date: date | None = None


class WizardResult(BaseModel):
    workspace: WorkspaceOut
    features: list[str]
    accounts_created: int


class OrgFeatureOut(BaseModel):
    id: uuid.UUID
    feature_code: str
    name: str
    enabled_from: date
    enabled_to: date | None


class FeatureEnable(BaseModel):
    feature_code: str
    enabled_from: date


class FeatureDisable(BaseModel):
    enabled_to: date


class UiProfile(BaseModel):
    """`gated`: tot ce e legat de vreo funcționalitate; `visible`: ce e pornit azi.
    Interfața ascunde `gated − visible`."""

    enabled: list[str]
    gated_sections: list[str]
    visible_sections: list[str]
    gated_screens: list[str]
    visible_screens: list[str]
