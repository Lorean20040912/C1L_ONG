# Arhitectura sistemului

## 1. Deciziile principale

| # | Decizie | De ce |
|---|---------|-------|
| D1 | **Sistem web propriu care înlocuiește 1C**, cu aceeași paradigmă de lucru (secțiuni → jurnale → formulare → Dt/Kt → rapoarte) | contabilii nu se reinstruiesc; scăpăm de licențe per utilizator și de erorile configurației |
| D2 | **Monolit modular** (un backend FastAPI cu module clare) + **worker** pentru sarcini lungi, nu microservicii | o echipă mică, un server; mai simplu de instalat, testat și explicat în teză |
| D3 | **PostgreSQL** ca singura sursă de adevăr; toate rapoartele se calculează din înregistrări | integritate contabilă, tranzacții, audit |
| D4 | **Formulare generate din metadate** (JSON) + **straturi de personalizare** peste metadate | documente noi fără formulare desenate de mână; asistentul AI poate schimba interfața fără a atinge codul |
| D5 | **AI doar propune, omul confirmă** | contabilitatea nu tolerează „halucinații”; răspunderea rămâne la contabil |
| D6 | **Stratul `storage`** cu adaptoare: Google Drive / folder local | organizația alege unde stau originalele; restul aplicației nu știe diferența |
| D7 | **Adaptoare de schimb**: bănci (TXT/DBF/DBO), e-Factura (API), 1C (migrare) | fiecare sistem extern izolat într-un modul, testat separat |
| D8 | **Docker Compose** pe serverul organizației | instalare și actualizare cu o comandă; datele rămân la organizație |

1C rămâne doar **sursa datelor pentru migrare** și referința pentru logica contabilă (vezi [03-analiza-configuratiei-1c.md](03-analiza-configuratiei-1c.md)).

## 2. Componente

```
                    ┌──────────────────────────── Browser (React) ─────────────────────────────┐
 Contabili ───────▶ │ AppShell tip 1C · Liste · Formulare · Rapoarte · Panou „Asistent AI” (chat) │
                    └───────────────────────────────┬──────────────────────────────────────────┘
                                                    │ HTTPS (JWT + 2FA)
┌───────────────────────────────────────────────────▼───────────────────────────────────────────────┐
│ nginx ──▶ API (FastAPI, monolit modular)                                                           │
│   auth · audit · metadata+ui_overrides · catalogs · documents · posting · payroll · fixed_assets   │
│   month_close · grants · reports · regulated (IPC21/5-CON/ONG17) · donor_reports · assistant       │
│   adaptoare: storage (Drive | local) · bank (TXT/DBF/DBO) · efactura (API SFS) · onec_import        │
└──────┬─────────────────────────────┬───────────────────────────────────────┬──────────────────────┘
       │                             │ sarcini în coadă                      │
┌──────▼──────┐               ┌──────▼──────┐     ┌──────────────────────────▼───────────────────────┐
│ PostgreSQL  │◀──────────────│   Redis     │────▶│ Worker: OCR · AI · import bancă · e-Factura sync  │
│ date+audit  │  backup zilnic└─────────────┘     │ pachete donatori · rapoarte mari · monitor legi  │
└─────────────┘                                   └──┬────────┬──────────┬──────────┬──────────┬─────┘
                                                     ▼        ▼          ▼          ▼          ▼
                                              Google Drive  Folder   e-Factura   Claude API  legis.md
                                              (OAuth)       local*   (SFS)       + web search BNM (curs)

 * folder local = director montat în containere (server / rețea) SAU agentul de sincronizare de pe calculatorul utilizatorului
```

## 3. Nucleul contabil — „înregistrarea” ca în 1C

1. Contabilul completează documentul și apasă **Înregistrează**.
2. Într-o **singură tranzacție**: verificarea perioadei (neînchisă) și a câmpurilor → **regula de înregistrare** a tipului de document generează `entry_lines` (Dt, Kt, sumă, subconto, grant, linie de buget, articol 5-CON, tip activitate ONG17) → verificarea Dt = Kt → `is_posted = true` → `audit_log`.
3. **Dt/Kt** arată înregistrările; **Anulare înregistrare** le șterge.
4. Toate rapoartele (OSV, IPC21, 5-CON, ONG17, execuția bugetului, raportul donatorului) se calculează din `entry_lines`, `payroll_entries`, `individual_payments`.

