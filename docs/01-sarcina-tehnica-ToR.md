# Sarcina tehnică (Terms of Reference) — Task 1

**Denumirea proiectului:** ContaHub ONG — sistem web de contabilitate pentru organizații necomerciale, înlocuitor al 1C:Contabilitate ONG, cu asistență AI
**Tip:** proiect examen „Programare Web 2” + teză de licență
**Autor:** _[numele studentului]_
**Versiune:** 0.2 · noiembrie 2026

---

## 1. Context și problema

În organizație, mai mulți contabili (sub coordonarea contabilului-șef) țin evidența ONG-urilor în configurația 1C:Contabilitate pentru ONG (platforma 1C:Întreprindere 8.3). Logica de bază și interfața sunt cunoscute și funcționează, dar:

| # | Problema | Consecința |
|---|----------|-----------|
| P1 | Configurația nu deosebește **contractul individual de muncă (CIM)** de **contractul civil** — scutirea personală se aplică cumulat la ambele venituri. | Impozit pe venit calculat greșit. |
| P2 | Documentele primare stau pe Google Drive și se introduc manual a doua oară în 1C. | Muncă dublă, erori. |
| P3 | Rapoartele pentru donatori (Soros etc.) se completează manual în Excel, pe linii de buget. | Ore pierdute la fiecare raportare. |
| P4 | Cotele de impozit și plafoanele se schimbă anual; actualizarea depinde de furnizor. | Risc de calcul cu cota veche. |
| P5 | Integrarea 1C cu alte sisteme (CSV/DBF/TXT) este instabilă. | Automatizarea nu e posibilă. |
| P6 | 1C cere licențe per utilizator și instalare pe fiecare calculator / RDP. | Cost și administrare. |

## 2. Scopul proiectului

Crearea unui **sistem web de contabilitate care înlocuiește complet 1C** pentru ONG-uri:
- **păstrează modul de lucru din 1C 8.3** (secțiuni, liste de documente, formulare, butoane „Înregistrează și închide”, „Dt/Kt”, rapoarte de tip balanță de verificare), ca contabilii să lucreze fără reinstruire;
- **păstrează logica contabilă** (planul de conturi, înregistrări contabile, regulile de calcul) cunoscută din configurația actuală, corectând erorile cunoscute;
- **preia toate datele existente din 1C** (cataloage, solduri, documente, istoricul înregistrărilor);
- adaugă ce 1C nu are: citirea automată a documentelor (OCR + AI), arhiva pe Google Drive pe linii de buget, rapoarte automate pentru donatori, monitorizarea legislației;
- rulează pe serverul organizației în **Docker**, accesat din browser de mai mulți contabili simultan.

## 3. Utilizatori și roluri

| Rol | Drepturi |
|-----|----------|
| **Administrator** | utilizatori, organizații, setări, backup |
| **Contabil-șef** | tot ce face contabilul + închiderea perioadei, aprobarea cotelor noi, interzicerea modificării perioadelor închise |
| **Contabil** | documente, înregistrări, salarii, rapoarte în organizațiile atribuite |
| **Manager de proiect** | vizualizează execuția bugetului grantului |
| **Auditor / Donator** | doar citire pentru un grant |

O instanță deservește **mai multe organizații**; fiecare contabil vede doar organizațiile atribuite.

## 4. Cerințe funcționale

