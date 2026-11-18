# Arhitectura sistemului

## Decizia: sistem web propriu care înlocuiește 1C, cu aceeași logică de lucru

1C rămâne doar **sursa datelor pentru migrare** și referința pentru logica contabilă. După perioada de lucru în paralel, toți contabilii lucrează în aplicația web.

Ce preluăm din 1C:
- **paradigma de interfață**: secțiuni → liste (jurnale) → formulare → înregistrări Dt/Kt → rapoarte;
- **modelul de date**: cataloage, documente, registre (contabil, salarii), planul de conturi cu subconto;
- **regulile de calcul și de înregistrare** (ce înregistrări generează fiecare document);
- **datele**: cataloage, solduri, istoric.

Ce **nu** copiem: codul sursă, imaginile și resursele 1C (proprietate 1C/furnizor). Reconstruim logica pe baza analizei și o scriem din nou în Python.

## Componente (Docker Compose pe server)

```
 Contabili (browser)                                   Google Drive   Azure OCR / LLM   legis.md, BNM
        │ HTTPS                                              ▲              ▲                ▲
 ┌──────▼──────┐   ┌──────────────────────┐   ┌──────────────┴──────────────┴────────────────┴─┐
 │   nginx     │──▶│  api  (FastAPI)       │──▶│ worker: OCR, AI, import 1C, rapoarte, curs BNM │
 │ + frontend  │   │  auth · cataloage ·   │   └──────────────────────┬─────────────────────────┘
 │ (React)     │   │  documente · posting ·│          ┌───────────────┘
 └─────────────┘   │  rapoarte · salarii   │   ┌──────▼──────┐   ┌──────────────┐
                   └──────────┬────────────┘   │   redis     │   │ 1C (doar la  │
                              │                └─────────────┘   │ migrare,     │
                       ┌──────▼──────┐                           │ prin OData)  │
                       │ postgres    │◀── backup zilnic          └──────────────┘
                       └─────────────┘
```

## Nucleul contabil (cum funcționează „înregistrarea” ca în 1C)

1. Contabilul completează documentul (ex. *Factură primită*) și apasă **Înregistrează**.
2. Backend-ul, într-o **singură tranzacție**:
   - verifică perioada (nu e închisă), câmpurile obligatorii;
   - apelează **regula de înregistrare** a tipului de document → generează rânduri în `entry_lines` (Dt, Kt, sumă, subconto, grant, linie de buget);
   - verifică Dt = Kt;
   - setează `is_posted = true` și scrie în `audit_log`.
3. **Dt/Kt** afișează înregistrările generate; **Anulare înregistrare** le șterge.
4. Rapoartele (OSV, fișa contului) se calculează din `entry_lines` + soldurile inițiale.

Regulile de înregistrare sunt cod Python pe tip de document (testat cu teste unitare), cu conturile implicite configurabile în setări — echivalentul modulelor de obiect din 1C.

## Interfața de tip 1C 8.3

- **Panou de secțiuni** stânga, **panou de navigare** al secțiunii (liste de documente, cataloage, rapoarte).
- **Tab-uri** pentru formularele deschise (mai multe documente deschise simultan).
- **Liste**: tabel virtualizat (mii de rânduri fără încetinire), iconiță înregistrat/neînregistrat/marcat pentru ștergere, filtru perioadă, căutare.
- **Formular document**: antet, tabel de rânduri editabil inline, subsol cu totaluri, bara de butoane standard.
- **Comenzi rapide**: Insert (rând nou), F2 (editare), F8 (copiere), Ctrl+Enter (înregistrează și închide), Ctrl+S.
- Formularele se generează din **metadate** (descrierea câmpurilor fiecărui document), ca în 1C — un document nou se adaugă fără a scrie un formular de la zero.

## Migrarea din 1C

| Pas | Detalii |
|-----|---------|
| 1. Analiza configurației | export configurație în fișiere XML (Configurator) → lista cataloagelor, documentelor, registrelor, câmpurilor → maparea către tabelele noastre |
| 2. Conectare la date | interfața **OData standard** a bazei 1C (REST, JSON) sau export XML |
| 3. Import | ordinea: plan de conturi → cataloage → solduri inițiale → documente → înregistrări; GUID-ul 1C păstrat în `onec_id_map` |
| 4. Reconciliere | balanța de verificare aplicație vs 1C pe fiecare cont; diferențele în raport |
| 5. Lucru în paralel | 1–2 luni, apoi 1C trece în mod doar citire |

## Salarizare CIM / contract civil

