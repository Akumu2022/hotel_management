# Hotel Food Ordering

Spec: *Hotel Food Ordering App — Developer Specification* (Oct 1, 2026), with overrides in
[docs/DECISIONS.md](docs/DECISIONS.md). UI direction: [docs/UI.md](docs/UI.md).

```
backend/     FastAPI app, Alembic migrations, tests
web/         React + Vite app (customer, hotel, rider, admin)
forwarder/   "Chakula Till" Android app for each hotel's Till phone (M8)
docs/        spec addendum, UI direction
```

## Local development (Windows, no Docker)

Requirements: Python 3.13, and PostgreSQL 16 portable binaries unzipped so that
`%LOCALAPPDATA%\pgsql16\bin\pg_ctl.exe` exists (from the EDB "binaries" zip; only the `bin`,
`lib` and `share` folders are needed). Set `$env:PGBIN` to use another location.

```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\scripts\dev-db.ps1 start                         # first run creates hotel + hotel_test DBs
.\.venv\Scripts\alembic upgrade head
.\.venv\Scripts\python -m app.cli create-superadmin --name "Admin" --phone 0712345678
.\.venv\Scripts\uvicorn app.main:app --reload --no-access-log       # http://localhost:8000/docs
```

Stop the database with `.\scripts\dev-db.ps1 stop`.

## Web app

```powershell
cd web
npm install
npm run dev        # http://localhost:5173 (proxies /api and /media to the backend on :8000)
npm run build      # type-check + production build
```

Areas: `/` customer, `/hotel` (orders, payments, menu, deals, Chakula bill, settings), `/rider`, `/admin`.

## Till phone app (forwarder/)

Sends each hotel's M-Pesa Till messages to the server so payments confirm by themselves
(DECISIONS D26). Needs Android Studio's SDK and bundled Java:

```powershell
cd forwarder
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio1\jbr"   # your Android Studio's jbr
.\gradlew assembleDebug
copy app\build\outputs\apk\debug\app-debug.apk ..\web\public\downloads\chakula-till.apk
```

Hotels download it from `/downloads/chakula-till.apk`, then pair it under Settings → Till phone.
For a phone on the same Wi-Fi as a development laptop, run the API with `--host 0.0.0.0` and
`npm run dev -- --host`, and enter `http://<laptop Wi-Fi IP>:5173` as the server address
(the emulator uses `http://10.0.2.2:8000`). Debug builds allow plain http; release builds need https.
Set `FORWARDER_KEY` (see `.env.example`) to a long random value in production.

## Tests and lint

```powershell
cd backend
.\.venv\Scripts\pytest -q        # migrates hotel_test from scratch; real PostgreSQL
.\.venv\Scripts\ruff check .
```

Each test runs in a rolled-back transaction; the concurrency tests use real commits.
CI (`.github/workflows/backend.yml`) runs the same on PostgreSQL 16, plus a migration
up/down/up and drift check.

## Settings

Business values (commission, fees, timeouts, caps) are admin-entered:
`GET/PUT /api/v1/admin/settings`. They are seeded with the spec's proposed defaults and
reported as `unconfirmed` until an admin saves them once. Commission and service fee can be
overridden per hotel.

## Deployment

`docker-compose.yml` runs the database, API and web app (it is what development uses too).
Before real customers use a server, run the launch check and fix every `[FAIL]`:

```powershell
docker compose exec api python -m app.cli check-production
```

It verifies `APP_ENV=production`, strong `JWT_SECRET` and `FORWARDER_KEY`, an HTTPS-only login
cookie, a non-default database password, real `CORS_ORIGINS`, and that the payment simulator
(which can mark an order paid with no money) is off. `[WARN]` lines are the three optional
extras below. The demo seed (`python -m app.cli seed-demo`) refuses to run in production.
Settings live in `.env` (see `.env.example`).

### Web Push (alarms when the browser is closed)

```powershell
docker compose exec api python -m app.cli vapid-keys   # put the three lines in .env
```

Needs HTTPS. Staff and riders then see "Alerts when Chakula is closed" under the bell and turn
it on per device. Hotels are woken for new orders and payments to confirm, riders for open or
assigned jobs, the super admin for decisions. Signing out turns it off on that device.

### Shared rate limits (more than one API process)

```powershell
docker compose --profile scale up -d redis     # then REDIS_URL=redis://redis:6379/0 in .env
```

Without `REDIS_URL` limits are counted in memory, which is correct for one process. If Redis
can't be reached the API counts in memory instead of refusing requests.

### Road routing (distance, the customer's live map)

Distances and the dotted route use OSRM. The free public server is for the pilot only: it can
take 10 s or more and has no guarantees. To run your own for Kenya:

```powershell
mkdir osrm-data; cd osrm-data
curl -L -o kenya-latest.osm.pbf https://download.geofabrik.de/africa/kenya-latest.osm.pbf
docker run --rm -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend osrm-extract -p /opt/car.lua /data/kenya-latest.osm.pbf
docker run --rm -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend osrm-partition /data/kenya-latest.osrm
docker run --rm -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend osrm-customize /data/kenya-latest.osrm
cd ..; docker compose --profile routing up -d osrm
```

Then set `OSRM_URL=http://osrm:5000/route/v1/driving` in `.env` and restart the API. If routing
is down, ordering and the map keep working with straight-line distances.