### M0. Interfața de tip 1C 8.3
- F0.1 Panou de secțiuni în stânga, ca în „Бухгалтерия для Молдовы + НКО 3.0”: *Principal, Conducătorului, Bancă și casă, Vânzări, Achiziții, Depozit, Mijloace fixe și INM, Salarii și personal, Operațiuni, Rapoarte, Cataloage, Administrare, ONG*.
- F0.1a **Pagina inițială** cu calendarul obligațiilor de raportare pe organizație (ex. IPC21 lunar, 5-CON trimestrial, ONG17 anual): termen, raport, statut *Restanță / A rămas o săptămână / Prezentat*, cu deschiderea raportului dintr-un clic.
- F0.2 Fiecare document are **listă** (jurnal cu filtre, căutare, marcaj „înregistrat”) și **formular** (antet + tabel de rânduri + subsol cu totaluri).
- F0.3 Butoane standard: *Creare, Copiere, Înregistrare (postare), Anulare înregistrare, Înregistrează și închide, Marcare pentru ștergere, Dt/Kt (vizualizare înregistrări), Tipărire*.
- F0.4 Mai multe formulare deschise simultan, ca file (tab-uri); navigare din tastatură (Insert, F2, F8, Ctrl+Enter etc.).
- F0.5 Câmpuri de selecție din cataloage cu căutare rapidă; deschiderea elementului din câmp.
- F0.6 Aspectul este **inspirat** de 1C (paradigmă familiară), realizat cu componente proprii; nu se copiază resurse grafice sau cod al 1C.

### M1. Nucleul contabil
- F1.1 Planul de conturi conform Planului general de conturi contabile al RM, cu analitică (subconto) pe conturi.
- F1.2 Cataloage: organizații, contrapartide, contracte, persoane, conturi bancare, case, articole/servicii, mijloace fixe, unități de măsură, valute, surse de finanțare, granturi, linii de buget.
- F1.3 La **înregistrarea** unui document se generează automat înregistrări contabile (Dt/Kt) după reguli configurabile; anularea le șterge.
- F1.4 Operațiune manuală (înregistrări introduse direct).
- F1.5 Închiderea perioadei: după închidere documentele din perioadă nu pot fi modificate (doar de contabilul-șef).
- F1.6 Rapoarte standard: balanța de verificare (OSV), fișa contului, analiza contului, cartea mare, soldurile pe contrapartide, registrul documentelor.
- F1.7 Multi-valută, cu curs BNM descărcat automat.

### M2. Documente principale (versiunea 1)
Factură primită, factură emisă, ordin de plată (intrare/ieșire), extras bancar, dispoziție de încasare/plată (casă), avans spre decontare, act de prestări servicii, intrare/punere în funcțiune/amortizare mijloace fixe, calcul salariu, plata salariului, operațiune manuală.

### M2a. Plăți către persoane fizice (nu salarii)
- F2a.1 Document „Plată către persoană fizică” pentru chirie (FOL), arendă teren agricol (PLs), servicii/contract civil (PL), donații (DON pf), dobânzi, royalty.
- F2a.2 Tipul plății determină codul sursei de venit IPC21 și cota de reținere (din `tax_rates`).
- F2a.3 Impozitul reținut ajunge automat în IPC21, cheltuiala — în 5-CON și pe linia de buget a grantului. Nu mai e nevoie de introducere manuală în IPC.

### M3. Salarizare (CIM vs contract civil)
- F3.1 Fiecare contract are tip explicit: `CIM` sau `contract_civil`.
- F3.2 Calculul se face **pe contract**: la CIM — contribuții CNAS, prima CNAM, impozit pe venit cu scutire personală / pentru persoane întreținute (doar la locul de muncă de bază); la contractul civil — reținere la sursă **fără scutire personală**.
- F3.3 Repartizarea cheltuielilor salariale pe granturi și linii de buget.
- F3.4 Fișe de salariu, statul de plată, date pentru IPC21 / IALS.

### M4. Cote și legislație
- F4.1 Toate cotele, plafoanele și scutirile stau în BD cu perioadă de valabilitate și temei legal.
- F4.2 Calculul folosește automat cota valabilă la data operațiunii.
- F4.3 Agentul AI monitorizează sursele oficiale (legis.md, sfs.md, cnas.md) și propune modificări; **contabilul-șef le aprobă**, nimic nu se aplică automat.