## 4. Mijloace fixe și închiderea lunii

**Problema în 1C:** mijlocul fix cere un document separat („Принятие к учету ОС”), iar o factură care conține și mijloc fix, și OMVSD, și materiale trebuie „spartă” în mai multe documente.

**La noi:**
- rândul facturii are `line_kind` = `fixed_asset | low_value_item | material | goods | service`;
- regula de înregistrare a facturii, pentru `fixed_asset`, **creează fișa** în `fixed_assets` (legată de rând) și, dacă e bifat „pus în funcțiune”, începe amortizarea de luna următoare;
- `month_close` este un **asistent cu pași**: fiecare pas (amortizare, salarii, repartizare pe granturi, diferențe de curs, venituri din mijloace cu destinație specială, închiderea conturilor, verificări) are *previzualizare → executare → anulare*; rezultatul e un document `month_close_runs` cu înregistrările lui — se vede clar ce a făcut închiderea.

## 5. Sursa documentelor (stratul `storage`)

```python
class StorageProvider(Protocol):
    def list(self, folder) -> list[FileInfo]: ...
    def read(self, file_id) -> bytes: ...
    def write(self, folder, name, data) -> FileInfo: ...
    def make_folder(self, path) -> FolderInfo: ...
    def link(self, file_id) -> str: ...
```

| Adaptor | Cum funcționează |
|---------|------------------|
| `GoogleDriveStorage` | OAuth 2.0, scope minim (doar folderele aplicației); fișierele rămân în Drive-ul organizației/utilizatorului |
| `LocalFolderStorage` | director montat în containere (`/data/docs`) — server sau share de rețea |
| `AgentStorage` | **agent de sincronizare** pe calculatorul utilizatorului (aplicație mică, ex. Python/Tauri): urmărește un folder ales, urcă fișierele noi prin API cu un token personal, creează local folderele cerute de aplicație (ex. pachetul donatorului) |

Fiecare document are `storage_connection_id` + `file_id` + `sha256` → dublurile se recunosc indiferent de sursă.

## 6. Schimbul cu banca (fișiere TXT / DBF / DBO)

- Un **profil de format** pe bancă (`bank_formats`): tipul fișierului, codificarea (CP1251/UTF-8/CP866), separatori sau lățimi fixe, maparea câmpurilor (dată, sumă, IBAN, IDNO, destinație, nr. document), direcția (import extras / export ordine).
- Parsere: `TxtParser` (delimitat sau lățime fixă), `DbfParser` (biblioteca `dbfread`), `DboParser` (formatul DBO al băncii — de configurat după fișierele-exemplu), `XmlParser`.
- Import: fișier → rânduri normalizate → căutare contrapartidă (IDNO/IBAN) → propunere cont + grant (după istoric / AI) → documente-ciornă → contabilul confirmă.
- **Idempotență**: fiecare rând primește o cheie (bancă + cont + dată + nr. document + sumă); un rând deja importat nu se mai creează.
- Export: ordinele de plată selectate → fișierul în formatul băncii → contabilul îl încarcă în sistemul băncii.

## 7. e-Factura

- `efactura` = client API + sincronizare periodică în worker.
- Primite: descărcare → `invoices` completate direct din XML (fără OCR) → legate de contrapartidă și contract.
- Emise: trimitere → urmărirea statutului în `efactura_messages`.
- Datele de acces / certificatul — criptate, doar pe server. Condițiile tehnice de acces se clarifică cu SFS înainte de etapa E8.

## 8. Rapoarte pentru donatori și pachetul de documente

