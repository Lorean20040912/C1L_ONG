# Normalizarea și performanța bazei de date

Schema ([database/schema.dbml](../database/schema.dbml)) a fost verificată pe formele normale 1NF, 2NF, 3NF, BCNF și 4NF. Principiul ales:

> **Tabelele în care se lucrează (OLTP) sunt normalizate până la BCNF / 4NF.**
> **Denormalizarea se face doar intenționat, documentat și controlat** — pentru viteza rapoartelor sau pentru că legea contabilă cere „înghețarea” datelor unui document.

## 1. Verificarea pe forme normale și ce s-a corectat

| Forma | Cerința | Problemă găsită | Corectură |
|-------|---------|-----------------|-----------|
| **1NF** | valori atomice, fără grupuri repetate | `accounts.subconto1/2/3` — grup repetat de coloane | tabela **`account_analytics`** (cont, poziție, tip subconto) |
| 1NF | idem | `entry_lines.debit_subconto / credit_subconto` în JSON — analitica înregistrării nu putea fi indexată și nu avea chei străine | tabela **`entry_line_analytics`** (rând, D/K, tip, id) cu index pe `(tip, id)` → fișa contului pe contrapartidă se citește din index |
| **2NF** | fiecare atribut depinde de toată cheia (la chei compuse) | cheile sunt surogat (`uuid`), iar tabelele cu chei compuse (`account_turnovers`, `entry_line_analytics`) au doar atribute dependente de toată cheia | — |
| **3NF** | fără dependențe tranzitive | `invoices.number / issue_date / total_amount` și `payment_orders.number / payment_date / amount / currency` repetau antetul din `documents` | păstrate **o singură dată**, în `documents` |
| 3NF | fără atribute derivate | `invoices.amount_without_vat / vat_amount` = suma rândurilor | se calculează din `invoice_lines` (view) |
| **BCNF** | orice determinant e cheie | `entry_lines.budget_line_id → grant_id` (linia de buget determină grantul) — risc de neconcordanță | **cheie străină compusă** `entry_lines(budget_line_id, grant_id) → budget_lines(id, grant_id)`: baza de date nu permite o linie de buget a altui grant |
| **4NF** | fără dependențe multivaloare independente | `contracts.grant_id` — un contract poate fi finanțat din mai multe granturi | tabela **`contract_funding`** (contract × grant × %, cu perioadă) — previne și dubla finanțare |
| 4NF / timp | atribute care se schimbă în timp | `persons.dependents_count` — scutirile se schimbă și țin de contractul CIM de bază, nu de persoană | tabela **`exemption_claims`** (persoană, contract, tip scutire, perioadă, cererea semnată) |
| corectitudine | unicitate cu `NULL` | `tax_rates (code, applies_to, valid_from)` — în PostgreSQL două `NULL` nu sunt egale | `UNIQUE NULLS NOT DISTINCT` |
| corectitudine | cheie primară cu coloană opțională | `account_turnovers` avea cheia primară cu `grant_id`, dar rulajele fără proiect au `grant_id` gol — PostgreSQL nu acceptă `NULL` în cheia primară | cheie surogat `id` + `UNIQUE NULLS NOT DISTINCT` pe (organizație, cont, lună, grant, valută) |
| documentare | legături opționale | 91 de chei străine opționale marcate ca obligatorii în diagramă | notate `>?` (zero-sau-unu) — schimbă doar diagrama, nu baza |

## 2. Denormalizări păstrate intenționat (și de ce)

| Unde | Ce se repetă | De ce e corect așa |
|------|--------------|--------------------|
| `organization_id` în multe tabele (ex. `entry_lines`) | se poate deduce prin document | **izolarea datelor pe organizație** (Row-Level Security în PostgreSQL) și filtrare rapidă; e o cerință de securitate, nu o greșeală |
| `payment_orders.beneficiary_*` | se pot deduce din contrapartidă | **instantaneu (snapshot)**: documentul trebuie să păstreze exact ce s-a trimis la bancă, chiar dacă mai târziu se schimbă IBAN-ul contrapartidei |
| `payroll_entries` (impozit, scutire, net), `individual_payments.net` | se pot recalcula din cote | **rezultate înghețate**: cotele se schimbă; suma declarată în IPC21 nu are voie să se schimbe la recalcul. Cotele folosite sunt păstrate în `calc_details` |
| `tax_reports.data`, `report_packages`, `generated` | se pot regenera | raportul **depus** e un document juridic — se păstrează exact cum a fost depus |
| `document_extractions.fields`, `ai_*`, `audit_log.old/new_values` (JSON) | — | date semi-structurate (răspunsul AI, istoricul) care nu se folosesc în calcule contabile |
| **`account_turnovers`** | sumele din `entry_lines` | **tabel de totaluri** (ca „итоги” din registrele 1C) — vezi mai jos |

## 3. Viteza: cum se obține

### 3.1 Tabelul de totaluri `account_turnovers`

- La **înregistrarea** unui document, în **aceeași tranzacție** cu scrierea în `entry_lines`, se actualizează rulajele lunare: (organizație, cont, lună, grant, valută) → debit / credit.
- Balanța de verificare pe un an = citirea a câteva sute de rânduri de totaluri, nu a sute de mii de înregistrări → **milisecunde**.
- Corectitudinea: un test automat și o verificare nocturnă compară totalurile cu suma reală din `entry_lines`; orice diferență se semnalează (și se poate reconstrui).

### 3.2 Indexuri

| Index | Pentru ce |
|-------|-----------|
| `entry_lines (organization_id, entry_date)` | jurnalul de înregistrări pe perioadă |
| `entry_lines (debit_account_id, entry_date)`, `(credit_account_id, entry_date)` | fișa și analiza contului |
| `entry_lines (grant_id, budget_line_id, entry_date)` | execuția bugetului, raportul donatorului |
| `entry_lines (document_id)` | Dt/Kt al documentului, anularea înregistrării |
| `entry_line_analytics (subconto_type, ref_id)` | fișa pe contrapartidă / contract / persoană |
| `documents (organization_id, status)`, `(organization_id, sha256)` | listele de documente, dublurile de scanuri |
| `bank_transactions (dedup_key)` | import bancar fără dubluri |

### 3.3 Partiționare

`entry_lines` (cel mai mare tabel) se partiționează **pe ani** (`PARTITION BY RANGE (entry_date)`): interogările pe un an citesc doar partiția anului; arhivarea anilor vechi e simplă.

### 3.4 Alte reguli

- tranzacții scurte; calculele grele (rapoarte mari, OCR, import) în worker, nu în cererea HTTP;
- paginare pe server (keyset, nu `OFFSET` mare) pentru listele lungi;
- `EXPLAIN ANALYZE` pe interogările principale în testele de performanță, cu o bază de test de mărimea reală (ex. 5 ani × 10 organizații).

## 4. Pe scurt pentru susținere

1. Tabelele operaționale sunt în **BCNF**, iar relațiile multivaloare (contract × granturi, scutiri în timp) sunt separate conform **4NF**.
2. Integritatea e garantată de **baza de date** (chei străine, inclusiv compuse, unicitate, Dt = Kt în tranzacție), nu doar de aplicație.
3. Denormalizările sunt **puține, intenționate și controlate**: izolare pe organizație, instantanee juridice ale documentelor, rezultate înghețate ale calculelor și **un singur tabel de totaluri** pentru viteză, verificat automat.