### M5. Documente scanate, Google Drive, AI
- F5.1 Conectare Google Drive (OAuth, doar folderele selectate); originalele rămân pe Drive, sortate automat `Organizație / An / Grant / Linie de buget / Tip`.
- F5.2 OCR + AI creează **documentul-ciornă** (factură, ordin de plată) cu câmpurile completate și nivel de încredere; contabilul verifică side-by-side și înregistrează.
- F5.3 Import direct e-Factura (SFS) fără OCR.
- F5.4 Detectarea dublurilor (hash) și propunerea automată a grantului / liniei de buget.

### M6. Granturi și rapoarte pentru donatori
- F6.1 Donatori, granturi, linii de buget, alocarea cheltuielilor (din documente și salarii).
- F6.2 Execuția bugetului: planificat / cheltuit / rest, alertă la depășire.
- F6.3 Încărcarea șablonului Excel al donatorului, maparea celulelor (asistată de AI), generarea raportului completat + lista documentelor justificative cu linkuri Drive.

### M6a. Rapoarte fiscale și statistice
- F6a.1 **IPC21** (lunar, SFS) — darea de seamă privind reținerea impozitului pe venit, a contribuțiilor CNAS și a primelor CNAM, completată automat din salarizare, cu anexele pe persoane și pe tip de venit (CIM / contract civil separat).
- F6a.2 **5-CON** (trimestrial, BNS) — cheltuielile și costurile organizațiilor necomerciale, completat din înregistrările contabile pe articole de cheltuieli.
- F6a.3 **ONG17** (anual, SFS) — declarația organizației necomerciale, completată din datele anului, inclusiv anexa 1D (desemnarea procentuală). Lipsește în 1C actual — funcție nouă.
- Specificații detaliate: [IPC21](05-specificatie-IPC21.md), [ONG17](06-specificatie-ONG17.md), [5-CON](07-specificatie-5CON.md).
- F6a.4 Fiecare raport: completare automată → verificare și corectare manuală a celulelor → salvare versiune → export în formatul acceptat de **e-Cabinet SFS** / portalul BNS (XML/XLS) și tipărire PDF.
- F6a.5 Formularele de raport sunt descrise ca **șabloane cu versiune și perioadă de valabilitate** (când SFS/BNS schimbă formularul, se adaugă o versiune nouă; rapoartele vechi rămân pe forma veche).
- F6a.6 Descifrarea fiecărei cifre: clic pe celulă → lista înregistrărilor/documentelor din care provine.

### M7. Migrarea datelor din 1C
- F7.1 Import din 1C prin **interfața OData standard** a bazei 1C sau prin export XML (prelucrarea universală de export/import date XML).
- F7.2 Se importă: planul de conturi, cataloagele, soldurile inițiale la data trecerii, documentele și înregistrările contabile istorice (perioada aleasă).
- F7.3 Fiecare obiect importat păstrează GUID-ul din 1C → importul poate fi repetat fără dubluri.
- F7.4 Raport de reconciliere după import: balanța de verificare din aplicație = balanța din 1C, pe fiecare cont.
- F7.5 Perioadă de lucru în paralel 1C + aplicație până la confirmarea corectitudinii.

## 5. Cerințe nefuncționale

| Cod | Cerință |
|-----|---------|
| NF1 Securitate | HTTPS, parole Argon2, 2FA (TOTP), sesiuni cu expirare, roluri (RBAC), izolarea datelor pe organizație. |
| NF2 Audit | Orice modificare în `audit_log` (cine, ce, când, valoare veche/nouă); documentele înregistrate nu se șterg fizic, doar se marchează. |
| NF3 Integritate contabilă | Înregistrarea unui document și generarea înregistrărilor se fac într-o singură tranzacție BD; suma Dt = suma Kt verificată de BD. |
| NF4 Lucru simultan | 10+ contabili simultan; blocarea optimistă a documentului deschis de altcineva. |
| NF5 Date personale | Legea 133/2011: IDNP și IBAN criptate, acces minim necesar. |
| NF6 Stabilitate | Sarcinile grele (OCR, AI, import, rapoarte mari) în coadă cu reîncercări; backup automat zilnic BD. |
| NF7 Performanță | Liste și formulare < 1 s; balanța de verificare pe un an < 3 s. |
| NF8 Instalare | `docker compose up` pe server; actualizare fără pierderea datelor (migrări BD). |
| NF9 Limbă | Interfață în română și rusă (comutabilă per utilizator), ca în 1C. |

