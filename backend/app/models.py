"""Importă toate modelele, ca SQLAlchemy și Alembic să vadă întreaga schemă."""

from app.audit.models import AuditLog
from app.bank.models import BankAccount, BankFormat, BankImport, BankTransaction, ExchangeRate, PaymentBatch
from app.auth.models import OrganizationMember, User
from app.catalogs.models import Account, AccountAnalytics, Counterparty, Department
from app.documents.models import Document, Invoice, InvoiceLine, PaymentOrder, PaymentOrderLine
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
    "BankFormat",
    "BankImport",
    "BankTransaction",
    "BudgetLine",
    "CostItem",
    "Contract",
    "ContractFunding",
    "Counterparty",
    "Department",
    "Document",
    "ExchangeRate",
    "EntryLine",
    "EntryLineAnalytics",
    "ExemptionClaim",
    "FixedAsset",
    "Grant",
    "IndividualPayment",
    "Invoice",
    "InvoiceLine",
    "MonthCloseRun",
    "Organization",
    "OrganizationMember",
    "PaymentBatch",
    "PaymentOrder",
    "PaymentOrderLine",
    "PayrollEntry",
    "PayrollPeriod",
    "Person",
    "OrganizationStats",
    "PostingRule",
    "ReportForm",
    "ReportingCalendar",
    "TaxReport",
    "TaxRate",
    "User",
    "Workspace",
]
