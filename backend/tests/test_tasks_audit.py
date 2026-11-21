from datetime import date, datetime

from sqlalchemy import select

from app.audit.service import write_audit
from app.auth.models import OrganizationMember
from app.core.enums import UserRole
from app.regulated.models import ReportingCalendar, ReportStatus, TaxReport
from app.tasks.service import template_due_date
from tests.conftest import auth_headers, make_org, make_user


def _add_member(db, org, user, role):
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role))
    db.flush()


def test_task_crud_and_status(client, db):
    u = make_user(db, "t1@x.md")
    org = make_org(db, u, "Org T")
    h, base = auth_headers(u), f"/organizations/{org.id}"
    r = client.post(f"{base}/tasks", json={"title": "Trimite impozitele", "due_date": "2020-01-05"}, headers=h)
    assert r.status_code == 201
    tid = r.json()["id"]
    assert r.json()["status"] == "open"
    # termenul a trecut: la listare devine restantă
    assert client.get(f"{base}/tasks", headers=h).json()[0]["status"] == "overdue"
    assert client.post(f"{base}/tasks/{tid}/done", headers=h).json()["status"] == "done"
    assert client.post(f"{base}/tasks/{tid}/reopen", headers=h).json()["status"] == "overdue"
    assert client.patch(f"{base}/tasks/{tid}", json={"due_date": "2999-01-01"}, headers=h).json()["status"] == "open"
    assert client.post(f"{base}/tasks/{tid}/skip", headers=h).json()["status"] == "skipped"
    assert client.get(f"{base}/tasks?status_filter=skipped", headers=h).json()[0]["id"] == tid
    assert client.get(f"{base}/tasks?status_filter=nope", headers=h).status_code == 422
    assert client.delete(f"{base}/tasks/{tid}", headers=h).status_code == 204
    assert client.get(f"{base}/tasks", headers=h).json() == []


def test_tasks_isolated_between_organizations_and_private(client, db):
    a, b = make_user(db, "a@x.md"), make_user(db, "b@x.md")
    org_a, org_b = make_org(db, a, "Org A"), make_org(db, b, "Org B")
    ha, hb = auth_headers(a), auth_headers(b)
    tid = client.post(f"/organizations/{org_a.id}/tasks", json={"title": "A", "due_date": "2999-01-01"}, headers=ha).json()["id"]
    # B nu vede și nu poate modifica sarcina lui A, nici prin organizația proprie
    assert client.get(f"/organizations/{org_a.id}/tasks", headers=hb).status_code == 404
    for path in ("done", "skip", "reopen"):
        assert client.post(f"/organizations/{org_b.id}/tasks/{tid}/{path}", headers=hb).status_code == 404
    assert client.delete(f"/organizations/{org_b.id}/tasks/{tid}", headers=hb).status_code == 404
    # sarcina privată a unui contabil nu se vede de colegi
    colleague = make_user(db, "c@x.md")
    _add_member(db, org_a, colleague, UserRole.accountant)
    priv = client.post(
        f"/organizations/{org_a.id}/tasks", json={"title": "Personal", "due_date": "2999-01-01", "is_private": True}, headers=ha
    ).json()["id"]
    hc = auth_headers(colleague)
    assert {t["title"] for t in client.get(f"/organizations/{org_a.id}/tasks", headers=hc).json()} == {"A"}
    assert client.post(f"/organizations/{org_a.id}/tasks/{priv}/done", headers=hc).status_code == 404
    assert {t["title"] for t in client.get(f"/organizations/{org_a.id}/tasks", headers=ha).json()} == {"A", "Personal"}


def test_roles_on_tasks(client, db):
    boss = make_user(db, "boss@x.md")
    org = make_org(db, boss, "Org R", UserRole.admin)
    viewer = make_user(db, "v@x.md")
    _add_member(db, org, viewer, UserRole.auditor)
    hv = auth_headers(viewer)
    assert client.post(f"/organizations/{org.id}/tasks", json={"title": "x", "due_date": "2999-01-01"}, headers=hv).status_code == 403
    assert client.get(f"/organizations/{org.id}/tasks", headers=hv).status_code == 200
    assert client.post(f"/organizations/{org.id}/task-templates", json={"title": "x", "recurrence": "FREQ=MONTHLY;BYMONTHDAY=5"}, headers=hv).status_code == 403


