"""Chatul asistentului AI: conversații personale, răspunsuri din datele organizației.

Asistentul are exact drepturile utilizatorului (același `OrgContext`), citește doar
prin instrumentele din `tools.py` și nu scrie nimic în contabilitate (ToR F8.3).
"""

import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assistant.llm import LLMClient, LLMError, LLMNotConfigured, get_llm_client
from app.assistant.models import AiConversation, AiMessage
from app.assistant.tools import TOOLS, run_tool
from app.audit.service import write_audit
from app.auth.deps import OrgContext, get_org_context
from app.core.db import get_db

router = APIRouter(prefix="/organizations/{organization_id}/assistant", tags=["asistent AI"])

MAX_STEPS = 5
HISTORY = 20

SYSTEM_PROMPT = (
    "Ești asistentul contabil al aplicației ContaHub, pentru organizații necomerciale din Republica Moldova. "
    "Răspunde în română, scurt și precis. Cifrele și documentele le iei DOAR din instrumentele puse la dispoziție; "
    "dacă datele lipsesc, spune asta, nu inventa. Poți explica Dt/Kt și regulile de înregistrare (cu sursa din regulă) "
    "și poți sugera înregistrări ca text (Dt cont / Kt cont / sumă) — sugestiile nu se aplică singure, "
    "utilizatorul le introduce el. Nu poți modifica date, închide perioade sau schimba drepturi."
)


class ConversationIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    context: dict | None = None


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str | None
    context: dict | None
    created_at: datetime | None


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    context: dict | None = None  # ecranul / documentul deschis acum


class MessageOut(BaseModel):
    id: int
    role: str
    content: str | None
    tool_calls: list | None
    created_at: datetime | None


def llm_client() -> LLMClient:
    """Dependența clientului LLM (în teste se suprascrie cu un client fals)."""
    try:
        return get_llm_client()
    except LLMNotConfigured:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Asistentul AI nu este configurat: administratorul trebuie să seteze ANTHROPIC_API_KEY în .env.",
        ) from None


def _conversation(db: Session, ctx: OrgContext, conversation_id: uuid.UUID) -> AiConversation:
    conv = db.scalar(
        select(AiConversation).where(
            AiConversation.id == conversation_id,
            AiConversation.organization_id == ctx.organization_id,
            AiConversation.user_id == ctx.user.id,
        )
    )
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversația nu a fost găsită")
    return conv


@router.post("/conversations", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
def create_conversation(
    body: ConversationIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> AiConversation:
    conv = AiConversation(organization_id=ctx.organization_id, user_id=ctx.user.id, title=body.title, context=body.context)
    db.add(conv)
    db.flush()
    write_audit(db, action="create", entity="ai_conversation", entity_id=conv.id,
                organization_id=ctx.organization_id, user_id=ctx.user.id)
    db.commit()
    return conv


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[AiConversation]:
    return list(
        db.scalars(
            select(AiConversation)
            .where(AiConversation.organization_id == ctx.organization_id, AiConversation.user_id == ctx.user.id)
            .order_by(AiConversation.created_at.desc())
            .limit(50)
        )
    )


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def list_messages(
    conversation_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> list[AiMessage]:
    conv = _conversation(db, ctx, conversation_id)
    return list(db.scalars(select(AiMessage).where(AiMessage.conversation_id == conv.id).order_by(AiMessage.id)))


@router.post("/conversations/{conversation_id}/messages", response_model=MessageOut)
def send_message(
    conversation_id: uuid.UUID,
    body: MessageIn,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
    llm: LLMClient = Depends(llm_client),
) -> AiMessage:
    conv = _conversation(db, ctx, conversation_id)
    return _answer(db, ctx, conv, body, llm)


def _answer(db: Session, ctx: OrgContext, conv: AiConversation, body: MessageIn, llm: LLMClient) -> AiMessage:
    history = list(
        db.scalars(
            select(AiMessage)
            .where(AiMessage.conversation_id == conv.id, AiMessage.role.in_(("user", "assistant")))
            .order_by(AiMessage.id.desc())
            .limit(HISTORY)
        )
    )[::-1]
    messages: list[dict] = [{"role": m.role, "content": m.content or ""} for m in history]
    messages.append({"role": "user", "content": body.content})
    if body.context:
        conv.context = body.context
    system = SYSTEM_PROMPT
    if conv.context:
        system += f"\nContext: utilizatorul are deschis {json.dumps(conv.context, ensure_ascii=False)[:500]}. Rolul lui: {ctx.role.value}."

    db.add(AiMessage(conversation_id=conv.id, role="user", content=body.content))
    if conv.title is None:
        conv.title = body.content[:60]
    used: list[dict] = []
    text = ""
    try:
        for _ in range(MAX_STEPS):
            reply = llm.complete(system, messages, TOOLS)
            if not reply.tool_calls:
                text = reply.text
                break
            blocks: list[dict] = ([{"type": "text", "text": reply.text}] if reply.text else []) + [
                {"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in reply.tool_calls
            ]
            results = []
            for call in reply.tool_calls:
                output = run_tool(db, ctx, call.name, call.input)
                used.append({"name": call.name, "input": call.input})
                results.append({"type": "tool_result", "tool_use_id": call.id, "content": json.dumps(output, ensure_ascii=False)})
            messages += [{"role": "assistant", "content": blocks}, {"role": "user", "content": results}]
        else:
            text = "Nu am putut încheia analiza în numărul permis de pași. Reformulați întrebarea mai precis."
    except LLMError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from None

    answer = AiMessage(conversation_id=conv.id, role="assistant", content=text or "(fără răspuns)", tool_calls=used or None)
    db.add(answer)
    write_audit(db, action="message", entity="ai_conversation", entity_id=conv.id, organization_id=ctx.organization_id,
                user_id=ctx.user.id, new_values={"tools": [u["name"] for u in used]})
    db.commit()
    return answer
