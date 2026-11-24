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
    n = db.scalar(text("SELECT count(*) FROM alembic_version WHERE version_num = 'fix9_0001'"))
    assert n == 1
