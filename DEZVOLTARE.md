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
| Rapoarte reglementate (ONG17, 5-CON, calendar) | gata; ONG17 și 5-CON și în XML; RSF2 (XML) din contabilitate |
| Bancă (formate, import cu deduplicare, export ordine, curs BNM, diferențe de curs) | gata |
| Granturi (donatori, versiuni, tranșe, distribuirea stocurilor, transfer 535, repartizare) | gata, inclusiv versiunile de buget cu proiect → aprobare (ADMIN_ROLES) și comparația cu realizatul |
| Baza nouă + profiluri de funcționalități | gata (expertul, `features`, partida simplă) |
| Import 1C, e-Factura, asistent AI, sarcini, audit | gata în forma de bază |
| Securitate (2FA, blocare la parole/2FA, RLS pe toate tabelele, parola inițială de schimbat, dezactivarea conturilor fără organizații) | gata, cu teste în `test_security.py`; punctele de revizuire sunt închise |
| Stocarea externă (Drive) și OCR | neîncepute (adaptoare externe) |
| Ecrane din lotul `fix6` (mijloace fixe din factură, punere în funcțiune, casare, amortizarea și achizițiile pe granturi, finanțare primită, pachet donator, tipuri de calcul, ajustarea perioadei, contrapartide, subdiviziuni, surse de documente, profiluri bănci, documente scanate AI) | gata: backend în `app/fix6/` (migrarea `fix6_0001`, teste în `tests/test_fix6.py`), ecrane în `frontend/src/screens/fix6/` |

## Puncte rămase deschise

