# Strategia produsului: aplicație nouă sau extensie la 1C?

## 1. De ce furnizorii locali rămân pe 1C

| Motiv | Explicație |
|-------|-----------|
| Funcționalitate acumulată | o configurație ca „Бухгалтерия для Молдовы + НКО” are sute de documente, rapoarte reglementate și cazuri speciale scrise în ani — rescrierea cere mult timp |
| Model de afaceri | partenerii 1C câștigă din licențe, actualizări și deservire; un produs propriu înseamnă să renunți la un venit sigur |
| Clienții deja instalați | mii de baze în producție; migrarea lor e riscantă și costisitoare |
| Încredere | contabilii știu 1C, iar auditorii și SFS sunt obișnuiți cu rapoartele lui |

Deci nu au rămas pe 1C pentru că „1C e cea mai bună tehnologie”, ci pentru că e cel mai sigur pentru afacerea lor **astăzi**.

## 2. Cele trei variante

| | A. Extensie la 1C | B. Aplicație nouă + legătură cu 1C | C. Aplicație nouă, fără 1C |
|---|---|---|---|
| Ce este | AI, Drive, bănci, donatori ca extensie `.cfe` + serviciu web lângă 1C | aplicația noastră e principală; 1C rămâne doar sursă de migrare / funcționează în paralel o perioadă | totul în aplicația noastră |
| Timp până la ceva util | scurt | mediu | lung |
| Calitatea experienței | limitată de interfața și platforma 1C | modernă | modernă |
| Dependență de 1C (licențe, platformă, riscuri externe) | totală | doar la trecere | niciuna |
| Vânzare la alte organizații | doar celor cu aceeași configurație 1C | oricui are 1C (migrare ușoară) și celor fără 1C | oricui, dar trecerea de pe 1C e grea fără instrument |
| Teză / examen Web2 | slab (puțin web, mult cod 1C) | foarte bun | foarte bun |
| Risc | mic, dar „salvăm un sistem vechi” | mediu, controlabil | mare la început |

**Recomandare: varianta B.** Construim aplicația nouă ca produs principal și facem din **migrarea din 1C** un avantaj de vânzare: „îți aduc baza 1C în 1 zi, cu balanța verificată”. Integrarea REST cu 1C o folosim **doar pentru perioada de trecere** (lucru în paralel, sincronizare), nu ca arhitectură permanentă.

## 3. Cum obținem stabilitatea „testată de ani” a lui 1C

1. **Teste automate pe date reale**: luăm o bază 1C reală (copie), o migrăm, iar testele verifică că balanța, IPC21, 5-CON, ONG17 ies **identic** cu 1C pentru fiecare lună. Fiecare modificare de cod rulează aceste teste (GitHub Actions).
2. **Nucleul contabil mic și strict**: regula „Dt = Kt, într-o tranzacție, perioadă închisă protejată” este impusă de baza de date, nu doar de interfață.
3. **Pilot**: întâi organizația voastră, 2–3 luni în paralel cu 1C; abia apoi alți clienți.
4. **Versiuni și rollback**: fiecare actualizare se poate întoarce; backup automat zilnic.
5. **Jurnal de audit**: orice problemă se poate urmări până la cine/ce/când.

## 4. Unde stau datele: server central sau la client?

| Model | Cum funcționează | Pentru cine |
|-------|------------------|-------------|
| **Cloud (SaaS)** | o singură instalare pe serverul vostru; fiecare organizație are datele ei separate; clienții intră din browser | majoritatea clienților mici: nu au server, nu au IT |
| **Instalare la client (on-premise)** | aceeași aplicație în Docker pe serverul clientului | organizații mari sau cu cerințe stricte de date |
| ~~Pe fiecare calculator~~ | ~~bază locală pe fiecare PC~~ | **nu**: 10 contabili au nevoie de aceeași bază în timp real |

Arhitectura actuală suportă ambele modele fără schimbări: separarea pe `organization_id` permite SaaS, iar Docker Compose permite instalarea la client.

**Pentru SaaS mai trebuie** (înainte de primii clienți externi):
- server cu backup în altă locație și conexiune stabilă (sau găzduire la un centru de date);
- contract de prelucrare a datelor cu caracter personal (Legea 133/2011), înregistrarea ca operator/persoană împuternicită;
- HTTPS, monitorizare, plan de recuperare;
- condiții de abonament și facturare.

## 5. Pentru teză și pentru grant

- Teza: arhitectura B, migrarea din 1C cu reconcilierea balanței și asistentul AI sunt capitole puternice și originale.
- Grant: un software contabil local, modern, cu AI, care reduce dependența de platforme externe, se potrivește programelor de susținere a digitalizării și a IT-ului — merită verificate programele în vigoare (ex. cele ale agențiilor de dezvoltare / inovare și ale donatorilor internaționali) atunci când există un prototip funcțional.

## 6. Ce facem cu configurația 1C de pe server

Exportul configurației complete (cu modulele) ne dă **formulele** de calcul pe care le folosim ca **referință** (ce reguli contabile aplică, ce coduri, ce verificări) — logica o scriem din nou, în Python, și o verificăm prin testele de la punctul 3. Codul furnizorului nu se copiază în aplicație.
