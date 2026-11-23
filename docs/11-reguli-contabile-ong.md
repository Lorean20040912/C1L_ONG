# Regulile contabile ONG — baza formulelor din aplicație

Acest document este **sursa formulelor contabile (Dt/Kt)** pe care le folosește aplicația și **baza de cunoștințe** a asistentului AI. Unde configurația 1C ONG face altfel și contabilul corecta manual, regula de aici are prioritate.

## Surse

| Cod | Sursa |
|-----|-------|
| **[IM188]** | Indicațiile metodice privind particularitățile contabilității în organizațiile necomerciale, Ordinul MF nr. 188 din 30.12.2014 (completarea Planului general de conturi, Ordinul MF nr. 119 din 06.08.2013) |
| **[L287]** | Legea contabilității și raportării financiare nr. 287 din 15.12.2017 |
| **[SNC]** | Standardele Naționale de Contabilitate, Ordinul MF nr. 118 din 06.08.2013 (modificat prin Ordinul nr. 204 din 23.12.2015) |
| **[CM]** | Codul muncii nr. 154 din 28.03.2003 |
| **[L1420]** | Legea nr. 1420 din 31.10.2002 cu privire la filantropie și sponsorizare |
| **[INV60]** | Regulamentul privind inventarierea, Ordinul MF nr. 60 din 29.05.2012 |
| **[HG10]** | Regulamentul cu privire la delegarea salariaților, HG nr. 10 din 05.01.2012 |
| **[F24/36]** | Formularele tipizate de documente primare cu regim special, Ordinul MF nr. 24/36 din 25.03.1998 |
| **[ART]** | Articolul „Aspectele contabilității asistenței financiare a ONG-urilor din Republica Moldova” (situațiile 1–4) |
| **[MFG]** | Prezentarea „Managementul financiar al granturilor și contabilitatea proiectelor” (INSPIR Moldova) |
| **[SEM]** | Notițele contabilului-șef din consultații/seminare |

Textele integrale stau în folderul local `doc legistlative/` (nu se publică în GitHub) și sunt indexate pentru asistentul AI.

> **Regulă pentru asistent:** orice formulă propusă trebuie să citeze sursa (codul din tabel + articolul/situația). Dacă nu există sursă, asistentul spune asta și propune verificarea de către contabilul-șef.

---

## 1. Conturile principale ONG și analitica

| Cont | Conținut | Analitică obligatorie |
|------|----------|-----------------------|
| 234 (234.4) / 235* | Creanțe privind mijloacele cu destinație specială | **pe proiecte** [SEM] |
| 425 | Finanțări și încasări cu destinație specială pe termen lung | proiect / donator |
| 537 | Finanțări și încasări cu destinație specială curente | proiect / donator |
| 535 | Venituri anticipate curente | proiect |
| 341.2 | Fonduri de active imobilizate | proiect / MF |
| 341.3 | Fonduri de autofinanțare | — |
| 341.1 / 341.4 | contribuții inițiale ale fondatorilor / alte fonduri (planul 1C) | — |
| 544 | mijloace nepredestinate (ex. aport material la aderare) [SEM] | — |
| **616** | Venituri aferente mijloacelor cu destinație specială — **proiecte** | proiect |
| **617** | Venituri ale organizației (nepredestinate): **donații, ajutoare financiare, cotizații, cotizațiile sindicale** | **tipul venitului** [SEM] |
| 618 | Venituri din activitatea economică | — |
| **716** | Cheltuieli aferente mijloacelor cu destinație specială — **proiecte** (inclusiv **comisioanele bancare ale proiectului**) | proiect / linie de buget |
| **717** | Cheltuieli ale organizației (nepredestinate) | **pe proiecte** [SEM] |
| 718 | Cheltuieli din activitatea economică | — |

\* [ART] propune un cont nou 235 „Creanțe privind mijloacele cu destinație specială” prin politica contabilă; [SEM] folosește subcontul 234.4 cu analitică pe proiecte. **În aplicație contul se alege în politica contabilă** (setare), formulele rămân aceleași.

**În locul subdiviziunii, veniturile și cheltuielile se leagă de proiecte** [SEM] — în aplicație dimensiunea `grant_id` este obligatorie pe conturile 616/617/716/717, iar subdiviziunea rămâne opțională.