```
Rapoarte/
└── Fundația Soros/
    └── SOR-2026-01/
        └── 2026-T3/
            ├── Raport financiar SOR-2026-01 T3.xlsx        ← șablonul donatorului, completat
            ├── Lista de verificare (documente lipsă).xlsx
            ├── 1.1 Salarii personal proiect/   contracte, pontaje, state de plată
            ├── 2.1 Echipament/                 facturi, acte de primire, ordine de plată
            └── 3.1 Transport și deplasări/     ordine de deplasare, bilete, deconturi
```

1. **Șablonul**: contabilul încarcă Excel-ul donatorului → AI-ul citește foile/celulele și propune maparea (`report_templates.mapping`: celulă ↔ linie de buget / perioadă / tip valoare) → contabilul confirmă o dată.
2. **Cerințele**: contabilul scrie în cuvinte ce documente cere donatorul → AI-ul le transformă în reguli structurate (`donor_requirements.rules`: pentru ce tip de cheltuială ce tipuri de documente) → contabilul le vede și le corectează.
3. **Generarea pachetului** (în worker): calculează cifrele din `entry_lines` → completează Excel-ul (openpyxl, păstrând formatarea donatorului) → creează folderele prin `storage` → pentru fiecare cheltuială pune documentele cerute (copie sau scurtătură) → lista documentelor lipsă.
4. Operatorii pot adăuga manual documente în folderele pe linii de buget; la sincronizare aplicația le recunoaște și le leagă de cheltuieli.

## 9. Asistentul AI

```
 Chat (panou lateral) ──▶ assistant (API) ──▶ Claude API (tool use)
                                │                    │ apelează instrumente
                                │◀───────────────────┘
                                ▼
          Instrumente (cu drepturile utilizatorului curent):
          search_documents · get_report · explain_entry · draft_document · propose_entries
          build_donor_package · web_search · get_ui_layout · propose_ui_change · remember_rule
                                ▼
          ai_actions (propuneri) ──▶ utilizatorul: Aplică / Respinge ──▶ audit_log
```

- **Contextul**: ecranul curent, documentul deschis, organizația, regulile memorate ale organizației (`ai_memory`).
- **Siguranță**: instrumentele de scriere creează doar **propuneri** (`ai_actions` cu statut `pending`); aplicarea o face utilizatorul. Asistentul nu poate închide perioade, șterge date sau schimba drepturi.
- **Căutare pe internet**: pentru legislație și cazuri neobișnuite; răspunsul conține sursele (linkuri); o cotă nouă găsită pe internet devine propunere în `legal_updates`, nu se aplică singură.
- **Date personale**: către AI se trimite minimul necesar; IDNP și IBAN se maschează în prompturi; organizația poate dezactiva trimiterea scanurilor.

### Personalizarea interfeței prin chat

Interfața se construiește din: **metadate de bază** (în cod) + **override-uri de organizație** + **override-uri de utilizator** (`ui_overrides`).

| Cererea utilizatorului | Ce schimbă asistentul |
|------------------------|------------------------|
| „Mută butonul Dt/Kt la început” | ordinea comenzilor în bara formularului |
| „Scrie «Proiect» în loc de «Grant»” | eticheta câmpului |
| „Ascunde coloana Subdiviziune” | vizibilitatea coloanei în listă |
| „La chirie pune implicit articolul 3.4” | valoare implicită |

Fiecare override are versiune, autor (utilizator / asistent), dată și poate fi anulat; cele de organizație cer aprobarea contabilului-șef. **Codul aplicației nu se modifică la runtime** — astfel nicio cerere din chat nu poate strica logica contabilă sau securitatea.

## 9a. Importul bugetului proiectului

```
Excel/PDF buget ──▶ worker: citire foi (openpyxl) ──▶ AI: recunoaște tabelul de buget
                     (linii, unități, cost unitar, total, cofinanțare, tranșe, valută)
                                      │
                                      ▼
                     budget_imports (statut: de verificat) ──▶ ecran de previzualizare
                                      │  contabilul corectează și confirmă
                                      ▼
   grants · grant_donors · budget_versions · budget_lines · grant_tranches · cost_items (propuse)
   + înregistrarea recunoașterii grantului după politica contabilă (posting_rules)
```

