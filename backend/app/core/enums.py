"""Tipurile ENUM din PostgreSQL (database/schema.dbml).

Tipurile sunt create de migrarea Alembic; modelele doar le folosesc
(`create_type=False`).
"""

import enum

from sqlalchemy.dialects.postgresql import ENUM


class UserRole(str, enum.Enum):
    admin = "admin"
    chief_accountant = "chief_accountant"
    accountant = "accountant"
    project_manager = "project_manager"
    auditor = "auditor"


class DocumentType(str, enum.Enum):
    invoice = "invoice"
    e_invoice = "e_invoice"
    payment_order = "payment_order"
    bank_statement = "bank_statement"
    contract = "contract"
    act = "act"
    receipt = "receipt"
    individual_payment = "individual_payment"
    other = "other"


class DocumentStatus(str, enum.Enum):
    new = "new"
    ai_processed = "ai_processed"
    to_review = "to_review"
    validated = "validated"
    rejected = "rejected"


class ContractType(str, enum.Enum):
    cim = "cim"
    civil = "civil"


class EntityType(str, enum.Enum):
    srl = "srl"
    sa = "sa"
    ii = "ii"
    gt = "gt"
    ngo_association = "ngo_association"
    ngo_foundation = "ngo_foundation"
    ngo_other = "ngo_other"
    other = "other"


class AccountingMethod(str, enum.Enum):
    double_entry = "double_entry"
    single_entry = "single_entry"


class AccountKind(str, enum.Enum):
    active = "active"
    passive = "passive"
    active_passive = "active_passive"


class SubcontoType(str, enum.Enum):
    counterparty = "counterparty"
    contract = "contract"
    person = "person"
    item = "item"
    fixed_asset = "fixed_asset"
    bank_account = "bank_account"
    grant = "grant"
    budget_line = "budget_line"
    financing_source = "financing_source"


def pg_enum(py_enum: type[enum.Enum], name: str) -> ENUM:
    return ENUM(py_enum, name=name, create_type=False, values_callable=lambda e: [m.value for m in e])


user_role = pg_enum(UserRole, "user_role")
document_type = pg_enum(DocumentType, "document_type")
document_status = pg_enum(DocumentStatus, "document_status")
contract_type = pg_enum(ContractType, "contract_type")
entity_type = pg_enum(EntityType, "entity_type")
accounting_method = pg_enum(AccountingMethod, "accounting_method")
account_kind = pg_enum(AccountKind, "account_kind")
subconto_type = pg_enum(SubcontoType, "subconto_type")


class LineKind(str, enum.Enum):
    fixed_asset = "fixed_asset"
    low_value_item = "low_value_item"
    material = "material"
    goods = "goods"
    service = "service"


class PaymentDirection(str, enum.Enum):
    incoming = "incoming"
    outgoing = "outgoing"


line_kind = pg_enum(LineKind, "line_kind")
payment_direction = pg_enum(PaymentDirection, "payment_direction")


class ImportStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


import_status = pg_enum(ImportStatus, "import_status")
