# Specificația raportului IPC21

**Formular:** IPC21 — *Declarație privind reținerea impozitului pe venit, a primelor de asigurare obligatorie de asistență medicală și a contribuțiilor de asigurări sociale de stat obligatorii calculate*
**Temei:** Anexa nr.1 la Ordinul Ministerului Finanțelor nr. 94 din 30.07.2020 (cu modificările ulterioare)
**Periodicitate:** lunar, termen — ziua 25 a lunii următoare
**Depunere:** fișier XML în e-Cabinet SFS

Sursa analizei: macheta `Tabele2024` și schema XML `ipc18_xsd2023` din configurația 1C (raportul `IPC18`). Structura de mai jos e cea pe care o generează aplicația noastră.

## 1. Structura formularului

| Bloc | Conținut | Element XML |
|------|----------|-------------|
| Antet | cod fiscal, denumire, cod CUATM, subdiviziunea SFS, cod CAEM, e-mail, telefon, cod CNAS | `dec/fiscCod/*` |
| Perioada | luna/anul declarat | `dec/peroidnalog/datefisc` |
| Tip declarație | primară / de corectare; rezident parc IT; corecție după control fiscal | `table1/ds`, `table1/it`, `table1/cf` (flag-uri) |
| **Tabelul 1** | venit achitat, impozit reținut, CNAM reținut — pe coduri de sursă de venit | `table1/row/r{cod}c{coloană}` |
| Suma de control | col.5 cod 61 − col.5 (coduri 41…49) | `summContr` |
| **Anexă la Tabelul 1** | impozitul din salarii repartizat pe subdiviziuni (cod localitate) | `dinamicTable/row[]` (c1…c5) + `total` |
| **Tabelul 1.1** | impozit la dividende din profitul 2023–2025 | `table11/row1…row3` (c3…c7) |
| **Tabelul 2 (nominal)** | fiecare persoană asigurată: perioadă, categorie, tarif, bază, indemnizații, contribuție CNAS | `dinamicTable2/row[]` (c1…c11) + `total` |
| **Tabelul 2 (totaluri)** | contribuții CNAS pe tarife (29%, 24%, 39%, 32%, agricultură, taxe fixe, zilieri 6%) | `table2/row/r…c9`, `r…c11` |
| Semnături | conducător, contabil-șef | `dec/director/*` |

## 2. Tabelul 1 — coduri de sursă de venit

Coloane: **4** = venit calculat și îndreptat spre achitare; **5** = impozit pe venit reținut; **6** = prime CNAM reținute (doar la salarii).

| Cod rând | Cod sursă | Ce intră | Sursa în aplicația noastră |
|---------:|-----------|----------|----------------------------|
| 11 | **SAL** | plăți salariale, art. 88 CF | `payroll_entries` cu contract **CIM** |
| 12 | SAL a) | salariile angajaților agenților economici cu activitate de bază programarea (Legea 1164/1997) — nu se aplică la ONG | `payroll_entries` CIM, categorie IT |
| 21 | DOB a) | dobânzi, art. 89 | operațiuni manuale |
| 22 | DOB b) | dobânzi către persoane fizice rezidente, art. 90¹ alin.(3⁷) | operațiuni manuale |
| 23 | VMS | dobânzi / creștere de capital din valori mobiliare de stat, art. 90¹ alin.(3⁸) | operațiuni manuale |
| 31 | **PL** | venituri din care se reține impozit, art. 90 (ex. **contracte civile / prestări servicii**) | `payroll_entries` cu contract **civil** |
| 32 | PLs | venituri scutite de reținerea prealabilă, art. 90 | contracte civile scutite |
| 41 | **FOL** | locațiune / arendă / uzufruct / superficie de la persoane fizice care nu sunt întreprinzători, **cu excepția terenurilor agricole** (acelea → PLs, rândul 32), art. 90¹ alin.(3) | documentul **„Plată către persoană fizică”** (`individual_payments`), tip *chirie* |
| 42 | PUB | dividende, art. 90¹ alin.(3¹) | — |
| 43 | RCS a) | sume retrase din capital (2010–2011) | — |
| 44 | ROY a) | redevențe către persoane fizice | — |
| 45 | ROY d) | câștiguri jocuri de noroc | — |
| 46 | — | câștiguri campanii promoționale și loterii | — |
| 47 | LIV | livrări producție fitotehnie/horticultură | — |
| 48 | CSM | comerț de consignație | — |
| 49 | DON pf | **donații către persoane fizice**, art. 90¹ alin.(3¹) — relevant pentru ONG | documente de plată cu tip „donație” |
| 491 | AGRAC | livrări produse agricole, art. 69¹⁸ | — |
| 51–56 | ROY, DOB c), CC, DIV, RCS b), PLT | venituri ale nerezidenților, art. 91 | plăți către nerezidenți |
| 61 | — | **TOTAL** | suma rândurilor |

