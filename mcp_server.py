import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from api.database import ensure_user, get_connection, init_db


mcp = FastMCP(
    "Apple Health Medications",
    instructions=(
        "Read-only access to transformed Apple Health medication data stored in SQLite. "
        "Use these tools to answer questions about medication events, upload provenance, "
        "import reconciliation, and medication mapping context. Do not provide medical advice."
    ),
)


def _rows_to_dicts(rows: list[Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _ensure_user_id(user_id: int) -> None:
    with get_connection() as conn:
        ensure_user(conn, user_id)


@mcp.resource("medications://schema")
def database_schema() -> str:
    """Describe the SQLite tables exposed by this MCP server."""
    schema = {
        "users": ["id", "name", "created_at"],
        "medication_mappings": ["user_id", "mapping_json", "created_at", "updated_at"],
        "csv_uploads": [
            "id",
            "user_id",
            "original_filename",
            "raw_path",
            "transformed_path",
            "raw_row_count",
            "transformed_row_count",
            "uploaded_at",
        ],
        "import_runs": [
            "id",
            "user_id",
            "upload_id",
            "source_filename",
            "inserted_count",
            "updated_count",
            "unchanged_count",
            "error_count",
            "created_at",
        ],
        "medication_events": [
            "id",
            "user_id",
            "date_text",
            "medication",
            "count",
            "nickname",
            "unit_mg",
            "dosage_mg",
            "source_filename",
            "upload_id",
            "first_seen_at",
            "last_seen_at",
            "updated_at",
        ],
    }
    return json.dumps(schema, indent=2)


@mcp.resource("medications://users")
def users_resource() -> str:
    """List users available in the medication database."""
    return json.dumps(list_users(), indent=2)


@mcp.resource("medications://users/{user_id}/overview")
def user_overview_resource(user_id: int) -> str:
    """Return a compact overview for one user's medication history."""
    return json.dumps(get_user_overview(user_id), indent=2)


@mcp.tool()
def list_users() -> list[dict[str, Any]]:
    """List users with medication data namespaces."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, created_at FROM users ORDER BY id"
        ).fetchall()
    return _rows_to_dicts(rows)


@mcp.tool()
def get_user_overview(user_id: int) -> dict[str, Any]:
    """Summarize a user's medication timeline, uploads, imports, and top nicknames."""
    _ensure_user_id(user_id)
    with get_connection() as conn:
        event_summary = conn.execute(
            """
            SELECT
                COUNT(*) AS event_count,
                MIN(date_text) AS first_event_at,
                MAX(date_text) AS last_event_at,
                COUNT(DISTINCT medication) AS distinct_medications,
                COUNT(DISTINCT nickname) AS distinct_nicknames
            FROM medication_events
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
        upload_summary = conn.execute(
            """
            SELECT
                COUNT(*) AS upload_count,
                MAX(uploaded_at) AS latest_upload_at
            FROM csv_uploads
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
        import_summary = conn.execute(
            """
            SELECT
                COUNT(*) AS import_count,
                COALESCE(SUM(inserted_count), 0) AS total_inserted,
                COALESCE(SUM(updated_count), 0) AS total_updated,
                COALESCE(SUM(unchanged_count), 0) AS total_unchanged,
                COALESCE(SUM(error_count), 0) AS total_errors,
                MAX(created_at) AS latest_import_at
            FROM import_runs
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
        top_nicknames = conn.execute(
            """
            SELECT
                COALESCE(nickname, medication) AS name,
                COUNT(*) AS event_count,
                ROUND(COALESCE(SUM(dosage_mg), 0), 3) AS total_dosage_mg
            FROM medication_events
            WHERE user_id = ?
            GROUP BY COALESCE(nickname, medication)
            ORDER BY event_count DESC, name
            LIMIT 10
            """,
            (user_id,),
        ).fetchall()

    return {
        "user_id": user_id,
        "events": dict(event_summary),
        "uploads": dict(upload_summary),
        "imports": dict(import_summary),
        "top_nicknames": _rows_to_dicts(top_nicknames),
    }


@mcp.tool()
def search_medication_events(
    user_id: int,
    nickname: str | None = None,
    medication: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Search reconciled medication events by user, medication/nickname, and date text bounds."""
    _ensure_user_id(user_id)
    limit = max(1, min(limit, 500))
    offset = max(0, offset)

    query = ["SELECT * FROM medication_events WHERE user_id = ?"]
    params: list[Any] = [user_id]
    if nickname:
        query.append("AND nickname = ?")
        params.append(nickname)
    if medication:
        query.append("AND medication LIKE ?")
        params.append(f"%{medication}%")
    if date_from:
        query.append("AND date_text >= ?")
        params.append(date_from)
    if date_to:
        query.append("AND date_text <= ?")
        params.append(date_to)
    query.append("ORDER BY date_text LIMIT ? OFFSET ?")
    params.extend([limit, offset])

    with get_connection() as conn:
        rows = conn.execute(" ".join(query), params).fetchall()
    return _rows_to_dicts(rows)


@mcp.tool()
def get_daily_totals(
    user_id: int,
    nickname: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 120,
) -> list[dict[str, Any]]:
    """Aggregate medication event counts and dosage totals by calendar day and nickname."""
    _ensure_user_id(user_id)
    limit = max(1, min(limit, 500))

    query = [
        """
        SELECT
            SUBSTR(date_text, 1, 10) AS day,
            COALESCE(nickname, medication) AS name,
            COUNT(*) AS event_count,
            ROUND(COALESCE(SUM(count), 0), 3) AS total_count,
            ROUND(COALESCE(SUM(dosage_mg), 0), 3) AS total_dosage_mg
        FROM medication_events
        WHERE user_id = ?
        """
    ]
    params: list[Any] = [user_id]
    if nickname:
        query.append("AND nickname = ?")
        params.append(nickname)
    if date_from:
        query.append("AND date_text >= ?")
        params.append(date_from)
    if date_to:
        query.append("AND date_text <= ?")
        params.append(date_to)
    query.append(
        """
        GROUP BY SUBSTR(date_text, 1, 10), COALESCE(nickname, medication)
        ORDER BY day DESC, name
        LIMIT ?
        """
    )
    params.append(limit)

    with get_connection() as conn:
        rows = conn.execute(" ".join(query), params).fetchall()
    return _rows_to_dicts(rows)


@mcp.tool()
def list_uploads(user_id: int, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    """List raw/transformed CSV uploads for a user."""
    _ensure_user_id(user_id)
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                original_filename,
                raw_row_count,
                transformed_row_count,
                uploaded_at,
                raw_path,
                transformed_path
            FROM csv_uploads
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, limit, offset),
        ).fetchall()
    return _rows_to_dicts(rows)


@mcp.tool()
def list_import_runs(user_id: int, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    """List CSV import/reconciliation runs for a user."""
    _ensure_user_id(user_id)
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM import_runs
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, limit, offset),
        ).fetchall()
    return _rows_to_dicts(rows)


@mcp.tool()
def get_medication_mapping(user_id: int) -> dict[str, Any]:
    """Return the stored medication mapping for a user, if one exists."""
    _ensure_user_id(user_id)
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT mapping_json, created_at, updated_at
            FROM medication_mappings
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
    if row is None:
        return {
            "user_id": user_id,
            "mapping": None,
            "note": "No user-specific mapping is stored; the API falls back to the default mapping file.",
        }
    return {
        "user_id": user_id,
        "mapping": json.loads(row["mapping_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@mcp.tool()
def find_mapping_gaps(user_id: int) -> list[dict[str, Any]]:
    """Find medication events that have no mapped nickname or dosage."""
    _ensure_user_id(user_id)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                medication,
                COUNT(*) AS event_count,
                MIN(date_text) AS first_seen,
                MAX(date_text) AS last_seen
            FROM medication_events
            WHERE user_id = ?
              AND (nickname IS NULL OR unit_mg IS NULL OR dosage_mg IS NULL)
            GROUP BY medication
            ORDER BY event_count DESC, medication
            """,
            (user_id,),
        ).fetchall()
    return _rows_to_dicts(rows)


@mcp.prompt()
def medication_history_review(user_id: int) -> str:
    """Prompt for an LLM to review available medication history context."""
    return (
        f"Review medication history for user {user_id}. Start with get_user_overview, "
        "then inspect search_medication_events or get_daily_totals for specific questions. "
        "Use list_uploads and list_import_runs to explain data provenance. "
        "Call find_mapping_gaps before drawing conclusions about dosage totals. "
        "Do not provide medical advice; focus on data summaries and reconciliation context."
    )


def main() -> None:
    init_db()
    mcp.run()


if __name__ == "__main__":
    main()
