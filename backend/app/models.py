"""Importă toate modelele, ca SQLAlchemy și Alembic să vadă întreaga schemă."""

from app.audit.models import AuditLog
from app.bank.models import BankAccount
from app.auth.models import OrganizationMember, User
from app.catalogs.models import Account, AccountAnalytics, Counterparty, Department
from app.documents.models import Document, Invoice, InvoiceLine, PaymentOrder, PaymentOrderLine
from app.fixed_assets.models import FixedAsset
from app.grants.models import BudgetLine, CostItem, Grant
from app.posting.models import (
    AccountingPeriod,
    AccountingPolicy,
    AccountTurnover,
    EntryLine,
    EntryLineAnalytics,
    PostingRule,
)
from app.taxes.models import TaxRate
from app.workspaces.models import Organization, Workspace

__all__ = [
    "Account",
    "AccountAnalytics",
    "AccountingPeriod",
    "AccountingPolicy",
    "AccountTurnover",
    "AuditLog",
    "BankAccount",
    "BudgetLine",
    "CostItem",
    "Counterparty",
    "Department",
    "Document",
    "EntryLine",
    "EntryLineAnalytics",
    "FixedAsset",
    "Grant",
    "Invoice",
    "InvoiceLine",
    "Organization",
    "OrganizationMember",
    "PaymentOrder",
    "PaymentOrderLine",
    "PostingRule",
    "TaxRate",
    "User",
    "Workspace",
]
