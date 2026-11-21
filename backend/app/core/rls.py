"""Row-Level Security pe organizație (arhitectura §10).

Aplicația fixează în fiecare tranzacție `app.org_id` (și `app.user_id`) din contextul
cererii (`get_org_context`); politica `org_isolation` lasă să treacă doar rândurile
acelei organizații. Fără `app.org_id` (autentificare, worker, migrări, seed) nu se
restrânge nimic. Rândurile cu `organization_id` nul (șabloane standard, audit global)
rămân vizibile. Politicile se aplică conexiunilor care nu sunt superutilizator
(proprietarul tabelelor este forțat prin FORCE ROW LEVEL SECURITY).

Tabelă nouă cu `organization_id` → migrarea apelează `enable_rls_sql(<tabela>)`.
"""

import uuid

from sqlalchemy import event, text
from sqlalchemy.orm import Session

_ORG = "nullif(current_setting('app.org_id', true), '')"
_USER = "nullif(current_setting('app.user_id', true), '')"

ORG_CONDITION = f"{_ORG} IS NULL OR organization_id IS NULL OR organization_id = {_ORG}::uuid"
# sarcinile private se văd doar de proprietar
TASK_PRIVATE_CONDITION = f"is_private IS NOT TRUE OR {_USER} IS NULL OR owner_user_id = {_USER}::uuid"


def enable_rls_sql(table: str) -> list[str]:
    return [
        f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY',
        f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY',
        f'DROP POLICY IF EXISTS org_isolation ON "{table}"',
        f'CREATE POLICY org_isolation ON "{table}" USING ({ORG_CONDITION}) WITH CHECK ({ORG_CONDITION})',
    ]


def disable_rls_sql(table: str) -> list[str]:
    return [
        f'DROP POLICY IF EXISTS org_isolation ON "{table}"',
        f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY',
        f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY',
    ]


def set_rls_context(db: Session, organization_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Fixează contextul pentru tranzacția curentă și pentru cele următoare ale sesiunii."""
    db.info["rls"] = (str(organization_id), str(user_id))
    _apply(db)


def _apply(db: Session) -> None:
    ctx = db.info.get("rls")
    if ctx:
        db.execute(
            text("SELECT set_config('app.org_id', :org, true), set_config('app.user_id', :usr, true)"),
            {"org": ctx[0], "usr": ctx[1]},
        )


@event.listens_for(Session, "after_begin")
def _after_begin(session: Session, transaction, connection) -> None:  # noqa: ANN001
    # set_config local dispare la commit; o tranzacție nouă a aceleiași cereri îl reia
    ctx = session.info.get("rls")
    if ctx:
        connection.execute(
            text("SELECT set_config('app.org_id', :org, true), set_config('app.user_id', :usr, true)"),
            {"org": ctx[0], "usr": ctx[1]},
        )


def count_unscoped(db: Session, query):  # noqa: ANN001
    """Rulează `query` (un scalar) fără restricția de organizație, apoi reia contextul.

    Pentru verificări care privesc toate organizațiile unui utilizator (ex.: mai are vreo organizație?)
    și care sub RLS ar vedea doar organizația curentă.
    """
    db.execute(text("SELECT set_config('app.org_id', '', true)"))
    try:
        return db.scalar(query)
    finally:
        _apply(db)