`contracts.type` (`cim`/`civil`); calculul în `payroll_entries` se face **pe contract**. Scutirea personală se aplică doar dacă `type = cim` și `is_main_job = true`. Cotele se iau din `tax_rates` valabile la data calculului.

## Cote de impozit și legislație

Cotele au `valid_from`/`valid_to` și temei legal. Worker-ul verifică sursele oficiale, AI-ul propune modificări în `legal_updates`, contabilul-șef aprobă → versiune nouă în `tax_rates`.

## Securitate

- Argon2 + 2FA TOTP; sesiuni cu expirare; RBAC pe organizație.
- Fiecare interogare filtrată după `organization_id` (test automat).
- IDNP/IBAN criptate; secretele doar în `.env` pe server, nu în GitHub.
- `audit_log` pentru tot; perioadele închise protejate.
- Backup zilnic `pg_dump` + păstrare 30 zile; originalele documentelor pe Drive.

## Modulele backend (FastAPI)

| Modul | Responsabilitate | Tabele principale |
|-------|------------------|-------------------|
| `auth` | login, 2FA, sesiuni, roluri pe organizație | users, organization_members |
| `audit` | jurnalul modificărilor (middleware pe toate scrierile) | audit_log |
| `metadata` | descrierile documentelor/cataloagelor pentru formularele generice | (fișiere JSON în cod) |
| `catalogs` | CRUD generic pentru cataloage | counterparties, persons, accounts, departments, cost_items… |
| `documents` | CRUD generic pentru documente, numerotare, blocare optimistă (`version`) | documents, invoices, payment_orders, individual_payments… |
| `posting` | **regulile de înregistrare** (câte o clasă pe tip de document) → `entry_lines`; anulare; perioade închise | entry_lines, accounting_periods |
| `payroll` | calcul pe contract, scutiri, CNAS/CNAM, coduri de venit | contracts, payroll_entries |
| `taxes` | cote cu valabilitate, propuneri legislative | tax_rates, legal_updates |
| `grants` | proiecte, donatori, linii de buget, repartizare | grants, grant_donors, budget_lines, allocations |
| `reports` | OSV, fișa contului, execuția bugetului | (citește entry_lines) |
| `regulated` | IPC21, 5-CON, ONG17: calcul → verificare → XML/PDF; calendarul raportărilor | report_forms, tax_reports, reporting_calendar |
| `donor_reports` | completarea șabloanelor Excel ale donatorilor | report_templates, generated_reports |
| `drive` + `ai` | sincronizare Drive, OCR, extragere, propuneri de alocare (în worker) | documents, document_extractions |
| `onec_import` | citirea bazei 1C, maparea GUID-urilor, reconciliere | onec_import_runs, onec_id_map |

Regula de aur: **nicio sumă din rapoarte nu se introduce de mână** — totul vine din `entry_lines`, `payroll_entries` și `individual_payments`; corecțiile manuale într-un raport se salvează separat (`tax_reports.manual_overrides`) și sunt vizibile.

## Modulele frontend (React)

| Componentă | Rol |
|------------|-----|
| `AppShell` | bara de sus, panoul de secțiuni, filele, tastele globale |
| `SectionPanel` | linkurile secțiunii (din metadate) |
| `ListForm` | jurnal generic: bara de comenzi, filtre, tabel virtualizat, statut ✓/○/✕ |
| `ObjectForm` | formular generic: antet + secțiuni tabelare + subsol, din metadate |
| `RefField`, `DateField`, `MoneyField` | câmpuri cu selecție din catalog, dată, sumă (format „1 234,56”) |
| `PostingView` | fereastra Dt/Kt |
| `ScanReview` | scanul + câmpurile extrase de AI, cu nivel de încredere |
| `ReportView` | parametri, tabel, descifrarea celulelor, export |
| `HomePage` | calendarul raportărilor, documente de verificat, execuția bugetelor |

Prototipul vizual al acestor componente: [`design/prototip.html`](../design/prototip.html); regulile de design: [08-design-interfata.md](08-design-interfata.md).

## Structura repository-ului (planificată)

```
proeict/
├── docs/              ToR, arhitectură, analiza configurației 1C
├── database/          schema.dbml (dbdiagram.io)
├── backend/           FastAPI: app/{catalogs,documents,posting,payroll,reports,onec_import}, alembic/, tests/
├── frontend/          React + Vite: shell tip 1C, liste, formulare din metadate
├── onec-analysis/     exportul configurației 1C (NU se pune în GitHub public)
└── docker-compose.yml
```