1. **Cote salarizare**: valorile din `tax_rates` (CNAS, CNAM, impozit, scutiri) trebuie confirmate de contabilul-șef înainte de folosirea în producție.
2. **Schema XML 5-CON**: de aliniat exportul la `5CON_xsd_2023` față de varianta `5-CON` implementată (`docs/07-specificatie-5CON.md`).
3. ~~Versiuni de buget avansate~~ — făcut: `POST /budget-versions` cu `draft`, `PATCH`/`DELETE` pe proiect, `POST …/approve`, `GET /budget-comparison` (versiune vs versiune vs realizat); ecran în „Donatori, versiuni de buget și tranșe”.
4. **Docker**: fluxul a fost verificat fără Docker (indisponibil în mediul de verificare); `docker compose up --build` de rulat o dată pe o mașină cu Docker.
5. **RSF2** (`GET /organizations/{id}/reports/rsf2.xml?year=`, `regulated/rsf2.py`): structura XML este cea din `docs/exemple-fisc/rsf2.xml` (testată în `tests/test_rsf2.py`), dar corespondența conturi → rânduri este o ipoteză de lucru (configurația 1C `.cf` nu conține formularul RSF2 NGO; raportul ei `ГодовойБаланс` mapează doar formularul standard pe rânduri 010..880/010..230, folosit aici doar pentru conturile reglatoare: amortizarea imobilizărilor necorporale este 113/114/117, nu 112, iar fondurile ONG sunt 341.2/341.3 — corectate; vezi `docs/03`, secțiunea „Configurația .cf”) (descrisă în docstring-ul modulului; formularul oficial nu e în depozit) — de confirmat de contabilul-șef. Rămân 0: rândurile de active imobilizate în afara r030/r110 (terenuri, clădiri, obiecte de mică valoare etc.), r090/r230..r250/r270..r300 din bilanț, impozitul și rândurile r070..r100 din rezultat. Nu se completează (rămân goale/0) telefonul, adresa, site-ul, e-mailul (organizația nu are aceste câmpuri) și fișierele atașate (`dinamicAttachments`). Sumele sunt în lei întregi.
6. **Parcurgerea UI (Playwright, 1366px)**: toate ecranele se deschid fără erori de consolă sau 4xx/5xx neașteptate. Corectat: ecranele „5-CON/ONG17” (descifrarea unui rând) și „Asistent AI” se blocau (efect React care întorcea o valoare). Din cele 74 de legături din meniu, toate deschid ecrane reale (`node scripts/check-links.mjs` le verifică; cele 8 din lotul `fix7` au primit ecran). Curs BNM răspunde 502 dacă serverul nu are acces la bnm.md (comportament așteptat). `tests/test_smoke_get.py` verifică că niciun GET al organizației nu dă 5xx.
7. **Lotul `fix6` — limite cunoscute**: scanurile se păstrează în baza de date (`scanned_files`, max. 10 MB) — nu există încă sincronizare automată din Drive / folder (sursele din `document_sources` sunt doar configurate și atașate la încărcare); recunoașterea AI cere `ANTHROPIC_API_KEY` și citește doar PDF/PNG/JPEG; casarea folosește conturile din fișa mijlocului fix (`account_id`, `depreciation_account_id`) și un cont de cheltuieli ales la casare; tipurile de calcul (`payroll_calc_types`) sunt catalog și nu influențează încă calculul salariilor (care folosește `tax_rates`); „Amortizarea pe granturi” este calculată în ecran din fișele MF, fără endpoint propriu.
8. **Lotul `fix8` — TVA, Cartea mare, Verificarea contabilității**: `GET /organizations/{id}/reports/vat` (+ `.xlsx`) — jurnalul TVA al achizițiilor și decontul pe cote/luni din facturile primite (baza = suma rândului, TVA = bază × cotă; nu există documente de vânzare, deci TVA colectată lipsește); `GET …/reports/general-ledger` (+ `.xlsx`) — pe cont: sold inițial, rulaje lunare, sold final, din `account_turnovers`; `GET …/reports/accounting-check` — balanța echilibrată și totaluri = înregistrări, înregistrări fără corespondență validă, documente validate dar nepostate / incoerente, solduri anormale, cu trimitere la documente și fișa contului. Cod în `backend/app/fix8/`, ecrane în `frontend/src/screens/fix8/`, teste în `tests/test_fix8.py`. Fără migrare (nu s-a schimbat schema; head rămâne `fix6_0001`).
9. **Lotul `fix7` — bancă și casă, decont de avans, acte, rapoarte de achiziții**: cod în `backend/app/treasury/` (migrarea `fix7_0001`: tabelele `treasury_docs`, `treasury_doc_lines` cu RLS și 6 reguli noi în `posting_rules`; head Alembic `fix7_0001`), ecrane în `frontend/src/screens/treasury/`, teste în `tests/test_treasury.py`.
   - API `/organizations/{id}/treasury`: `GET /meta` (tipuri și operațiuni), `/docs` (listă cu filtre `kind`, `date_from/to`, `posted`, `q`, `bank_account_id`), `POST/PUT/DELETE /docs`, `POST /docs/{id}/preview|post|unpost`, `GET /docs/{id}/entries`, `/cash-balance`, `/advance-balance`; rapoarte `/reports/supplier-debts` (+`/moves`) și `/reports/received-invoices`.
   - Operațiunile standard folosesc `posting_rules` (cele vechi: `supplier_payment`, `tranche_received`, `membership_fee/receipt`; cele noi pe tipurile `bank_receipt`/`bank_payment`); partea de bancă o fixează contul contabil al contului bancar, partea de casă contul 241; operațiunile „alt cont”, avans acordat/restituit scriu direct contul ales. Decontul de avans și actul de servicii refolosesc regulile facturii (`expense`, `income_recognition`...), cu creditul pe contul de avans (analitic persoana), respectiv pe 521 (analitic furnizorul). Mijloacele fixe nu se introduc în decont/act (doar prin factură).
   - Verificări: casa nu poate ajunge pe minus (plata se refuză la înregistrare), cursul BNM obligatoriu pentru conturi în valută, câmpurile cerute de operațiune, blocare optimistă pe `version`, document înregistrat nemodificabil, ștergere doar pentru neînregistrat; ruta generică `/documents/{id}/post|unpost` refuză aceste documente. Depășirea bugetului la decont/act nu blochează, dar avertizează.
   - Tipărirea (ordin de încasare/plată în numerar, decont, act) se face din browser (fereastră de tipărire → „Salvare ca PDF”); nu există PDF generat pe server. „Datorii față de furnizori”: sold pe conturile `521*` cu analitica furnizorului, vechimea după FIFO (plățile sting cele mai vechi facturi), export CSV. „Facturi fiscale primite”: TVA = suma rândului × cotă/(100+cotă) (suma include TVA), ca în raportul TVA din `fix8`.
   - Limite: documentele nu se leagă încă de facturile achitate (stingerea se vede doar în „Datorii față de furnizori”); casa e doar în MDL; încasările de la clienți (vânzări) nu au operațiune proprie — se folosește „Alt cont”.
10. **Lotul `fix9` — parcurgerea finală**: toate legăturile din meniu (82) deschid ecrane reale; corectat: lipsa conturilor 241/243 în planul demonstrativ (migrarea `fix9_0001`, head Alembic `fix9_0001`), indexuri declarate în modele (`alembic check` curat), etichete românești și derulare orizontală în „Reguli de înregistrare”, mesaje de validare API traduse în `api/client.ts`, butonul „Importă din 1C” din Bazele mele, secțiunile Conducătorului / Vânzări / Depozit cu legături. Fluxurile bancă, casă, avans, act, mijloc fix, închiderea lunii și exporturile XML au rulat prin API. Rămas: crearea prin interfață a granturilor, salariilor și a importului de extras (verificate doar prin API/validări); „Curs BNM” cere acces la bnm.md; IPC21 din „Rapoarte reglementate” rămâne doar în ecranul Salarii; document cu același număr de factură nu e refuzat.
