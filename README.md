# apple-health-medications

A small FastAPI backend for Apple Health medication CSV exports.

It stores raw CSV snapshots, transforms them with the logic from
`ref/Apple_Health_Medications_Data_Transformations.ipynb`, and can reconcile
transformed CSV rows into a durable SQLite medication timeline.

## Stack

| Layer | Tech |
| --- | --- |
| API | FastAPI + Uvicorn |
| LLM Context | MCP Python SDK |
| Database | SQLite |
| Runtime | Docker + Docker Compose |

SQLite is embedded and file-backed, so the API uses `/data/medications.db`.
Docker Compose bind-mounts the host `./data` directory to `/data`, which makes
backup and server-to-server transfer straightforward.

## Quick Start

```bash
docker compose up --build
```

API docs are available at http://localhost:8000/docs.

OpenAPI JSON is available at http://localhost:8000/openapi.json.

## Environment

Copy the example environment file before first deploy:

```bash
cp .env.example .env
```

The default `.env` values are ready for Docker Compose:

```bash
MEDS_DATABASE_PATH=/data/medications.db
MEDS_STORAGE_DIR=/data/storage
MEDS_DEFAULT_MAPPING_PATH=/app/ref/medication_mappings.json
```

`.env` and `data/` are intentionally gitignored. The application data you need
to preserve lives under `data/`.

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Health check |
| `POST` | `/users` | Create a user |
| `GET` | `/users` | List users |
| `PUT` | `/users/{user_id}/mapping` | Store or replace that user's medication mapping JSON |
| `GET` | `/users/{user_id}/mapping` | Fetch the user's mapping, falling back to `ref/medication_mappings.json` |
| `POST` | `/users/{user_id}/csvs` | Upload a raw Apple Health CSV, store it, transform it, and store the transformed CSV |
| `GET` | `/users/{user_id}/uploads` | List uploads and discover upload ids |
| `GET` | `/users/{user_id}/uploads/{upload_id}/transformed-csv` | Download the transformed CSV for an upload |
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

List uploads and find the `id` to use as `upload_id`:

```bash
curl http://localhost:8000/users/1/uploads
```

Download the transformed CSV from that upload:

```bash
curl -L http://localhost:8000/users/1/uploads/1/transformed-csv \
  -o transformed-medications.csv
```

Import that transformed upload into SQLite:

```bash
curl -X POST http://localhost:8000/users/1/uploads/1/import
```

Query the perpetual medication timeline:

```bash
curl "http://localhost:8000/users/1/medication-events?nickname=Klonopin&limit=25"
```

## MCP Server

The repo includes a read-only MCP server in `mcp_server.py`. It connects to the
same SQLite database and exposes medication history context to LLM clients.

Available MCP capabilities:

- Resources:
  - `medications://schema`
  - `medications://users`
  - `medications://users/{user_id}/overview`
- Tools:
  - `list_users`
  - `get_user_overview`
  - `search_medication_events`
  - `get_daily_totals`
  - `list_uploads`
  - `list_import_runs`
  - `get_medication_mapping`
  - `find_mapping_gaps`
- Prompt:
  - `medication_history_review`

Run it locally over stdio:

```bash
MEDS_DATABASE_PATH=/path/to/medications.db python3 mcp_server.py
```

If you are using Docker Compose, the database lives inside the `sqlite_data`
volume at `/data/medications.db`. For desktop MCP clients, point the server at a
database file on your host, or bind-mount a host directory for `/data`.

Example client config:

```json
{
  "mcpServers": {
    "apple-health-medications": {
      "command": "python3",
      "args": ["/Users/andrew/repos/apple-health-medications/mcp_server.py"],
      "env": {
        "MEDS_DATABASE_PATH": "/Users/andrew/repos/apple-health-medications/data/medications.db"
      }
    }
  }
}
```

## Proxmox / Docker Server Deployment

For a simple Proxmox Docker host or VM:

```bash
git clone <repo-url> apple-health-medications
cd apple-health-medications
cp .env.example .env
mkdir -p data
docker compose up -d --build
```

The persistent files are:

- `data/medications.db`
- `data/storage/raw/...`
- `data/storage/transformed/...`
- `data/storage/imports/...`

To transfer persistence to a new server, stop the app and copy the project plus
`data/`:

```bash
docker compose down
rsync -av ./data/ user@new-server:/path/to/apple-health-medications/data/
```

Then start it on the new server:

```bash
docker compose up -d --build
```

If you previously used the old named Docker volume, export it once into the new
bind-mounted `data/` directory:

```bash
mkdir -p data
docker run --rm \
  -v apple-health-medications_sqlite_data:/from \
  -v "$PWD/data:/to" \
  alpine sh -c "cd /from && cp -a . /to"
```

After confirming `data/medications.db` exists, run the updated Compose file.

## Nginx Proxy Manager

No app code changes are required when exposing the API on a subdomain such as
`https://meds.example.com`.

In Nginx Proxy Manager, create a Proxy Host:

- Domain Names: your API hostname
- Scheme: `http`
- Forward Hostname / IP: the Docker host or Compose service IP
- Forward Port: `8000`
- SSL: request/attach a certificate and force SSL

Avoid exposing this publicly without protection. The API currently has no auth,
and medication history is sensitive. Put it behind a VPN, Nginx Proxy Manager
Access List / basic auth, or add API authentication before internet exposure.

If you proxy it under a path like `https://example.com/meds/` instead of a
dedicated subdomain, the app may need a FastAPI `root_path` setting. A dedicated
subdomain is the cleanest deployment.

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