---

## 2. Granturi și mijloace cu destinație specială

### 2.1 Recunoașterea grantului [IM188], [ART sit.1], [SEM]

Mijloacele cu destinație specială se recunosc doar dacă există **certitudinea întemeiată** că: (1) vor fi primite; (2) condițiile vor fi îndeplinite; (3) valoarea poate fi determinată credibil.

**Setare per grant — momentul recunoașterii:**

| Varianta | Când | Formula |
|----------|------|---------|
| A. la semnare (contract autentificat / certitudine) | luna semnării, pe suma totală sau pe etapă | Dt 234.4/235 — Kt 425 (termen lung) sau 537 (curent) |
| B. la primirea tranșei (contract neautentificat, nu există certitudine) [SEM] | la încasare | Dt 242/243 — Kt 537 (direct) sau Dt 234 — Kt 537 + Dt 242 — Kt 234 în aceeași zi |

[SEM]: „Recunoaștem totul și stingem creanța pe etape” — varianta A, cu creanța stinsă la fiecare tranșă. Dacă contractul de finanțare e semnat dar nu e autentificat, finanțatorul nu e obligat să plătească → varianta B.

Încasarea tranșei: **Dt 242 / 243 — Kt 234.4 (235)**.

### 2.2 Cheltuieli curente din grant [IM188], [ART sit.2]

1. Cheltuiala: **Dt 716 — Kt 521 / 531 / 532 / 533 / 211 …** (cu proiect + linie de buget)
2. Concomitent, în aceeași sumă: **Dt 537 — Kt 616**

→ rezultatul pe proiect e zero (non-profit): venitul = cheltuiala.

### 2.3 Stocuri cumpărate din grant [ART sit.2]

- Intrare: Dt 211 — Kt 521; plata: Dt 521 — Kt 242.
- Distribuire: Dt 716 — Kt 211 **și** Dt 537 — Kt 616 (la valoarea distribuită).
- Partea nedistribuită: Dt 537 — Kt **535** (venituri anticipate); la distribuire ulterioară: Dt 716 — Kt 211 și **Dt 535 — Kt 616**.
- Politica contabilă poate trece toată suma stocurilor/avansurilor la 535 de la început (opțiune în setări).

**Avansuri** (ex. utilaj așteptat jumătate de an) [SEM]: suma nu rămâne mult timp în 537 — se regularizează prin 535.

### 2.4 Mijloace fixe din grant [IM188], [ART sit.3], [SEM]

- Intrare și punere în funcțiune: **Dt 123 — Kt 521**
- Formarea fondului: **Dt 425 (sau 537) — Kt 341.2** „Fonduri de active imobilizate”
- **Amortizarea: Dt 341.2 — Kt 124** (NU pe cheltuieli 713/716 — amortizarea diminuează fondul) [ART], [SEM]
- Plata furnizorului: Dt 521 — Kt 242.

> În aplicație: rândul de tip „Mijloc fix” dintr-o factură pe grant generează automat formarea fondului, iar închiderea lunii calculează amortizarea pe 341.2/124. Pentru MF procurate din mijloace nepredestinate sau din activitatea economică se aplică amortizarea obișnuită pe cheltuieli (setare pe sursa de finanțare a MF).

Activele primite gratuit/cu destinație specială **nu se vând**: se transmit gratuit altui ONG sau statului; vânzarea schimbă destinația (devine venit impozabil) [SEM]. Pentru imobilizări nu se aplică toate cele 3 metode de stabilire a valorii [SEM] — metoda se alege în politica contabilă.

### 2.5 Diferențe de curs valutar [IM188], [ART sit.4]

Diferențele aferente mijloacelor cu destinație specială (numerar, conturi, depozite, creanțe și datorii în valută) **nu merg la venituri/cheltuieli financiare**, ci **majorează sau diminuează 537/425**:

- curs nefavorabil la încasarea grantului: Dt 537 — Kt 234.4/235
- curs nefavorabil la plata datoriei: Dt 537 — Kt 521; favorabil: Dt 521 — Kt 537.

### 2.6 Dobânzi pe soldurile grantului [IM188], [ART]

