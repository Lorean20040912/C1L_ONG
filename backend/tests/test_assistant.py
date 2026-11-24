"""Asistentul AI: chat cu client LLM fals, instrumente doar pe datele organizației, izolare."""

from app.assistant.llm import LLMReply, ToolCall
from app.assistant.router import llm_client
from app.main import app
from app.models import AiMessage, AuditLog
from tests.conftest import auth_headers, make_accounts, make_org, make_user


class FakeLLM:
    """Răspunsuri programate; reține ce a primit."""

    def __init__(self, *replies: LLMReply):
        self.replies = list(replies)
        self.calls: list[dict] = []

    def complete(self, system, messages, tools):
        self.calls.append({"system": system, "messages": [dict(m) for m in messages], "tools": tools})
        return self.replies.pop(0)


def use_llm(llm):
    app.dependency_overrides[llm_client] = lambda: llm


def start(client, org, user, context=None):
    r = client.post(f"/organizations/{org.id}/assistant/conversations", json={"context": context}, headers=auth_headers(user))
    assert r.status_code == 201
    return r.json()["id"]


def say(client, org, user, conv, text, **kw):
    return client.post(
        f"/organizations/{org.id}/assistant/conversations/{conv}/messages", json={"content": text, **kw}, headers=auth_headers(user)
    )


def test_fara_cheie_mesaj_clar(client, db, monkeypatch):
    monkeypatch.setattr("app.assistant.llm.get_settings", lambda: type("S", (), {"anthropic_api_key": None})())
    user = make_user(db, "ai1@test.md")
    org = make_org(db, user, "ONG AI 1")
    conv = start(client, org, user)
    r = say(client, org, user, conv, "Salut")
    assert r.status_code == 503
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_raspuns_cu_instrument_si_jurnal(client, db):
    user = make_user(db, "ai2@test.md")
    org = make_org(db, user, "ONG AI 2")
    make_accounts(db, org, "521", "242")
    llm = FakeLLM(
        LLMReply(tool_calls=[ToolCall("t1", "list_accounts", {"query": "521"})]),
        LLMReply(text="Contul 521 este contul bancar."),
    )
    use_llm(llm)
    conv = start(client, org, user)
    r = say(client, org, user, conv, "Ce este contul 521?", context={"screen": "invoice-list"})
    assert r.status_code == 200, r.text
    assert r.json()["content"] == "Contul 521 este contul bancar."
    assert r.json()["tool_calls"] == [{"name": "list_accounts", "input": {"query": "521"}}]
    # rezultatul instrumentului a ajuns la model și conține doar contul căutat
    result = llm.calls[1]["messages"][-1]["content"][0]["content"]
    assert "521" in result and "242" not in result
    assert "invoice-list" in llm.calls[0]["system"]
    msgs = client.get(f"/organizations/{org.id}/assistant/conversations/{conv}/messages", headers=auth_headers(user)).json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert db.query(AuditLog).filter_by(entity="ai_conversation", action="message").count() == 1


def test_instrumentele_nu_vad_alta_organizatie(client, db):
    a, b = make_user(db, "ai3a@test.md"), make_user(db, "ai3b@test.md")
    org_a, org_b = make_org(db, a, "ONG A"), make_org(db, b, "ONG B")
    make_accounts(db, org_a, "211")
    make_accounts(db, org_b, "999")
    llm = FakeLLM(LLMReply(tool_calls=[ToolCall("t", "list_accounts", {})]), LLMReply(text="ok"))
    use_llm(llm)
    conv = start(client, org_a, a)
    assert say(client, org_a, a, conv, "conturi?").status_code == 200
    result = llm.calls[1]["messages"][-1]["content"][0]["content"]
    assert "211" in result and "999" not in result


def test_conversatia_altui_utilizator_sau_organizatii_da_404(client, db):
    a, b = make_user(db, "ai4a@test.md"), make_user(db, "ai4b@test.md")
    org_a, org_b = make_org(db, a, "ONG A4"), make_org(db, b, "ONG B4")
    use_llm(FakeLLM(LLMReply(text="x")))
    conv = start(client, org_a, a)
    # alt utilizator, altă organizație
    assert say(client, org_b, b, conv, "salut").status_code == 404
    assert client.get(f"/organizations/{org_b.id}/assistant/conversations/{conv}/messages", headers=auth_headers(b)).status_code == 404
    # utilizatorul b nu are acces la organizația a
    assert say(client, org_a, b, conv, "salut").status_code == 404
    assert client.get(f"/organizations/{org_b.id}/assistant/conversations", headers=auth_headers(b)).json() == []


def test_alt_membru_al_organizatiei_nu_citeste_conversatia(client, db):
    from app.auth.models import OrganizationMember
    from app.core.enums import UserRole

    a, b = make_user(db, "ai5a@test.md"), make_user(db, "ai5b@test.md")
    org = make_org(db, a, "ONG 5")
    db.add(OrganizationMember(organization_id=org.id, user_id=b.id, role=UserRole.accountant))
    db.flush()
    conv = start(client, org, a)
    assert client.get(f"/organizations/{org.id}/assistant/conversations/{conv}/messages", headers=auth_headers(b)).status_code == 404


def test_instrument_necunoscut_si_document_strain(client, db):
    a, b = make_user(db, "ai6a@test.md"), make_user(db, "ai6b@test.md")
    org_a, org_b = make_org(db, a, "ONG A6"), make_org(db, b, "ONG B6")
    llm = FakeLLM(
        LLMReply(tool_calls=[
            ToolCall("1", "sterge_tot", {}),
            ToolCall("2", "get_document_entries", {"document_id": "00000000-0000-0000-0000-000000000001"}),
            ToolCall("3", "explain_posting_rules", {}),
        ]),
        LLMReply(text="gata"),
    )
    use_llm(llm)
    conv = start(client, org_a, a)
    assert say(client, org_a, a, conv, "x").status_code == 200
    results = [r["content"] for r in llm.calls[1]["messages"][-1]["content"]]
    assert "necunoscut" in results[0] and "nu a fost găsit" in results[1] and '"rules"' in results[2]


def test_cerere_fara_autentificare(client, db):
    user = make_user(db, "ai7@test.md")
    org = make_org(db, user, "ONG 7")
    assert client.post(f"/organizations/{org.id}/assistant/conversations", json={}).status_code == 401


def test_limita_de_pasi(client, db):
    user = make_user(db, "ai8@test.md")
    org = make_org(db, user, "ONG 8")
    use_llm(FakeLLM(*[LLMReply(tool_calls=[ToolCall(str(i), "list_accounts", {})]) for i in range(10)]))
    conv = start(client, org, user)
    r = say(client, org, user, conv, "x")
    assert r.status_code == 200 and "numărul permis" in r.json()["content"]
    assert db.query(AiMessage).count() == 2
