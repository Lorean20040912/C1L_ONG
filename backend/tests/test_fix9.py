"""Bug-uri găsite la parcurgerea ecranelor (fix9)."""

from sqlalchemy import text

from app.seed import DEMO_ACCOUNTS


def test_planul_demonstrativ_acopera_conturile_regulilor(db):
    """Casa (241) lipsea din baza demo: plata în numerar nu se putea înregistra."""
    cod = {c for c, _, _ in DEMO_ACCOUNTS}
    folosite = set()
    for dt, kt in db.execute(text("SELECT debit_account, credit_account FROM posting_rules")):
        folosite.update(x for x in (dt, kt) if not x.startswith("{"))
    # conturile de rezultat/valută folosite doar de reguli opționale nu sunt cerute de fluxurile demo
    lipsa = {c for c in folosite if c in {"241", "242", "243", "521", "531", "533", "534"}} - cod
    assert not lipsa


def test_migrarea_fix9_adauga_casa(db):
    """Migrarea fix9_0001 face parte din istoricul aplicat (nu neapărat ultima: după ea vin alte migrări)."""
    import os

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(backend, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(backend, "alembic"))
    heads = set(db.scalars(text("SELECT version_num FROM alembic_version")))
    applied = {r.revision for h in heads for r in ScriptDirectory.from_config(cfg).walk_revisions(base="base", head=h)}
    assert "fix9_0001" in applied