Dobânda calculată pentru soldurile mijloacelor cu destinație specială: **Dt 234.4/235 — Kt 537** (majorează finanțarea, nu e venit financiar).

### 2.7 Mijloace neutilizate la finalul proiectului [IM188], [ART]

| Decizia finanțatorului | Formula |
|------------------------|---------|
| restituire | Dt 537 — Kt 242 / 243 |
| redirecționare la alt proiect | corespondență internă între subconturile 537/425 (proiect → proiect) |
| rămân la dispoziția ONG | Dt 425 / 537 — Kt 341.3 „Fonduri de autofinanțare” |

### 2.8 Cheltuieli peste buget și neeligibile [SEM], [MFG]

- **Ca să fie deductibile, cheltuielile trebuie să fie bugetate**; **tot ce depășește bugetul se adaugă la venitul impozabil** (ONG17, rândurile 010211 / 020).
- Cheltuiala înregistrată contabil nu e automat eligibilă: trebuie să fie **necesară, prevăzută în buget, eligibilă, efectiv suportată, justificată și în perioada eligibilă** [MFG].
- Exemple [SEM]: cafeaua nu e deductibilă la ONG; o cheltuială exagerată (ex. cel mai scump telefon) poate fi considerată utilizare contrar destinației.
- Rechizite procurate din bani rămași (nu din grant) → **717** [SEM].
- **Dubla finanțare** e interzisă: același cost nu se raportează în două proiecte; costurile comune (salarii, chirie, transport) se repartizează pe o bază documentată (pontaj, %) [MFG].

> În aplicație: la înregistrarea unei cheltuieli pe proiect, aplicația verifică linia de buget și disponibilul; peste buget → avertisment și marcaj `is_non_statutory` / „peste buget” care merge automat în ONG17.

---

## 3. Venituri nepredestinate: cotizații, donații, aderare

### 3.1 Cotizații de membru [SEM]

- Calcul: Dt 234 (pe membru) — Kt 617 (analitic „cotizații”).
- Încasare: Dt 241/242 — Kt 234.
- **La sfârșit de an — proces-verbal cu cine a achitat.**
- Cotizațiile **neachitate 3 ani se casează** (trec la 717); dacă membrul declară că nu poate plăti — proces-verbal.
- **Ieșirea din asociație se face prin cerere**; fără cerere, cotizația se datorează în continuare pentru perioada neachitată.
- **Adunarea generală** — de regulă aprilie–mai.
- Taxa de aderare (ex. 500 lei) — în 425 sau 537 dacă e cu destinație; aportul material nepredestinat — 544 [SEM].

### 3.2 Donații primite [L1420], [SEM]

- Donațiile, ajutoarele financiare — **617** cu analitică pe tipul venitului (dacă nu sunt cu destinație specială).
- **Cutie pentru donații** (bani sau lucruri) → **ordin/act de donații anonime**.
- **Act de evidență a donației** pentru fiecare donație.
- Dacă programul nu permite donația direct pe 262, se trece prin 211 [SEM] — în aplicație nu e nevoie de ocolire: documentul „Donație primită” are contul corect.

### 3.3 Donații acordate de ONG [L1420], [SEM]

- Evaluarea bunurilor donate: (1) **comisie** care analizează și documentează criteriile, sau (2) **după documentele producătorului**.
- **Cererea beneficiarului** că acceptă donația; **proces-verbal cu anexă** și confirmarea persoanei fizice.
- Donația către persoană fizică — se reflectă în **IPC21 la DON pf** (cota din `tax_rates`; [SEM] menționează 6% — de verificat la cota în vigoare).
- Dacă **persoana fizică face o donație** ONG-ului, ea însăși răspunde de impozitul pe venit; ONG-ul reține impozitul doar din salarii și contracte.

---

## 4. Personal: CIM, contracte civile, voluntari, membri