## 6. Stack tehnologic

| Strat | Tehnologie |
|-------|-----------|
| Frontend | React + TypeScript + Vite; tabele AG Grid / TanStack Table; UI cu tab-uri tip 1C |
| Backend | Python 3.12 + FastAPI, SQLAlchemy 2, Alembic, Pydantic |
| Bază de date | PostgreSQL 16 |
| Cozi | Redis + worker |
| OCR / AI | Azure Document Intelligence + LLM (Claude) |
| Fișiere | Google Drive API |
| Excel / PDF | openpyxl, WeasyPrint (formulare tipărite) |
| Import 1C | OData REST / XML |
| Infrastructură | Docker Compose (nginx, api, worker, postgres, redis), GitHub + GitHub Actions |

## 7. Etape și livrabile

| Etapă | Conținut |
|-------|----------|
| E1 | ToR, arhitectură, schema BD (dbdiagram.io), analiza configurației 1C |
| E2 | Autentificare, roluri, organizații, audit, Docker |
| E3 | Interfața de tip 1C (secțiuni, liste, formulare, tab-uri) |
| E4 | Nucleul contabil: plan de conturi, cataloage, înregistrări, OSV, fișa contului |
| E5 | Migrarea din 1C + reconcilierea balanței |
| E6 | Documentele bancă/casă/achiziții/vânzări cu reguli de înregistrare |
| E7 | Salarizare CIM / contract civil + cote cu valabilitate |
| E8 | Drive + OCR/AI pentru facturi și ordine de plată |
| E9 | Granturi, execuția bugetului, rapoarte donatori |
| E10 | Rapoarte fiscale IPC21, 5-CON, ONG17 + calendarul raportărilor |
| E11 | Monitor legislativ, testare, documentare, susținere |

## 8. Criterii de acceptare

1. După migrare, balanța de verificare din aplicație coincide cu balanța din 1C pe toate conturile, la aceeași dată.
2. Un contabil care lucrează în 1C 8.3 poate introduce și înregistra o factură primită fără instruire suplimentară.
3. Pentru o persoană cu CIM și contract civil în aceeași lună, scutirea personală se aplică doar venitului din CIM.
4. Schimbarea unei cote cu dată de intrare în vigoare nu modifică lunile anterioare.
5. O factură scanată pusă pe Drive devine document-ciornă completat; după verificare se înregistrează cu înregistrările corecte.
6. Raportul financiar al donatorului se generează din șablonul lui, cu totaluri egale cu execuția bugetului.
7. Un utilizator nu vede datele organizațiilor neatribuite (test automat).
8. Documentele dintr-o perioadă închisă nu pot fi modificate de un contabil obișnuit.
9. IPC21, 5-CON și ONG17 generate pentru o perioadă de test coincid cifră cu cifră cu cele generate de 1C pentru aceeași perioadă.

## 9. În afara scopului (versiunea 1)

- Depunerea directă a rapoartelor (semnare electronică și trimitere) — aplicația generează fișierul, depunerea se face pe e-Cabinet SFS / portalul BNS.
- Rapoartele fiscale în afara celor din M6a (TVA, situații financiare complete etc.) — versiunea 2.
- Contabilitatea stocurilor complexă (producție, mai multe depozite cu costuri FIFO avansate).
- Aplicație mobilă nativă; plăți bancare inițiate din aplicație.
