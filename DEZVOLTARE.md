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

Gata: autentificare și roluri, „Bazele mele”, nucleul contabil, reguli cu corecții, factura primită (MF/OMVSD/materiale/servicii, fișa MF), ordinul de plată, execuția bugetului cu avertisment, închiderea lunii (amortizare, venituri din mijloace cu destinație specială, verificări), OSV, operațiunea manuală, Administrare (politica, reguli, perioade, conturi bancare, granturi, utilizatori, planul de conturi).

Rămas — câte o sesiune pe domeniu, fiecare pornind de aici:

| Domeniu | Ce cere | Unde în docs |
|---------|---------|--------------|
| Salarii + IPC21 | persons, contracts (CIM / civil), exemption_claims, contract_funding, payroll_periods / entries, individual_payments; cote din `tax_rates`; pasul „Calculul salariului”; plata cumulată (`payment_orders.kind = grouped_tax`) | ToR M3, `05-specificatie-IPC21.md`, `09-schimb-banci.md` |
| Rapoarte reglementate | ONG17, 5-CON (din `entry_lines`, `cost_items.con5_article`, execuția bugetului), calendarul raportărilor pe pagina inițială | `06-…ONG17.md`, `07-…5CON.md` |
| Bancă | `bank_formats`, import extras (TXT/DBF/DBO) cu deduplicare, export ordine, diferențe de curs (curs BNM) | `09-schimb-banci.md`, arhitectura §6 |
| Granturi avansat | versiuni de buget, tranșe, donatori, distribuirea stocurilor (regula 716/211 cu `budget_line = drop`), repartizarea pe granturi | arhitectura §9a, `11-reguli…` §2.3 |
| Bază nouă + profiluri | `features`, `organization_features`, `coa_templates`, expertul complet; partida simplă ÎI/GȚ | `13-tipuri-entitati-profiluri.md` |
| e-Factura, storage, OCR/AI | adaptoare externe, `ai_actions` (propuneri Aplică / Respinge) | arhitectura §5, §7, §9 |
| Import 1C | `onec_import_runs`, `onec_id_map`, solduri inițiale, reconcilierea balanței | ToR F7 |
| ~~Securitate~~ | gata: 2FA TOTP, parolă, RLS (`app/core/rls.py` — tabelă nouă cu `organization_id` → `enable_rls_sql` în migrare), audit vizibil, sarcini (`app/tasks/`) | arhitectura §10, §9c |
