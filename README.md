# ContaHub

Sistem web de contabilitate pentru ONG-uri, SRL-uri (inclusiv plătitori de TVA, comerț, alimentație publică, cazare), întreprinderi individuale și gospodării țărănești din Republica Moldova. Înlocuiește 1C:Contabilitate păstrând modul de lucru familiar din 1C 8.3, cu asistență AI. La crearea bazei se alege tipul firmei, iar aplicația pornește doar modulele potrivite. Rulează pe server prin Docker, pentru mai mulți contabili simultan.

Proiect pentru examenul **Programare Web 2** și teza de licență.

## Ce face
- citește automat facturile și ordinele de plată scanate (OCR + AI) direct de pe Google Drive;
- păstrează originalele pe Drive, sortate pe granturi și linii de buget;
- calculează corect salariile, separând **contractul individual de muncă** de **contractul civil** (scutirea personală doar la CIM);
- completează automat rapoartele Excel ale donatorilor;
- ține cotele de impozit cu perioadă de valabilitate și propune actualizări din legislație (aprobate de contabil);
- interfață de tip 1C 8.3: secțiuni, jurnale, formulare, înregistrare Dt/Kt, balanța de verificare;
- migrează toate datele existente din 1C (OData / XML) cu reconcilierea balanței.

## Pornire locală

Cerințe: Docker cu Docker Compose v2.

```bash
cp .env.example .env        # opțional: fără .env se folosesc valorile de dezvoltare și contul demo
docker compose up --build
```

Aplicația: <http://localhost:8080>. La pornire, serviciul `api` rulează migrarea Alembic și, dacă în `.env` sunt setate `DEMO_EMAIL` / `DEMO_PASSWORD`, creează utilizatorul demonstrativ (implicit `demo@contahub.local` / `demo12345`) cu o bază „AO „Exemplu Verde””.

| Serviciu | Rol |
|----------|-----|
| `nginx` | servește interfața React și trimite `/api/` către API |
| `api` | FastAPI (Python 3.12): autentificare, „Bazele mele”, documente, motorul de înregistrare |
| `worker` | sarcinile lungi din coada Redis (RQ) |
| `postgres` | PostgreSQL 16 — datele (volumul `pgdata`) |
| `redis` | coada de sarcini |

Documentația API (Swagger) e la <http://localhost:8000/docs> când API-ul rulează local (vezi mai jos).

### Dezvoltare fără Docker

```bash
cd backend
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql+psycopg://contahub:contahub@localhost:5432/contahub
alembic upgrade head
DEMO_EMAIL=demo@contahub.local DEMO_PASSWORD=demo12345 python -m app.seed
uvicorn app.main:app --reload          # http://localhost:8000/docs
```

```bash
cd frontend
npm install
npm run dev                             # http://localhost:5173, /api -> localhost:8000
```

### Teste

```bash
cd backend
export TEST_DATABASE_URL=postgresql+psycopg://contahub:contahub@localhost:5432/contahub_test
pytest
```

Testele rulează pe un PostgreSQL real (baza de test se recreează la fiecare rulare). GitHub Actions rulează testele backend și build-ul frontend la fiecare push.

## Structura codului

```
backend/
  app/<modul>/      modulele din docs/02-arhitectura.md §11 (models, router, servicii)
  app/posting/      motorul de înregistrare: entry_lines + account_turnovers într-o tranzacție
  alembic/          migrările bazei de date
  tests/            pytest
frontend/
  src/shell/        AppShell: bara de sus, secțiunile, filele
  src/pages/        login, „Bazele mele”
docker-compose.yml
```

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
| [docs/12-normalizare-performanta-bd.md](docs/12-normalizare-performanta-bd.md) | Normalizarea BD (1NF–4NF), denormalizări intenționate, viteză |
| [docs/13-tipuri-entitati-profiluri.md](docs/13-tipuri-entitati-profiluri.md) | Tipurile de firme (ONG, SRL, ÎI, GȚ), expertul „Bază nouă”, profilurile de funcționalitate |
| [design/prototip.html](design/prototip.html) | Prototip clicabil (se deschide în browser) |
| [database/schema.dbml](database/schema.dbml) | Schema BD — se lipește în [dbdiagram.io](https://dbdiagram.io/d) |

## Stack
React + Vite · Python FastAPI · PostgreSQL · Redis · Azure Document Intelligence · Google Drive API · Docker
