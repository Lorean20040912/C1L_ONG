"""Instrumentele de citire ale asistentului: doar date ale organizației curente.

Se apelează cu `OrgContext` — același filtru pe organizație ca în restul API-ului.
Instrumentele nu scriu nimic: înregistrările le propune asistentul doar ca text.
"""

import uuid
from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth.deps import OrgContext
from app.catalogs.models import Account, Counterparty
from app.documents.models import Document
from app.posting.models import EntryLine, PostingRule
from app.reports.router import trial_balance

LIMIT = 40

TOOLS: list[dict] = [
    {
        "name": "list_accounts",
        "description": "Caută în planul de conturi al organizației după cod sau denumire.",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
    },
    {
        "name": "get_trial_balance",
        "description": "Balanța de verificare (OSV) pe perioadă; date în format AAAA-LL-ZZ.",
        "input_schema": {
            "type": "object",
            "properties": {"date_from": {"type": "string"}, "date_to": {"type": "string"}},
            "required": ["date_from", "date_to"],
        },
    },
    {
        "name": "find_documents",
        "description": "Caută documente după număr sau contrapartidă (facturi, ordine de plată).",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
    },
    {
        "name": "get_document_entries",
        "description": "Înregistrările Dt/Kt ale unui document.",
        "input_schema": {
            "type": "object",
            "properties": {"document_id": {"type": "string"}},
            "required": ["document_id"],
        },
    },
    {
        "name": "explain_posting_rules",
        "description": "Regulile de înregistrare (Dt/Kt) cu sursa legislativă; filtru opțional după tipul documentului.",
        "input_schema": {"type": "object", "properties": {"document_type": {"type": "string"}}},
    },
]


def _like(value: str) -> str:
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _list_accounts(db: Session, ctx: OrgContext, query: str = "", **_: Any) -> dict:
    stmt = select(Account).where(Account.organization_id == ctx.organization_id).order_by(Account.code).limit(LIMIT)
    if query:
        stmt = stmt.where(or_(Account.code.ilike(_like(query)), Account.name.ilike(_like(query))))
    return {"accounts": [{"code": a.code, "name": a.name, "kind": a.account_kind.value} for a in db.scalars(stmt)]}


def _get_trial_balance(db: Session, ctx: OrgContext, date_from: str, date_to: str, **_: Any) -> dict:
    result = trial_balance(date_from=date.fromisoformat(date_from), date_to=date.fromisoformat(date_to), ctx=ctx, db=db)
    rows = [
        {"cont": r.code, "denumire": r.name, "sold_final_debit": str(r.closing_debit), "sold_final_credit": str(r.closing_credit),
         "rulaj_debit": str(r.turnover_debit), "rulaj_credit": str(r.turnover_credit)}
        for r in result.rows[:LIMIT]
    ]
    return {"rows": rows, "total_conturi": len(result.rows), "totals": {k: str(v) for k, v in result.totals.items()}}


def _find_documents(db: Session, ctx: OrgContext, query: str = "", **_: Any) -> dict:
    stmt = (
        select(Document, Counterparty.name)
        .outerjoin(Counterparty, Counterparty.id == Document.counterparty_id)
        .where(Document.organization_id == ctx.organization_id)
        .order_by(Document.doc_date.desc().nulls_last())
        .limit(LIMIT)
    )
    if query:
        stmt = stmt.where(or_(Document.doc_number.ilike(_like(query)), Counterparty.name.ilike(_like(query))))
    return {
        "documents": [
            {"id": str(d.id), "tip": d.type.value if d.type else None, "numar": d.doc_number,
             "data": d.doc_date.isoformat() if d.doc_date else None, "suma": str(d.total_amount) if d.total_amount is not None else None,
             "moneda": d.currency, "contrapartida": name, "inregistrat": bool(d.is_posted)}
            for d, name in db.execute(stmt)
        ]
    }


def _get_document_entries(db: Session, ctx: OrgContext, document_id: str, **_: Any) -> dict:
    try:
        doc_id = uuid.UUID(document_id)
    except ValueError:
        return {"error": "Identificator de document invalid"}
    doc = db.scalar(select(Document).where(Document.id == doc_id, Document.organization_id == ctx.organization_id))
    if doc is None:
        return {"error": "Documentul nu a fost găsit"}
    debit, credit = Account.__table__.alias("d"), Account.__table__.alias("k")
    stmt = (
        select(EntryLine.entry_date, debit.c.code, credit.c.code, EntryLine.amount)
        .join(debit, debit.c.id == EntryLine.debit_account_id)
        .join(credit, credit.c.id == EntryLine.credit_account_id)
        .where(EntryLine.document_id == doc.id, EntryLine.organization_id == ctx.organization_id)
        .order_by(EntryLine.line_no)
    )
    return {"entries": [{"data": d.isoformat(), "debit": dt, "credit": kt, "suma": str(a)} for d, dt, kt, a in db.execute(stmt)]}


def _explain_posting_rules(db: Session, ctx: OrgContext, document_type: str = "", **_: Any) -> dict:
    stmt = (
        select(PostingRule)
        .where(
            or_(PostingRule.organization_id.is_(None), PostingRule.organization_id == ctx.organization_id),
            PostingRule.release_id.is_(None),
        )
        .order_by(PostingRule.document_type, PostingRule.operation)
        .limit(LIMIT)
    )
    if document_type:
        stmt = stmt.where(PostingRule.document_type == document_type)
    return {
        "rules": [
            {"document": r.document_type, "operatiune": r.operation, "debit": r.debit_account, "credit": r.credit_account,
             "conditii": r.conditions, "sursa": r.source_ref, "de_la": r.valid_from.isoformat(),
             "pana_la": r.valid_to.isoformat() if r.valid_to else None}
            for r in db.scalars(stmt)
        ]
    }


_HANDLERS = {
    "list_accounts": _list_accounts,
    "get_trial_balance": _get_trial_balance,
    "find_documents": _find_documents,
    "get_document_entries": _get_document_entries,
    "explain_posting_rules": _explain_posting_rules,
}


def run_tool(db: Session, ctx: OrgContext, name: str, args: dict) -> dict:
    handler = _HANDLERS.get(name)
    if handler is None:
        return {"error": f"Instrument necunoscut: {name}"}
    try:
        return handler(db, ctx, **args)
    except (TypeError, ValueError) as exc:
        return {"error": f"Parametri invalizi: {exc}"}
    except HTTPException as exc:
        return {"error": str(exc.detail)}