- Verificare automată: suma liniilor = totalul din fișier; suma tranșelor = contribuția donatorului; cofinanțarea pe fiecare linie ≤ totalul liniei.
- Maparea coloanelor confirmată se salvează pe donator (`report_templates` / șablonul de buget) → bugetul următor al aceluiași donator se citește fără întrebări.
- Modificările de buget aprobate de donator = **o nouă versiune** (`budget_versions`); liniile vechi rămân pentru istoric, execuția se compară cu versiunea în vigoare la data cheltuielii.

## 9b. Îmbunătățirea continuă prin asistent: canalele stabil și beta

**Ideea:** utilizatorul descrie în aplicație o eroare sau o îmbunătățire, asistentul o realizează ca **versiune beta**, utilizatorul o testează și decide dacă devine versiunea de bază. Nu mai e nevoie de un programator la fiecare schimbare mică, dar nici nu se riscă versiunea pe care lucrează contabilii.

### Două niveluri de modificări

| Nivel | Exemple | Unde se schimbă | Cât de repede |
|-------|---------|-----------------|---------------|
| **1. Configurare** | etichete, ordinea butoanelor, coloane, valori implicite, formule contabile (`posting_rules`), șabloane de rapoarte/forme, reguli ale asistentului | în baza de date, ca **variantă beta** a înregistrării (`is_beta`, `release_id`) | imediat, fără reinstalare |
| **2. Cod** | funcție nouă, eroare de calcul, ecran nou, import pentru o bancă nouă | în repository-ul de cod, pe o **ramură separată**, cu teste | minute–ore (build + teste) |

### Fluxul pentru modificările de cod

```
Utilizator ──▶ „aici e o eroare / aș vrea ca…” (+ captură, ecranul curent)
     │
     ▼
change_requests (statut: nouă) ──▶ asistentul clarifică cerința, o rezumă, utilizatorul confirmă
     │
     ▼
Agentul de dezvoltare (Claude, rulat pe server sau prin GitHub Actions)
  • creează ramura  beta/<nr-cerere>
  • scrie codul + testele, rulează testele local
  • deschide Pull Request (descrierea = cererea utilizatorului)
     │
     ▼
CI (GitHub Actions): toate testele — unitare, formule contabile, reconcilierea cu 1C,
IPC21 / 5-CON / ONG17 pe datele de test ──✗──▶ înapoi la agent (corectează) sau cererea eșuează
     │ ✓
     ▼
Instalare automată ca **mediu beta**: al doilea set de containere (aceeași imagine,
altă versiune), pe adresa beta.<domeniu>, cu o **copie a bazei de date** făcută la pornire
     │
     ▼
Utilizatorul testează în beta (bannerul „BETA v1.8.0-beta.3” vizibil pe fiecare ecran)
     │
     ├── „Promovează” ──▶ merge în main ─▶ release stabil vX.Y.Z ─▶ actualizarea producției
     │                     (backup automat înainte, migrări BD testate, rollback posibil)
     └── „Renunță”   ──▶ PR închis, mediul beta oprit, producția neatinsă
```

### Reguli de siguranță (obligatorii)

1. Agentul **nu are acces la baza de producție** și nici la secretele ei; lucrează doar cu codul și cu baza de test / copia beta.
2. **Nimic nu ajunge în producție fără „Promovează”** dat de un utilizator cu rol de administrator sau contabil-șef, și fără testele verzi.
3. Fiecare release stabil are **backup înainte** și **rollback** la versiunea anterioară dintr-un clic.
4. Migrările bazei de date din beta trebuie să fie reversibile; beta lucrează pe copie, deci datele reale nu sunt atinse până la promovare.
5. Modificările care ating **calculul impozitelor, formulele contabile sau securitatea** cer obligatoriu revizuirea diferențelor (diff) de către om înainte de promovare.
6. Toate cererile, versiunile și deciziile sunt în jurnalul de audit.

### Pentru vânzarea către alte organizații

- **Canal stabil** — toți clienții; **canal beta** — doar organizația voastră (și clienții care vor să testeze).
- Clienții primesc doar release-uri stabile, cu notă „ce s-a schimbat”; datele lor nu ajung niciodată în mediul beta.
- O modificare cerută de un client se poate face doar pentru el (configurare de nivel 1) sau, dacă e utilă tuturor, devine release.

