# apple-health-medications

A small FastAPI backend for Apple Health medication CSV exports.

It stores raw CSV snapshots, transforms them with the logic from
`notebooks/apple_health_medication_transform_reference.ipynb`, and can reconcile
transformed CSV rows into a durable SQLite medication timeline.

## Stack

| Layer | Tech |
| --- | --- |
| API | FastAPI + Uvicorn |
| LLM Context | MCP Python SDK |
| Database | SQLite |
| Web UI | Static HTML/CSS/JS + nginx |
| Runtime | Docker + Docker Compose |

SQLite is embedded and file-backed, so the API uses `/data/medications.db`.
Docker Compose bind-mounts the host `./data` directory to `/data`, which makes
backup and server-to-server transfer straightforward.

## Quick Start

```bash
docker compose up --build
```

Web UI is available at http://localhost:8003.

API docs are available at http://localhost:8000/docs.

OpenAPI JSON is available at http://localhost:8000/openapi.json.

Download a zip backup of the configured data directory:

```bash
curl -L http://localhost:8000/data.zip -o apple-health-medications-data.zip
```

## Environment

Copy the example environment file before first deploy:

```bash
cp .env.example .env
```

The default `.env` values are ready for Docker Compose:

```bash
MEDS_DATABASE_PATH=/data/medications.db
MEDS_STORAGE_DIR=/data/storage
MEDS_DEFAULT_MAPPING_PATH=/app/config/default_medication_map.json

# Host-mapped port customizability
API_PORT=8000
SQLITE_WEB_PORT=8001
MCP_PORT=8002
WEB_PORT=8003
```

`.env` and `data/` are intentionally gitignored. The application data you need
to preserve lives under `data/`.

Tracked project configuration lives outside `ref/`:

- `config/default_medication_map.json`
- `notebooks/apple_health_medication_transform_reference.ipynb`

The `ref/` directory is intentionally ignored and can be used for local sample
exports or scratch comparison files.

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Health check |
| `GET` | `/data.zip` | Download the configured application data directory as a zip archive |
| `POST` | `/users` | Create a user, optionally providing a `password` |
| `GET` | `/users` | List users, including `has_password` status |
| `POST` | `/users/{user_id}/verify-password` | Verify a user's password |
| `PUT` | `/users/{user_id}/password` | Set or update a user's password |
| `POST` | `/users/{user_id}/medications/sync` | Pull unique medications from history into managed table |
| `GET` | `/users/{user_id}/medications/managed` | List medications from the managed table |
| `PATCH` | `/users/{user_id}/medications/{medication_id}` | Update metadata for a managed medication |
| `PUT` | `/users/{user_id}/mapping` | Store or replace that user's medication mapping JSON |
| `GET` | `/users/{user_id}/mapping` | Fetch the user's mapping, falling back to `config/default_medication_map.json` |
| `POST` | `/users/{user_id}/medication-events/remap` | Reapply the active mapping to existing SQLite medication events |
| `POST` | `/medication-events/remap` | Reapply active mappings to existing SQLite medication events for all users |
| `GET` | `/users/{user_id}/medications` | List distinct reconciled medications for UI selectors |
| `POST` | `/users/{user_id}/csvs` | Upload a raw Apple Health CSV, store it, transform it, and store the transformed CSV |
| `GET` | `/users/{user_id}/uploads` | List uploads and discover upload ids |
| `GET` | `/users/{user_id}/uploads/{upload_id}/transformed-csv` | Download the transformed CSV for an upload |
| `POST` | `/users/{user_id}/uploads/{upload_id}/import` | Import a previously transformed upload into SQLite |
| `POST` | `/users/{user_id}/transformed-csvs/import` | Upload and import an already transformed CSV |
| `GET` | `/users/{user_id}/medication-events` | Query reconciled medication events |
| `GET` | `/users/{user_id}/medication-events.csv` | Download a transformed-format CSV snapshot from the SQLite timeline |

## Example Flow

Create a user with a password:

```bash
curl -X POST http://localhost:8000/users \
  -H "Content-Type: application/json" \
  -d '{"name":"andrew", "password":"mysecretpassword"}'
```

Verify a password:

```bash
curl -X POST http://localhost:8000/users/1/verify-password \
  -H "Content-Type: application/json" \
  -d '{"password":"mysecretpassword"}'
```

Set or update a password for an existing user:

```bash
curl -X PUT http://localhost:8000/users/1/password \
  -H "Content-Type: application/json" \
  -d '{"password":"newsecurepassword"}'
```

Upload and transform a raw Apple Health medication export:

```bash
curl -X POST http://localhost:8000/users/1/csvs \
  -F "file=@/path/to/Medications-2026-04-19-2026-05-02.csv"
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

Download a transformed-format CSV snapshot from the SQLite timeline:

```bash
curl -L "http://localhost:8000/users/1/medication-events.csv?start_date=2026-04-19&end_date=2026-05-02" \
  -o medications-2026-04-19-to-2026-05-02.csv
```

## Web UI

The `web/` directory contains a small dependency-free frontend served by its own
nginx container. Docker Compose publishes it on:

```text
http://localhost:8003
```

The UI is intentionally read-only. It lists users, lets you select a reconciled
medication, and renders an Apple Health-style medication detail view:

- a 28-day highlights grid where logged days are blue and missing days are gray
- month markers when the range crosses a month boundary
- a details card with the selected medication name, form, and latest known dose

The web container proxies browser requests from `/api/...` to the FastAPI
service at `api:8000`, so the browser talks to one origin and no CORS setup is
needed.

If the UI says no medication events were found, complete the import flow first:
upload/transform a CSV, then import the transformed upload into SQLite.

## MCP Server

The repo includes a read-only MCP server in `mcp_server.py`. It connects to the
same SQLite database and exposes medication history context to LLM clients.

Available MCP capabilities:

- Resources:
  - `medications://schema`
  - `medications://users`
  - `medications://users/{user_id}/overview`
  - `medications://users/{user_id}/medications`
