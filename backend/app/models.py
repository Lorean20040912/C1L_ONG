"""Importă toate modelele, ca SQLAlchemy și Alembic să vadă întreaga schemă."""

from app.assistant.models import AiConversation, AiMessage
from app.audit.models import AuditLog
from app.bank.models import BankAccount, BankFormat, BankImport, BankTransaction, ExchangeRate, PaymentBatch
from app.auth.models import OrganizationMember, User, UserBackupCode
from app.catalogs.models import Account, AccountAnalytics, Counterparty, Department
from app.documents.models import Document, Invoice, InvoiceLine, PaymentOrder, PaymentOrderLine
from app.features.models import CoaTemplate, Feature, OrganizationFeature, OrganizationTaxRegime
from app.fix6.models import DocumentSource, FixedAssetEvent, PayrollCalcType, PeriodAdjustment, ScannedFile
from app.fixed_assets.models import FixedAsset
from app.grants.models import Allocation, BudgetLine, BudgetVersion, CostItem, Donor, Grant, GrantDonor, GrantTranche
from app.month_close.models import MonthCloseRun
from app.efactura.models import EfacturaMessage
from app.onec_import.models import OnecIdMap, OnecImportRun, OpeningBalance
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
from app.tasks.models import Task, TaskTemplate
from app.taxes.models import TaxRate
from app.workspaces.models import Organization, Workspace

__all__ = [
    "AiConversation",
    "AiMessage",
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
    "CoaTemplate",
    "Counterparty",
    "Department",
    "Document",
    "EfacturaMessage",
    "ExchangeRate",
    "EntryLine",
    "EntryLineAnalytics",
    "ExemptionClaim",
    "Feature",
    "DocumentSource",
    "FixedAsset",
    "FixedAssetEvent",
    "PayrollCalcType",
    "PeriodAdjustment",
    "ScannedFile",
    "Grant",
    "GrantDonor",
    "GrantTranche",
    "Allocation",
    "BudgetVersion",
    "Donor",
    "IndividualPayment",
    "Invoice",
    "InvoiceLine",
    "MonthCloseRun",
    "OnecIdMap",
    "OnecImportRun",
    "OpeningBalance",
    "Organization",
    "OrganizationFeature",
    "OrganizationMember",
    "PaymentBatch",
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
    "Task",
    "TaskTemplate",
    "User",
    "UserBackupCode",
    "Workspace",
]
