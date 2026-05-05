# apple-health-medications

A small FastAPI backend for Apple Health medication CSV exports.

It stores raw CSV snapshots, transforms them with the logic from
`ref/Apple_Health_Medications_Data_Transformations.ipynb`, and can reconcile
transformed CSV rows into a durable SQLite medication timeline.

## Stack

| Layer | Tech |
| --- | --- |
| API | FastAPI + Uvicorn |
| Database | SQLite |
| Runtime | Docker + Docker Compose |

SQLite is embedded and file-backed, so the API uses `/data/medications.db`.
Docker Compose persists that file in the `sqlite_data` volume.

## Quick Start

```bash
docker compose up --build
```

API docs are available at http://localhost:8000/docs.

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Health check |
| `POST` | `/users` | Create a user |
| `GET` | `/users` | List users |
| `PUT` | `/users/{user_id}/mapping` | Store or replace that user's medication mapping JSON |
| `GET` | `/users/{user_id}/mapping` | Fetch the user's mapping, falling back to `ref/medication_mappings.json` |
| `POST` | `/users/{user_id}/csvs` | Upload a raw Apple Health CSV, store it, transform it, and store the transformed CSV |
| `POST` | `/users/{user_id}/uploads/{upload_id}/import` | Import a previously transformed upload into SQLite |
| `POST` | `/users/{user_id}/transformed-csvs/import` | Upload and import an already transformed CSV |
| `GET` | `/users/{user_id}/medication-events` | Query reconciled medication events |

## Example Flow

Create a user:

```bash
curl -X POST http://localhost:8000/users \
  -H "Content-Type: application/json" \
  -d '{"name":"andrew"}'
```

Upload and transform a raw Apple Health medication export:

```bash
curl -X POST http://localhost:8000/users/1/csvs \
  -F "file=@ref/before/Medications-2025-04-23-2026-04-23.csv"
```

Import that transformed upload into SQLite:

```bash
curl -X POST http://localhost:8000/users/1/uploads/1/import
```

Query the perpetual medication timeline:

```bash
curl "http://localhost:8000/users/1/medication-events?nickname=Klonopin&limit=25"
```

## Reconciliation

The import step treats `(user_id, Date, Medication)` as the durable event key.
When a new snapshot overlaps existing data:

- a new event is inserted when no matching event exists
- an exact match is counted as `unchanged` and has `last_seen_at` refreshed
- a changed match updates `Count`, `Nickname`, `Unit (mg)`, and `Dosage (mg)`

This makes repeated snapshot imports idempotent while still allowing corrected
CSV rows to update the SQLite timeline.

## Medication Mappings

By default, transforms use `ref/medication_mappings.json`. You can store a
per-user mapping with `PUT /users/{user_id}/mapping`; later transforms for that
user will use the stored mapping.

The checked-in `ref/after` CSV appears to have been generated with two mappings
that are not present in the checked-in mapping JSON:

- `Vyvanse 60mg Capsule` -> `Vyvanse 60`, `60`
- `Esketamine` -> `Ketamine`, `50`

The API intentionally uses the supplied JSON as the source of truth, so those
rows remain blank until the mapping is added through the API or directly to the
JSON.
