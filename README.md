# ContaHub ONG

Sistem web de contabilitate pentru organizații necomerciale din Republica Moldova, care înlocuiește 1C:Contabilitate ONG păstrând modul de lucru familiar din 1C 8.3, cu asistență AI. Rulează pe server prin Docker, pentru mai mulți contabili simultan.

Proiect pentru examenul **Programare Web 2** și teza de licență.

## Ce face
- citește automat facturile și ordinele de plată scanate (OCR + AI) direct de pe Google Drive;
- păstrează originalele pe Drive, sortate pe granturi și linii de buget;
- calculează corect salariile, separând **contractul individual de muncă** de **contractul civil** (scutirea personală doar la CIM);
- completează automat rapoartele Excel ale donatorilor;
- ține cotele de impozit cu perioadă de valabilitate și propune actualizări din legislație (aprobate de contabil);
- interfață de tip 1C 8.3: secțiuni, jurnale, formulare, înregistrare Dt/Kt, balanța de verificare;
- migrează toate datele existente din 1C (OData / XML) cu reconcilierea balanței.

## Documentație
| Fișier | Conținut |
|--------|----------|
| [docs/01-sarcina-tehnica-ToR.md](docs/01-sarcina-tehnica-ToR.md) | Task 1 — Sarcina tehnică (ToR) |
| [docs/02-arhitectura.md](docs/02-arhitectura.md) | Arhitectura și deciziile tehnice |
| [docs/03-analiza-configuratiei-1c.md](docs/03-analiza-configuratiei-1c.md) | Analiza configurației 1C ONG existente |
| [docs/04-anexa-campuri-1c.md](docs/04-anexa-campuri-1c.md) | Anexă: câmpurile obiectelor 1C preluate |
| [docs/05-specificatie-IPC21.md](docs/05-specificatie-IPC21.md) | Specificația IPC21 |
| [docs/06-specificatie-ONG17.md](docs/06-specificatie-ONG17.md) | Specificația ONG17 |
| [docs/07-specificatie-5CON.md](docs/07-specificatie-5CON.md) | Specificația 5-CON |
| [docs/08-design-interfata.md](docs/08-design-interfata.md) | Designul interfeței |
| [docs/09-schimb-banci.md](docs/09-schimb-banci.md) | Formatele băncilor, exportul ordinelor de plată, plata cumulată a impozitelor |
| [docs/10-strategie-produs.md](docs/10-strategie-produs.md) | Aplicație nouă vs extensie 1C, unde stau datele, stabilitate |
| [docs/11-reguli-contabile-ong.md](docs/11-reguli-contabile-ong.md) | Regulile contabile ONG și formulele Dt/Kt, cu surse legislative |
| [design/prototip.html](design/prototip.html) | Prototip clicabil (se deschide în browser) |
| [database/schema.dbml](database/schema.dbml) | Schema BD — se lipește în [dbdiagram.io](https://dbdiagram.io/d) |

## Stack
React + Vite · Python FastAPI · PostgreSQL · Redis · Azure Document Intelligence · Google Drive API · Docker