> **Esențial pentru problema scutirii:** contractul civil se declară la **cod PL (rândul 31)**, nu la SAL. Scutirea personală ține de impozitul pe salariu (SAL). Dacă salarizarea calculează pe contract și păstrează codul de venit (`income_code`), Tabelul 1 se completează corect automat și scutirea nu se poate aplica greșit la PL.

### Chirie și alte plăți către persoane fizice (nu salarii)

**Problema în 1C:** raportul IPC ia rândul 41 (FOL) doar din registrele de salarizare (`СведенияОДоходахПН`, tip impozit `ПодоходныйНалогУИсточникаВыплатыFOL`). Chiria introdusă ca serviciu primit (`ПоступлениеТоваровУслуг`) nu ajunge în IPC → trebuia introdusă manual sau „deghizată” în calcul salarial.

**În aplicația noastră:** document separat **„Plată către persoană fizică”** (secțiunea *Achiziții* și *Salarii*):
1. se alege persoana fizică (IDNP), tipul plății: *chirie (FOL)*, *arendă teren agricol (PLs)*, *servicii / contract civil (PL)*, *donație (DON pf)*, *dobândă (DOB)*, *royalty (ROY)*…;
2. tipul determină **codul sursei de venit** și **cota de reținere** din `tax_rates` (valabilă la data plății);
3. la înregistrare: Dt cheltuieli / Kt datorii față de persoana fizică, Dt datorii / Kt impozit reținut;
4. IPC21 ia automat suma și impozitul pe codul respectiv; 5-CON ia cheltuiala pe articolul ei (ex. chiria → rândul 130).

## 3. Anexa la Tabelul 1 — repartizare pe subdiviziuni

`dinamicTable/row`: c1 nr. crt., c2 codul localității subdiviziunii (CUATM), c3 = c4 + c5, c4 impozit cod SAL, c5 impozit cod SAL a). Totalul col.3 = col.5 din Tabelul 1 pentru SAL + SAL a).
Sursa: `payroll_entries` grupate după `departments.cuatm`.

## 4. Tabelul 2 — evidența nominală CNAS

`dinamicTable2/row` (câte un rând pentru fiecare perioadă/categorie a persoanei):

| Câmp | Conținut | Sursa |
|------|----------|-------|
| c1 | nr. crt. | generat |
| c2 | numele, prenumele | `persons.full_name` |
| c3 | IDNP | `persons.idnp_enc` (decriptat la export) |
| c4 | CPAS | `persons.cpas` |
| c5, c6 | perioada de muncă / incapacitate: de la – până la | `payroll_entries.period_start/end` |
| c7, c71 | categoria persoanei asigurate | `payroll_entries.insured_category` |
| c8, c81 | tariful (%) / codul funcției | `payroll_entries.cnas_tariff`, `contracts.special_function_code` |
| c9 | baza de calcul a contribuției | `payroll_entries.cnas_base` |
| c10 | indemnizația pentru incapacitate temporară | `payroll_entries.sick_benefit` |
| c11 | contribuția CNAS calculată | `payroll_entries.cnas_employer` |

`total`: tot2c9, tot2c10, tot2c11.

Totaluri pe tarife (`table2/row`): `r11a` 29%, `r11b` 24%, `r12a` 39%, `r12b` 32%, `r13` medici independenți 24%, `r14a/b` agricultură, `r15` persoane fizice taxă fixă, `r16` liber-profesioniști justiție, `r17` zilieri 6%; coloana 9 = baza, 11 = contribuția. Rândurile `r2…`, `r3…` (col.10) — indemnizațiile pentru incapacitate temporară de muncă pe surse (secțiunile 2–3 ale totalurilor).

## 5. Reguli de verificare (înainte de export)

1. `r61c4 = Σ c4`, `r61c5 = Σ c5`, `r61c6 = Σ c6` pe toate codurile.
2. Suma de control: `summContr = r61c5 − (r41c5 + … + r49c5 + r491c5)`.
3. Anexa: `tot1c3 = r11c5 + r12c5`.
4. Tabelul 2: `tot2c11 = Σ r…c11` pe tarife; fiecare rând nominal are IDNP de 13 cifre și CPAS.
5. Contractele civile nu apar la SAL; contractele CIM nu apar la PL.
6. Pentru o declarație de corectare se păstrează versiunea inițială (`tax_reports` cu status și versiune).

## 6. Versionare

1C păstrează câte o machetă și o schemă XSD pentru fiecare modificare a formularului (2018, 2019, 2020, 2021, 2022, 2022_07, 2023, 2024). La noi: `report_forms` (code = `IPC21`, version, valid_from, structure) — perioada declarată alege automat versiunea corectă.
