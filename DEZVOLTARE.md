# Ghid de dezvoltare ContaHub

Punctul de pornire pentru orice sesiune nouă de lucru: citiți acest fișier, nu istoricul. Cerințele sunt în `docs/` (ToR, arhitectura, regulile contabile), schema în `database/schema.dbml` — **nu se modifică**; deciziile noi se notează în descrierea PR-ului.

## Pornire și teste

```bash
docker compose up --build                      # http://localhost:8080, demo@contahub.local / demo12345 (administrator)
cd backend && pytest                           # PostgreSQL real: TEST_DATABASE_URL (implicit contahub_test pe localhost)
cd backend && DATABASE_URL=... alembic check   # migrările corespund modelelor
cd frontend && npm run build                   # tsc + vite
```

Commit-uri mici, în română, autor `Lorean Mandrescu`, fără mențiuni AI. Ramura: `feature/schelet-aplicatie`, PR #1 către `main` (fără merge).

## Principii (nu se încalcă)

1. **Izolarea pe organizație**: orice rută cu date contabile e sub `/organizations/{organization_id}/…` și primește `ctx: OrgContext = Depends(get_org_context)`; fiecare interogare filtrează după `ctx.organization_id`; orice id primit (cont, grant, contrapartidă...) se verifică că aparține organizației. Test de izolare pentru fiecare rută nouă.
2. **Rolurile**: `POSTING_ROLES` (documente), `ADMIN_ROLES` (setări contabile), `USER_ADMIN_ROLES` (utilizatori) din `app/auth/deps.py`; `ctx.require(...)`. În interfață `can(role, ...)` din `shell/tabs.ts`.
3. **Înregistrările se scriu doar prin `app/posting/engine.py`** (`post_document` / `unpost_document`): tranzacție unică cu `account_turnovers` și audit. Nicio rută nu scrie direct în `entry_lines`.
4. **Formulele sunt date** (`posting_rules`), nu cod: un document își transformă rândurile în `OperationInput`, `build_lines` alege regula (vezi docstring-ul din `app/posting/rules.py`). Regulă standard nouă = migrare Alembic cu `source_ref` din `docs/11`. Conturile alese în politica contabilă: `{grant_receivable}`.
5. **Funcțiile de serviciu nu fac commit**; ruta face `db.commit()` sau `db.rollback()` la `PostingError` (→ 422, `DocumentNotFound` → 404).
6. **Audit**: `write_audit(...)` pentru orice creare / modificare / ștergere.

## Harta codului

| Unde | Ce |
|------|----|
| `backend/app/posting/` | motorul (`engine.py`), regulile (`rules.py`, `rules_router.py`), politica / perioade / conturi (`admin_router.py`), Dt/Kt manual (`router.py`) |
| `backend/app/documents/` | factura (`invoices_router.py`), ordinul de plată (`payments_router.py`), transformarea în operațiuni (`posting.py`) |
| `backend/app/grants/` | granturi și linii (`admin_router.py`), execuția bugetului (`budget.py`, `router.py`) |
| `backend/app/month_close/` | amortizarea (`depreciation.py`), venituri și verificări (`steps.py`), pașii și documentele lor (`service.py`), fișele MF (`router.py`) |
| `backend/app/reports/` | balanța de verificare (OSV) |
| `backend/app/auth/`, `workspaces/`, `catalogs/` | autentificare, utilizatori, „Bazele mele”, cataloage |
| `backend/alembic/versions/` | 0001 nucleul · 0002 regulile ONG · 0003 factură/plată · 0004 închiderea lunii · 0005 regula veniturilor |
| `frontend/src/shell/` | `AppShell`, filele (`tabs.ts`: tipuri de ecran, `SCREEN_LINKS`, roluri), secțiunile |
| `frontend/src/screens/` | ecranele; `screens/admin/` — Administrare |
| `frontend/src/catalog/useCatalogs.ts` | cataloagele partajate; `refreshCatalogs(orgId)` după modificări |

**Ecran nou**: componentă în `screens/`, tip nou în `TabKind`, legătură în `SCREEN_LINKS` (titlul din `sections.ts`), `case` în `Screen` din `AppShell.tsx`. Formularele de document urmează `InvoiceForm.tsx` (salvare → id real în filă, `notifyDocumentsChanged`, Ctrl+Enter / Ctrl+S).

**Document nou cu înregistrare**: model + migrare → funcție `xxx_operations(...)` care produce `OperationInput` → `build_lines` → `post_document`; reguli standard în migrare; ruta generică `/documents/{id}/post` îl refuză dacă e în `DEDICATED_ROUTES`.

## Stadiul

Verificat cap-coadă prin API (uvicorn + PostgreSQL + Redis locale; același flux ca în `docker compose`): autentificare, bază nouă (expert), politică contabilă, factură + plată, închiderea lunii (amortizare, salarii, diferențe de curs, venituri, `account_closing`, verificări), transfer pe 535, închiderea perioadei, ONG17 (Excel), IPC21 (JSON și XML), import extras MAIB + înregistrare. Un singur head Alembic (`mrg_0009`); `alembic upgrade head` de la zero și `alembic check` sunt curate.

| Modul | Stare |
|-------|-------|
| Nucleu, facturi, ordine de plată, execuția bugetului, OSV, operațiune manuală, Administrare | gata |
| Închiderea lunii (toți pașii, inclusiv închiderea conturilor 6/7) | gata; pașii nu rulează și nu se anulează în luna închisă |
| Salarii + IPC21 | gata (persoane, contracte, pontaj, plata cumulată, declarația); **cotele** de confirmat de contabilul-șef |
| Rapoarte reglementate (ONG17, 5-CON, calendar) | gata; ONG17 doar Excel (nu are format XML) |
| Bancă (formate, import cu deduplicare, export ordine, curs BNM, diferențe de curs) | gata |
| Granturi (donatori, versiuni, tranșe, distribuirea stocurilor, transfer 535, repartizare) | gata, inclusiv versiunile de buget cu proiect → aprobare (ADMIN_ROLES) și comparația cu realizatul |
| Baza nouă + profiluri de funcționalități | gata (expertul, `features`, partida simplă) |
| Import 1C, e-Factura, asistent AI, sarcini, audit | gata în forma de bază |
| Securitate (2FA, blocare la parole/2FA, RLS pe toate tabelele, parola inițială de schimbat, dezactivarea conturilor fără organizații) | gata, cu teste în `test_security.py`; punctele de revizuire sunt închise |
| Stocarea externă (Drive) și OCR | neîncepute (adaptoare externe) |

## Puncte rămase deschise

1. **Cote salarizare**: valorile din `tax_rates` (CNAS, CNAM, impozit, scutiri) trebuie confirmate de contabilul-șef înainte de folosirea în producție.
2. **Schema XML 5-CON**: de aliniat exportul la `5CON_xsd_2023` față de varianta `5-CON` implementată (`docs/07-specificatie-5CON.md`).
3. ~~Versiuni de buget avansate~~ — făcut: `POST /budget-versions` cu `draft`, `PATCH`/`DELETE` pe proiect, `POST …/approve`, `GET /budget-comparison` (versiune vs versiune vs realizat); ecran în „Donatori, versiuni de buget și tranșe”.
4. **Docker**: fluxul a fost verificat fără Docker (indisponibil în mediul de verificare); `docker compose up --build` de rulat o dată pe o mașină cu Docker.