def test_templates_generate_once_per_month(client, db):
    u = make_user(db, "tp@x.md")
    org = make_org(db, u, "Org TP")
    h, base = auth_headers(u), f"/organizations/{org.id}"
    bad = client.post(f"{base}/task-templates", json={"title": "x", "recurrence": "FREQ=WEEKLY"}, headers=h)
    assert bad.status_code == 422
    client.post(f"{base}/task-templates", json={"title": "Impozitele către administrator", "recurrence": "FREQ=MONTHLY;BYMONTHDAY=5"}, headers=h)
    client.post(f"{base}/task-templates", json={"title": "Inventarierea anuală", "recurrence": "FREQ=YEARLY;BYMONTH=12;BYMONTHDAY=31"}, headers=h)
    first = client.post(f"{base}/tasks/generate", json={"period": "2026-03-17"}, headers=h).json()
    assert [(t["title"], t["due_date"]) for t in first] == [("Impozitele către administrator", "2026-03-05")]
    assert client.post(f"{base}/tasks/generate", json={"period": "2026-03-01"}, headers=h).json() == []
    dec = client.post(f"{base}/tasks/generate", json={"period": "2026-12-01"}, headers=h).json()
    assert {t["due_date"] for t in dec} == {"2026-12-05", "2026-12-31"}


def test_template_isolation(client, db):
    a, b = make_user(db, "ta@x.md"), make_user(db, "tb@x.md")
    org_a, org_b = make_org(db, a, "TA"), make_org(db, b, "TB")
    tpl = client.post(f"/organizations/{org_a.id}/task-templates", json={"title": "A", "recurrence": "FREQ=MONTHLY;BYMONTHDAY=1"}, headers=auth_headers(a)).json()
    hb = auth_headers(b)
    assert client.get(f"/organizations/{org_b.id}/task-templates", headers=hb).json() == []
    body = {"title": "hack", "recurrence": "FREQ=MONTHLY;BYMONTHDAY=2"}
    assert client.put(f"/organizations/{org_b.id}/task-templates/{tpl['id']}", json=body, headers=hb).status_code == 404
    assert client.delete(f"/organizations/{org_b.id}/task-templates/{tpl['id']}", headers=hb).status_code == 404


def test_template_due_date_clamps_to_month_end():
    assert template_due_date("FREQ=MONTHLY;BYMONTHDAY=31", date(2026, 2, 1)) == date(2026, 2, 28)
    assert template_due_date("FREQ=YEARLY;BYMONTH=12;BYMONTHDAY=31", date(2026, 11, 1)) is None


def test_calendar_sync_creates_and_closes_tasks(client, db):
    u = make_user(db, "cal@x.md")
    org = make_org(db, u, "Org Cal")
    org.created_at = datetime(date.today().year - 1, 1, 1)  # activitate de mai mult timp → termene în calendar
    db.flush()
    h, base = auth_headers(u), f"/organizations/{org.id}"
    created = client.post(f"{base}/tasks/sync-calendar", headers=h).json()
    assert created and all(t["calendar_id"] and t["title"].startswith("Depune ") for t in created)
    assert client.post(f"{base}/tasks/sync-calendar", headers=h).json() == []  # fără dubluri
    # depunerea raportului închide sarcina
    cal = db.get(ReportingCalendar, created[0]["calendar_id"])
    report = TaxReport(
        organization_id=org.id, form_id=cal.form_id, period_from=cal.period_from, period_to=cal.period_to,
        status=ReportStatus.submitted, submitted_at=datetime.now(),
    )  # fmt: skip
    db.add(report)
    db.flush()
    cal.tax_report_id = report.id
    db.flush()
    client.post(f"{base}/tasks/sync-calendar", headers=h)
    tasks = {t["id"]: t for t in client.get(f"{base}/tasks", headers=h).json()}
    assert tasks[created[0]["id"]]["status"] == "done"


def test_audit_view_scope_and_roles(client, db):
    a, b = make_user(db, "au@x.md"), make_user(db, "bu@x.md")
    org_a, org_b = make_org(db, a, "AU A"), make_org(db, b, "AU B")
    write_audit(db, action="create", entity="documents", organization_id=org_a.id, user_id=a.id, new_values={"n": 1})
    write_audit(db, action="create", entity="documents", organization_id=org_b.id, user_id=b.id)
    write_audit(db, action="create", entity="personal_checks", organization_id=org_a.id, user_id=a.id)
    write_audit(db, action="login", entity="users", user_id=a.id)
    write_audit(db, action="login", entity="users", user_id=b.id)
    db.flush()
    ha = auth_headers(a)
    items = client.get(f"/organizations/{org_a.id}/audit", headers=ha).json()["items"]
    assert {(i["entity"], i["user_email"]) for i in items} == {("documents", "au@x.md"), ("users", "au@x.md")}
    assert [i["entity"] for i in client.get(f"/organizations/{org_a.id}/audit?entity=documents", headers=ha).json()["items"]] == ["documents"]
    assert "documents" in client.get(f"/organizations/{org_a.id}/audit/entities", headers=ha).json()
    assert client.get(f"/organizations/{org_a.id}/audit", headers=auth_headers(b)).status_code == 404
    acc = make_user(db, "acc@x.md")
    _add_member(db, org_a, acc, UserRole.accountant)
    assert client.get(f"/organizations/{org_a.id}/audit", headers=auth_headers(acc)).status_code == 403
    paged = client.get(f"/organizations/{org_a.id}/audit?limit=1", headers=ha).json()
    assert paged["has_more"] and len(paged["items"]) == 1
