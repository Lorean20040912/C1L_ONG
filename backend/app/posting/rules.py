"""Regulile de înregistrare ca date (`posting_rules`).

O regulă = un rând Dt/Kt pentru (tip document, operațiune), cu condiții,
perioadă de valabilitate și sursa legislativă. Un document cere una sau mai
multe operațiuni (ex. cheltuiala din grant = `expense` + `income_recognition`),
iar pentru fiecare operațiune se alege o singură regulă:

1. doar regulile stabile (`release_id` gol) valabile la data operațiunii;
2. condițiile regulii trebuie să fie toate îndeplinite de atributele operațiunii
   (atributele includ și opțiunile politicii contabile în vigoare);
3. corecția organizației are prioritate față de regula standard, apoi regula
   cu mai multe condiții (mai specifică), apoi versiunea mai nouă;
4. două reguli la fel de potrivite = eroare (formula ar fi ambiguă).

Conturile se scriu prin cod („716”, „234.4”) sau prin trimitere la politica
contabilă („{grant_receivable}”) și se caută în planul de conturi al organizației.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.catalogs.models import Account
from app.posting.engine import AnalyticsInput, LineInput, PostingError
from app.posting.models import AccountingPolicy, PostingRule

# trimiterile permise din formule către conturile alese în politica contabilă
POLICY_ACCOUNTS = {"grant_receivable": "grant_receivable_account_id"}

# opțiunile politicii contabile care devin atribute pentru condiții
POLICY_ATTRIBUTES = ("grant_recognition", "stock_to_deferred_income", "fa_valuation_method")

# dimensiunile pe care o regulă le poate cere obligatoriu (analytics.required)
DIMENSIONS = {
    "grant": "grant_id",
    "budget_line": "budget_line_id",
    "cost_item": "cost_item_id",
    "department": "department_id",
}

_PLACEHOLDER = re.compile(r"^\{(\w+)\}$")


@dataclass
class OperationInput:
    operation: str
    amount: Decimal
    attributes: dict[str, Any] = field(default_factory=dict)
    entry_date: date | None = None
    grant_id: uuid.UUID | None = None
    budget_line_id: uuid.UUID | None = None
    cost_item_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    currency: str | None = None
    currency_amount: Decimal | None = None
    quantity: Decimal | None = None
    activity_type: str | None = None
    description: str | None = None
    analytics: list[AnalyticsInput] = field(default_factory=list)
    # contul ales explicit pe rândul documentului (ex. contul bancar 242/243 sau
    # contul de cheltuieli din rândul facturii) înlocuiește contul din formulă
    debit_account_id: uuid.UUID | None = None
    credit_account_id: uuid.UUID | None = None


@dataclass
class GeneratedLine:
    line: LineInput
    rule: PostingRule


def policy_in_force(db: Session, organization_id: uuid.UUID, on_date: date) -> AccountingPolicy | None:
    return db.scalar(
        select(AccountingPolicy)
        .where(AccountingPolicy.organization_id == organization_id, AccountingPolicy.valid_from <= on_date)
        .order_by(AccountingPolicy.valid_from.desc())
        .limit(1)
    )


def _policy_attributes(policy: AccountingPolicy | None) -> dict[str, Any]:
    if policy is None:
        return {}
    attrs = {name: getattr(policy, name) for name in POLICY_ATTRIBUTES if getattr(policy, name) is not None}
    # setările suplimentare ale politicii pot fi folosite și ele în condiții
    for key, value in (policy.settings or {}).items():
        attrs.setdefault(key, value)
    return attrs


def _matches(conditions: dict | None, attributes: dict[str, Any]) -> bool:
    for key, expected in (conditions or {}).items():
        actual = attributes.get(key)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


def select_rule(
    db: Session,
    organization_id: uuid.UUID,
    document_type: str,
    operation: str,
    attributes: dict[str, Any],
    on_date: date,
) -> PostingRule:
    candidates = db.scalars(
        select(PostingRule).where(
            PostingRule.document_type == document_type,
            PostingRule.operation == operation,
            PostingRule.release_id.is_(None),
            PostingRule.valid_from <= on_date,
            or_(PostingRule.valid_to.is_(None), PostingRule.valid_to >= on_date),
            or_(PostingRule.organization_id.is_(None), PostingRule.organization_id == organization_id),
        )
    ).all()
    matching = [r for r in candidates if _matches(r.conditions, attributes)]
    if not matching:
        raise PostingError(
            f"Nu există regulă de înregistrare pentru {document_type} / {operation} la {on_date:%d.%m.%Y}"
        )

    def rank(r: PostingRule) -> tuple:
        return (r.organization_id is not None, len(r.conditions or {}), r.version or 1)

    matching.sort(key=rank, reverse=True)
    if len(matching) > 1 and rank(matching[0]) == rank(matching[1]):
        refs = ", ".join(r.source_ref for r in matching[:2])
        raise PostingError(f"Reguli ambigue pentru {document_type} / {operation} ({refs})")
    return matching[0]


class _AccountResolver:
    def __init__(self, db: Session, organization_id: uuid.UUID, policy: AccountingPolicy | None):
        self.db = db
        self.organization_id = organization_id
        self.policy = policy
        self._by_code: dict[str, uuid.UUID] = {}

    def __call__(self, formula: str) -> uuid.UUID:
        formula = formula.strip()
        placeholder = _PLACEHOLDER.match(formula)
        if placeholder:
            name = placeholder.group(1)
            column = POLICY_ACCOUNTS.get(name)
            if column is None:
                raise PostingError(f"Trimitere necunoscută în formulă: {formula}")
            account_id = getattr(self.policy, column, None) if self.policy else None
            if account_id is None:
                raise PostingError(f"Politica contabilă nu stabilește contul pentru {formula}")
            return account_id
        if formula not in self._by_code:
            account_id = self.db.scalar(
                select(Account.id).where(Account.organization_id == self.organization_id, Account.code == formula)
            )
            if account_id is None:
                raise PostingError(f"Contul {formula} lipsește din planul de conturi")
            self._by_code[formula] = account_id
        return self._by_code[formula]


def build_lines(
    db: Session,
    *,
    organization_id: uuid.UUID,
    document_type: str,
    doc_date: date | None,
    operations: list[OperationInput],
) -> list[GeneratedLine]:
    """Transformă operațiunile documentului în rânduri Dt/Kt după reguli.

    Nu scrie nimic în baza de date: rezultatul se poate arăta ca previzualizare
    sau se dă motorului de înregistrare (`post_document`).
    """
    if not operations:
        raise PostingError("Documentul nu are operațiuni")
    generated: list[GeneratedLine] = []
    policies: dict[date, AccountingPolicy | None] = {}
    resolvers: dict[date, _AccountResolver] = {}
    for i, op in enumerate(operations, start=1):
        on_date = op.entry_date or doc_date
        if on_date is None:
            raise PostingError(f"Operațiunea {i}: lipsește data")
        if on_date not in policies:
            policies[on_date] = policy_in_force(db, organization_id, on_date)
            resolvers[on_date] = _AccountResolver(db, organization_id, policies[on_date])
        attributes = {**_policy_attributes(policies[on_date]), **op.attributes}
        if op.currency:
            attributes.setdefault("currency", op.currency)

        rule = select_rule(db, organization_id, document_type, op.operation, attributes, on_date)
        for dim in (rule.analytics or {}).get("required", []):
            column = DIMENSIONS.get(dim)
            if column is None:
                raise PostingError(f"Regula {rule.source_ref} cere o dimensiune necunoscută: {dim}")
            if getattr(op, column) is None:
                raise PostingError(f"Operațiunea {i} ({op.operation}): lipsește {dim} (cerut de {rule.source_ref})")

        resolve = resolvers[on_date]
        generated.append(
            GeneratedLine(
                line=LineInput(
                    debit_account_id=op.debit_account_id or resolve(rule.debit_account),
                    credit_account_id=op.credit_account_id or resolve(rule.credit_account),
                    amount=op.amount,
                    entry_date=on_date,
                    currency=op.currency,
                    currency_amount=op.currency_amount,
                    quantity=op.quantity,
                    department_id=op.department_id,
                    grant_id=op.grant_id,
                    budget_line_id=op.budget_line_id,
                    cost_item_id=op.cost_item_id,
                    activity_type=op.activity_type or (rule.analytics or {}).get("activity_type"),
                    description=op.description,
                    analytics=list(op.analytics),
                ),
                rule=rule,
            )
        )
    return generated
