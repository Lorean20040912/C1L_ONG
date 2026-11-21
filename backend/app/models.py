"""Importă toate modelele, ca SQLAlchemy și Alembic să vadă întreaga schemă."""

from app.audit.models import AuditLog
from app.bank.models import BankAccount
from app.auth.models import OrganizationMember, User
from app.catalogs.models import Account, AccountAnalytics, Counterparty, Department
from app.documents.models import Document, Invoice, InvoiceLine, PaymentOrder, PaymentOrderLine
from app.features.models import CoaTemplate, Feature, OrganizationFeature, OrganizationTaxRegime
from app.fixed_assets.models import FixedAsset
from app.grants.models import BudgetLine, CostItem, Grant
from app.month_close.models import MonthCloseRun
from app.payroll.models import (
    Contract,
    ContractFunding,
    ExemptionClaim,
    IndividualPayment,
    PayrollEntry,
    PayrollPeriod,
    Person,
)
from app.posting.models import (
    AccountingPeriod,
    AccountingPolicy,
    AccountTurnover,
    EntryLine,
    EntryLineAnalytics,
    PostingRule,
)
from app.regulated.models import OrganizationStats, ReportForm, ReportingCalendar, TaxReport
from app.simple_ledger.models import SimpleLedgerEntry
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
    "Contract",
    "ContractFunding",
    "CoaTemplate",
    "Counterparty",
    "Department",
    "Document",
    "EntryLine",
    "EntryLineAnalytics",
    "ExemptionClaim",
    "Feature",
    "FixedAsset",
    "Grant",
    "IndividualPayment",
    "Invoice",
    "InvoiceLine",
    "MonthCloseRun",
    "Organization",
    "OrganizationFeature",
    "OrganizationMember",
    "OrganizationTaxRegime",
    "PaymentOrder",
    "PaymentOrderLine",
    "PayrollEntry",
    "PayrollPeriod",
    "Person",
    "OrganizationStats",
    "PostingRule",
    "ReportForm",
    "ReportingCalendar",
    "SimpleLedgerEntry",
    "TaxReport",
    "TaxRate",
    "User",
    "Workspace",
]