| Situație | Regula | Sursa |
|----------|--------|-------|
| Contabilul | **nu poate fi pe contract de voluntariat** → contract individual de muncă | [SEM], [CM] |
| Contabil cu volum mic (ex. evidența anuală, 1 oră/lună) | CIM cu timp de muncă redus, scris în contract; fără pontaj zilnic separat | [SEM] |
| Prestări servicii de la persoană fizică | **doar ocazional**; dacă e regulat/lunar → CIM. Se impozitează ca salariul (reținere la sursă, cod PL în IPC21) | [SEM] |
| Plata contractului civil eșalonată pe luni | permisă dacă e o singură prestare; „lunar” în contract = CIM | [SEM] |
| Manager de proiect angajat deja | CIM + **acord adițional** pentru funcția de manager de proiect | [SEM] |
| Membru al consiliului | nu are contract/salariu; nu se depune IRM; plățile către el au linie separată în IPC | [SEM] |
| Voluntari | contract de voluntariat + **carnet de voluntariat**; numărul lor merge în 5-CON rândul 320 | [SEM] |
| Fondul de salarizare în buget | în buget se includ **toate impozitele și contribuțiile** (sau se bugetează ca „fond de salarizare” cu tot cu ele) | [SEM] |
| Dividende | **nu se plătesc** — mijloacele sunt primite cu titlu gratuit | [SEM] |
| Împrumut de la fondator | contract de împrumut scris (când e nevoie de bani până la tranșă) | [SEM] |

---

## 5. Control intern, inventariere, raportare

- **Ordin semnat** pentru orice cerere a directorului care generează o operațiune [SEM].
- **Inventarierea** [INV60], [SEM]: anuală înainte de bilanț; ceruta prin notă informativă/cerere (nu prin poștă); dovada inventarierii păstrată chiar dacă nu se depune; **gestionarul nu face parte din comisia de inventariere**; lista comisiei semnată de director.
- **Bilanțul** se aprobă de **comisia de cenzori** [SEM].
- **Bugetul și nota explicativă la situațiile financiare se fac publice** [SEM]; statutul ONG are rolul licenței la SRL — activitățile se verifică față de statut [SEM].
- Situațiile financiare ONG: rândurile „alte venituri” 040 și 050 nu trebuie să fie egale [SEM].
- Activitățile din statut pot fi prestate „contra cost” (activitate economică, 618/718) [SEM].
- Statut de **utilitate publică** — cerințe la Agenția Servicii Publice (ASP) [SEM] — de detaliat.
- **Raportul narativ** pentru donator: obiective, activități (fără bani), rezultate — chiar dacă sunt puține cifre [SEM].
- **Publicitate Facebook** și alte servicii din străinătate: TVA la importul de servicii, declarația de rezidență a prestatorului; mai simplu prin companie din țară [SEM].
- Reconcilierea raportului financiar cu contabilitatea, pe fiecare linie de buget, **înainte** de trimitere [MFG] → în aplicație: verificare automată în pachetul pentru donator.

---

## 6. Cum devin aceste reguli cod

1. **Regulile de înregistrare nu sunt scrise fix în cod**, ci ca **șabloane de formule** în baza de date (`posting_rules`): tip document + tip operațiune + condiții (sursa de finanțare, tip rând, valută) → Dt / Kt / analitică, cu **sursa** (codul din tabelul de mai sus) și **perioada de valabilitate**.
2. **Politica contabilă a organizației** (`accounting_policies`) alege variantele: contul pentru creanțele de grant (234.4 sau 235), momentul recunoașterii (semnare / tranșă), stocurile la 535 integral sau parțial, metoda de evaluare a MF.
3. Contabilul-șef poate **corecta o formulă** din interfață (ca acum manual în 1C) — schimbarea are versiune, autor, motiv și se aplică doar documentelor noi sau, la cerere, și celor reînregistrate.
4. Fiecare situație din [ART] (1–4) și fiecare regulă de aici devine **test automat**: documentul de test → înregistrările așteptate.

### Neconcordanțe găsite în surse (de lămurit)

| Unde | Ce | Ce facem |
|------|----|----------|
| [ART] sit.3 | textul spune amortizare 500 lei, formula arată 600 lei | testul folosește calculul din politica de amortizare, nu cifra din text |
| [ART] dobânda | enunț 9%, calcul cu 10% | idem — se calculează din rata reală |
| [ART] vs [SEM] | contul creanței: 235 (cont nou) vs 234.4 | setare în politica contabilă |
| [SEM] | cota pentru donații în IPC (6%) | se ia din `tax_rates`, verificată de contabilul-șef |