- Tools:
  - `list_users`
  - `get_user_overview`
  - `get_medication_catalog`
  - `search_medication_events`
  - `summarize_date_range`
  - `compare_date_ranges`
  - `get_daily_totals`
  - `generate_transformed_csv_snapshot`
  - `list_uploads`
  - `list_import_runs`
  - `get_import_quality_summary`
  - `get_medication_mapping`
  - `find_mapping_gaps`
- Prompt:
  - `medication_history_review`

`search_medication_events` is the broad lookup tool. It supports fuzzy
`query_text`, partial or exact `nickname` / `medication` matching, date bounds,
count and dosage ranges, upload/source filters, mapped/unmapped filters, sort
options, pagination, and an optional summary block.

Run it locally over stdio:

```bash
MEDS_DATABASE_PATH=/path/to/medications.db python3 mcp_server.py
```

Run it as a Streamable HTTP server:

```bash
MCP_TRANSPORT=streamable-http \
MCP_HOST=127.0.0.1 \
MCP_PORT=8002 \
MCP_PATH=/mcp \
MEDS_DATABASE_PATH=/path/to/medications.db \
python3 mcp_server.py
```

If you are using Docker Compose, the database is bind-mounted from the host at
`data/medications.db`. For desktop MCP clients, point the server at that host
database file.

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

The Docker Compose file also runs a dedicated MCP HTTP service on the Docker
host's loopback interface:

```text
127.0.0.1:8002 -> mcp:8002/mcp
```

That means it is not exposed directly on your LAN. To use it remotely from your
Mac, tunnel it over SSH:

```bash
ssh -N -L 8002:127.0.0.1:8002 user@192.168.0.7
```

Then configure Raycast with an HTTP MCP server URL:

```text
http://127.0.0.1:8002/mcp
```

You can expose MCP directly on the LAN instead of tunneling. Change the MCP
port mapping in `docker-compose.yml` from:

```yaml
- "127.0.0.1:8002:8002"
```

to:

```yaml
- "8002:8002"
```

Then rebuild/restart and use this Raycast URL:

```text
http://192.168.0.7:8002/mcp
```

The tradeoff is security. The MCP server is read-only, but it still exposes
medication history and currently has no authentication layer. SSH tunneling
keeps the service private to the VM and only reachable by someone who can SSH
into it. Direct LAN exposure is fine for a trusted home network if you accept
that risk; avoid forwarding `8002` through your router or exposing it publicly.

## Mac LAN Access: DataGrip and Raycast

When this runs on a Proxmox VM or Docker host at `192.168.0.7`, the API should
be reachable from your Mac at:

- API docs: `http://192.168.0.7:8000/docs`
- OpenAPI JSON: `http://192.168.0.7:8000/openapi.json`
- Portainer: `http://192.168.0.7:9000`

SQLite is not a TCP database server, so DataGrip cannot connect to
`192.168.0.7:8000` as a SQLite database. Port `8000` is the FastAPI app. For
DataGrip, mount or copy the database file from the VM and open that file:

```text
/path/to/apple-health-medications/data/medications.db
```

The safest live setup is to mount the VM project directory read-only on your Mac
and point DataGrip at the mounted `medications.db` file. For example, with
SSHFS:

```bash
brew install macfuse gromgit/fuse/sshfs-mac
mkdir -p ~/Mounts/apple-health-medications
sshfs -o ro user@192.168.0.7:/path/to/apple-health-medications \
  ~/Mounts/apple-health-medications
```

Then create a DataGrip SQLite data source using:

```text
~/Mounts/apple-health-medications/data/medications.db
```

Use read-only mode in DataGrip if you are inspecting production medication data.
SQLite allows multiple readers, but accidental writes from a desktop client are
not worth the risk while the API container is also using the file.

Raycast should use the remote MCP service through the SSH tunnel described
above. Keep the tunnel running, then add an HTTP MCP server in Raycast with:

```text
http://127.0.0.1:8002/mcp
```

If you would rather avoid a live DataGrip mount, copy `data/medications.db` to
the Mac and point DataGrip at the local copy. That is simpler and safer, but it
will only be current as of the last copy.

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

By default, transforms use `config/default_medication_map.json`. You can store a
per-user mapping with `PUT /users/{user_id}/mapping`; later transforms for that
user will use the stored mapping.

If existing SQLite rows were imported with an old or incomplete mapping, reapply
the active mapping in place:

```sh
curl -X POST http://localhost:8000/users/1/medication-events/remap
```

To repair every user in the database:

```sh
curl -X POST http://localhost:8000/medication-events/remap
```

The repair uses the user's stored mapping when present, otherwise the default
mapping. It recalculates `Nickname`, `Unit (mg)`, `Dosage (mg)`, and the row
hash for every stored event for that user.

The local sample `ref/after` CSV may have been generated with mappings that are
not present in the tracked default mapping JSON:

- `Vyvanse 60mg Capsule` -> `Vyvanse 60`, `60`
- `Esketamine` -> `Ketamine`, `50`

The API intentionally uses the supplied JSON as the source of truth, so those
rows remain blank until the mapping is added through the API or directly to the
JSON.
