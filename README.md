# med-tracker

A self-hosted medication tracking backend. Accepts CSV exports from medication logging apps and stores them in a Postgres database via a FastAPI REST API.

## Stack

| Layer    | Tech                              |
|----------|-----------------------------------|
| API      | FastAPI + Uvicorn                 |
| ORM      | SQLAlchemy 2 (async)              |
| Database | PostgreSQL 16                     |
| Runtime  | Docker + Docker Compose           |

## Quick start

```bash
cp .env.example .env          # adjust credentials if desired
docker compose up --build
```

API docs available at http://localhost:8000/docs

## Importing a CSV

```bash
curl -X POST http://localhost:8000/logs/import \
  -F "file=@Medications-2026-03-26-2026-04-26.csv"
```

Returns:
```json
{ "inserted": 238, "skipped": 0, "errors": [] }
```

Re-importing the same file is safe — duplicate rows (same date + medication + dosage) are skipped automatically.

## Endpoints

| Method | Path              | Description                          |
|--------|-------------------|--------------------------------------|
| GET    | `/health`         | Health check                         |
| POST   | `/logs/import`    | Upload and ingest a CSV export       |
| GET    | `/logs`           | List logs (filterable, paginated)    |
| GET    | `/logs/{id}`      | Fetch a single log entry             |
| DELETE | `/logs/{id}`      | Delete a log entry                   |

### Query params for `GET /logs`

| Param       | Example                  | Description              |
|-------------|--------------------------|--------------------------|
| `medication`| `?medication=Vyvanse`    | Partial name match       |
| `status`    | `?status=Taken`          | Exact status match       |
| `date_from` | `?date_from=2026-03-27`  | Lower datetime bound     |
| `date_to`   | `?date_to=2026-04-01`    | Upper datetime bound     |
| `limit`     | `?limit=50`              | Max rows (default 100)   |
| `offset`    | `?offset=0`              | Pagination offset        |

## Project layout

```
med-tracker/
├── docker-compose.yml
├── .env.example
├── .gitignore
├── README.md
├── api/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── config.py          # pydantic-settings
│   ├── database.py        # async engine + session
│   ├── models.py          # SQLAlchemy ORM models
│   ├── schemas.py         # Pydantic request/response schemas
│   ├── main.py            # FastAPI app + lifespan
│   └── routers/
│       └── logs.py        # /logs endpoints
└── db/
    └── init.sql           # placeholder for raw SQL / seed data
```

## Future additions

- **Alembic** migrations (drop-in: `alembic init alembic` inside `api/`)
- **MCP server** (`mcp/`) — expose tools that query the DB for AI assistants
- **Auth** — API key or JWT middleware in `api/middleware/`
- **Analytics router** — daily summaries, streaks, dose totals