## 10. Securitate

- Argon2 + 2FA TOTP; JWT acces 15 min + refresh rotativ; RBAC pe organizație; filtrare obligatorie după `organization_id` (test automat).
- IDNP, IBAN, tokenuri Drive, certificate e-Factura, chei API — criptate în BD sau doar în `.env` pe server; nimic în GitHub.
- HTTPS obligatoriu (inclusiv agentul de sincronizare); tokenurile agentului se pot revoca.
- `audit_log` pentru tot, inclusiv acțiunile asistentului; perioadele închise protejate.
- Backup zilnic `pg_dump`, păstrat 30 de zile; originalele documentelor rămân în Drive / folder.

## 11. Modulele backend

| Modul | Responsabilitate | Tabele principale |
|-------|------------------|-------------------|
| `auth`, `audit` | login, 2FA, roluri; jurnal | users, organization_members, audit_log |
| `metadata` | descrieri de formulare + override-uri | ui_overrides |
| `catalogs`, `documents` | CRUD generic, numerotare, blocare optimistă | counterparties, persons, documents, invoices… |
| `posting` | regulile de înregistrare; perioade | entry_lines, accounting_periods |
| `fixed_assets`, `month_close` | fișe MF din factură, amortizare, închiderea lunii | fixed_assets, month_close_runs |
| `payroll`, `individual_payments` | salarii pe contract; plăți către persoane fizice | contracts, payroll_entries, individual_payments |
| `taxes` | cote cu valabilitate, propuneri legislative | tax_rates, legal_updates |
| `grants`, `donor_reports` | granturi, bugete, șabloane, cerințe, pachete | grants, budget_lines, report_templates, donor_requirements, report_packages |
| `regulated`, `reports` | IPC21, 5-CON, ONG17, OSV… | report_forms, tax_reports, reporting_calendar |
| `storage`, `bank`, `efactura`, `onec_import` | adaptoarele externe | storage_connections, bank_formats, bank_imports, efactura_messages, onec_id_map |
| `assistant` | chat, instrumente, propuneri, memorie | ai_conversations, ai_messages, ai_actions, ai_memory |
| `budget_import` | citirea bugetului din Excel/PDF, previzualizare, crearea liniilor și tranșelor | budget_imports, budget_versions, budget_lines, grant_tranches |
| `releases` | cereri de modificare, versiuni beta, promovare / renunțare, rollback | change_requests, releases |

## 12. Modulele frontend

| Componentă | Rol |
|------------|-----|
| `AppShell` | bara de sus, secțiuni, file, taste globale |
| `ListForm`, `ObjectForm` | liste și formulare generice din metadate + override-uri |
| `RefField`, `MoneyField`, `DateField` | câmpuri tip 1C (selecție din catalog, „1 234,56”) |
| `PostingView` | Dt/Kt |
| `ScanReview` | scan + câmpuri extrase cu încredere |
| `ReportView` | parametri, tabel, descifrare, export |
| `BankImportWizard` | alegerea fișierului și a profilului → previzualizare → creare documente |
| `MonthCloseWizard` | pașii închiderii lunii cu previzualizare |
| `DonorPackageWizard` | șablon → cerințe → pachet → lista documentelor lipsă |
| `AssistantPanel` | chat-ul, propunerile cu butoane Aplică / Respinge |

Prototipul vizual: [`design/prototip.html`](../design/prototip.html); regulile de design: [08-design-interfata.md](08-design-interfata.md).

## 13. Structura repository-ului (planificată)

```
proeict/
├── docs/              ToR, arhitectură, analiza 1C, specificațiile rapoartelor, design
├── database/          schema.dbml (dbdiagram.io)
├── design/            prototipul HTML
├── backend/           FastAPI: app/<modul>/, alembic/, tests/
├── frontend/          React + Vite
├── sync-agent/        agentul de sincronizare pentru folderul local
└── docker-compose.yml
```
