import csv
import io
import json
import os
from datetime import date, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP

from api.database import ensure_user, get_connection, init_db


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


def _env_path(name: str, default: str) -> str:
    value = os.getenv(name, default)
    return value if value.startswith("/") else f"/{value}"


mcp = FastMCP(
    "Apple Health Medications",
    instructions=(
        "Read-only access to transformed Apple Health medication data stored in SQLite. "
        "Use these tools to answer questions about medication events, upload provenance, "
        "import reconciliation, and medication mapping context. Do not provide medical advice."
    ),
    host=os.getenv("MCP_HOST", "127.0.0.1"),
    port=_env_int("MCP_PORT", 8002),
    streamable_http_path=_env_path("MCP_PATH", "/mcp"),
    stateless_http=True,
    json_response=True,
)


def _rows_to_dicts(rows: list[Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _ensure_user_id(user_id: int) -> None:
    with get_connection() as conn:
        ensure_user(conn, user_id)


def _bounded_limit(limit: int, maximum: int = 500) -> int:
    return max(1, min(limit, maximum))


def _bounded_offset(offset: int) -> int:
    return max(0, offset)


def _next_day(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return value
    return (parsed + timedelta(days=1)).isoformat()


def _date_filters(
    where: list[str],
    params: list[Any],
    date_from: str | None,
    date_to: str | None,
) -> None:
    if date_from:
        where.append("date_text >= ?")
        params.append(date_from)
    if date_to:
        if len(date_to) == 10:
            where.append("date_text < ?")
            params.append(_next_day(date_to))
        else:
            where.append("date_text <= ?")
            params.append(date_to)


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


@mcp.resource("medications://users/{user_id}/medications")
def user_medications_resource(user_id: int) -> str:
    """Return the medication catalog for one user."""
    return json.dumps(get_medication_catalog(user_id), indent=2)


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
    query_text: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    count_min: float | None = None,
    count_max: float | None = None,
    dosage_mg_min: float | None = None,
    dosage_mg_max: float | None = None,
    upload_id: int | None = None,
    source_filename: str | None = None,
    mapped_only: bool = False,
    unmapped_only: bool = False,
    exact_match: bool = False,
    sort: str = "date_asc",
    include_summary: bool = True,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Flexible search over reconciled medication events with fuzzy matching, ranges, and summaries."""
    _ensure_user_id(user_id)
    limit = _bounded_limit(limit)
    offset = _bounded_offset(offset)

    where = ["user_id = ?"]
    params: list[Any] = [user_id]

    if nickname:
        if exact_match:
            where.append("LOWER(nickname) = LOWER(?)")
            params.append(nickname)
        else:
            where.append("LOWER(nickname) LIKE LOWER(?)")
            params.append(f"%{nickname}%")
    if medication:
        if exact_match:
            where.append("LOWER(medication) = LOWER(?)")
            params.append(medication)
        else:
            where.append("LOWER(medication) LIKE LOWER(?)")
            params.append(f"%{medication}%")
    if query_text:
        where.append(
            """
            (
                LOWER(medication) LIKE LOWER(?)
                OR LOWER(nickname) LIKE LOWER(?)
                OR LOWER(source_filename) LIKE LOWER(?)
                OR date_text LIKE ?
            )
            """
        )
        pattern = f"%{query_text}%"
        params.extend([pattern, pattern, pattern, pattern])
    _date_filters(where, params, date_from, date_to)
    if count_min is not None:
        where.append("count >= ?")
        params.append(count_min)
    if count_max is not None:
        where.append("count <= ?")
        params.append(count_max)
    if dosage_mg_min is not None:
        where.append("dosage_mg >= ?")
        params.append(dosage_mg_min)
    if dosage_mg_max is not None:
        where.append("dosage_mg <= ?")
        params.append(dosage_mg_max)
    if upload_id is not None:
        where.append("upload_id = ?")
        params.append(upload_id)
    if source_filename:
        where.append("LOWER(source_filename) LIKE LOWER(?)")
        params.append(f"%{source_filename}%")
    if mapped_only:
        where.append("nickname IS NOT NULL AND unit_mg IS NOT NULL AND dosage_mg IS NOT NULL")
    if unmapped_only:
        where.append("(nickname IS NULL OR unit_mg IS NULL OR dosage_mg IS NULL)")

    sort_sql = {
        "date_asc": "date_text ASC, id ASC",
        "date_desc": "date_text DESC, id DESC",
        "dosage_asc": "dosage_mg ASC, date_text ASC",
        "dosage_desc": "dosage_mg DESC, date_text DESC",
        "count_asc": "count ASC, date_text ASC",
        "count_desc": "count DESC, date_text DESC",
        "medication": "medication ASC, date_text ASC",
        "nickname": "nickname ASC, date_text ASC",
    }.get(sort, "date_text ASC, id ASC")

    where_sql = " AND ".join(where)
    events_sql = f"""
        SELECT *
        FROM medication_events
        WHERE {where_sql}
        ORDER BY {sort_sql}
        LIMIT ? OFFSET ?
    """
    count_sql = f"SELECT COUNT(*) AS total_matches FROM medication_events WHERE {where_sql}"
    summary_sql = f"""
        SELECT
            COUNT(*) AS event_count,
            COUNT(DISTINCT medication) AS distinct_medications,
            COUNT(DISTINCT nickname) AS distinct_nicknames,
            MIN(date_text) AS first_event_at,
            MAX(date_text) AS last_event_at,
            ROUND(COALESCE(SUM(count), 0), 3) AS total_count,
            ROUND(COALESCE(SUM(dosage_mg), 0), 3) AS total_dosage_mg
        FROM medication_events
        WHERE {where_sql}
    """

    with get_connection() as conn:
        rows = conn.execute(events_sql, [*params, limit, offset]).fetchall()
        total_matches = conn.execute(count_sql, params).fetchone()["total_matches"]
        summary = dict(conn.execute(summary_sql, params).fetchone()) if include_summary else None

    filters = {
        "user_id": user_id,
        "nickname": nickname,
        "medication": medication,
        "query_text": query_text,
        "date_from": date_from,
        "date_to": date_to,
        "count_min": count_min,
        "count_max": count_max,
        "dosage_mg_min": dosage_mg_min,
        "dosage_mg_max": dosage_mg_max,
        "upload_id": upload_id,
        "source_filename": source_filename,
        "mapped_only": mapped_only,
        "unmapped_only": unmapped_only,
        "exact_match": exact_match,
        "sort": sort,
        "limit": limit,
        "offset": offset,
    }
    return {
        "filters": {key: value for key, value in filters.items() if value is not None},
        "total_matches": total_matches,
        "summary": summary,
        "events": _rows_to_dicts(rows),
    }


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
    limit = _bounded_limit(limit)

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
    date_where: list[str] = []
    _date_filters(date_where, params, date_from, date_to)
    if date_where:
        query.append("AND " + " AND ".join(date_where))
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
def get_medication_catalog(user_id: int, include_unmapped: bool = True) -> list[dict[str, Any]]:
    """List medications/nicknames with first/last seen dates and aggregate totals."""
    _ensure_user_id(user_id)
    where = ["user_id = ?"]
    params: list[Any] = [user_id]
    if not include_unmapped:
        where.append("nickname IS NOT NULL")

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT
                medication,
                COALESCE(nickname, '') AS nickname,
                COUNT(*) AS event_count,
                MIN(date_text) AS first_seen,
                MAX(date_text) AS last_seen,
                ROUND(COALESCE(SUM(count), 0), 3) AS total_count,
                ROUND(COALESCE(AVG(count), 0), 3) AS average_count,
                ROUND(COALESCE(MAX(count), 0), 3) AS max_count,
                ROUND(COALESCE(MAX(unit_mg), 0), 3) AS unit_mg,
                ROUND(COALESCE(SUM(dosage_mg), 0), 3) AS total_dosage_mg,
                ROUND(COALESCE(AVG(dosage_mg), 0), 3) AS average_dosage_mg
            FROM medication_events
            WHERE {" AND ".join(where)}
            GROUP BY medication, COALESCE(nickname, '')
            ORDER BY COALESCE(nickname, medication), medication
            """,
            params,
        ).fetchall()
    return _rows_to_dicts(rows)


@mcp.tool()
def summarize_date_range(
    user_id: int,
    date_from: str,
    date_to: str,
    nickname: str | None = None,
    medication: str | None = None,
    group_by: str = "nickname",
    limit: int = 100,
) -> dict[str, Any]:
    """Summarize medication events within an inclusive date range grouped by nickname, medication, or day."""
    _ensure_user_id(user_id)
    limit = _bounded_limit(limit)
    group_sql = {
        "day": "SUBSTR(date_text, 1, 10)",
        "medication": "medication",
        "nickname": "COALESCE(nickname, medication)",
    }.get(group_by, "COALESCE(nickname, medication)")

    where = ["user_id = ?"]
    params: list[Any] = [user_id]
    _date_filters(where, params, date_from, date_to)
    if nickname:
        where.append("LOWER(nickname) = LOWER(?)")
        params.append(nickname)
    if medication:
        where.append("LOWER(medication) LIKE LOWER(?)")
        params.append(f"%{medication}%")
    where_sql = " AND ".join(where)

    with get_connection() as conn:
        total = dict(
            conn.execute(
                f"""
                SELECT
                    COUNT(*) AS event_count,
                    COUNT(DISTINCT SUBSTR(date_text, 1, 10)) AS active_days,
                    COUNT(DISTINCT medication) AS distinct_medications,
                    COUNT(DISTINCT nickname) AS distinct_nicknames,
                    MIN(date_text) AS first_event_at,
                    MAX(date_text) AS last_event_at,
                    ROUND(COALESCE(SUM(count), 0), 3) AS total_count,
                    ROUND(COALESCE(SUM(dosage_mg), 0), 3) AS total_dosage_mg
                FROM medication_events
                WHERE {where_sql}
                """,
                params,
            ).fetchone()
        )
        groups = conn.execute(
            f"""
            SELECT
                {group_sql} AS name,
                COUNT(*) AS event_count,
                COUNT(DISTINCT SUBSTR(date_text, 1, 10)) AS active_days,
                ROUND(COALESCE(SUM(count), 0), 3) AS total_count,
                ROUND(COALESCE(SUM(dosage_mg), 0), 3) AS total_dosage_mg,
                MIN(date_text) AS first_event_at,
                MAX(date_text) AS last_event_at
            FROM medication_events
            WHERE {where_sql}
            GROUP BY {group_sql}
            ORDER BY event_count DESC, name
            LIMIT ?
            """,
            [*params, limit],
        ).fetchall()

    return {
        "user_id": user_id,
        "date_from": date_from,
        "date_to": date_to,
        "group_by": group_by,
        "filters": {
            key: value
            for key, value in {"nickname": nickname, "medication": medication}.items()
            if value is not None
        },
        "total": total,
        "groups": _rows_to_dicts(groups),
    }


@mcp.tool()
def compare_date_ranges(
    user_id: int,
    baseline_from: str,
    baseline_to: str,
    comparison_from: str,
    comparison_to: str,
    nickname: str | None = None,
    medication: str | None = None,
) -> dict[str, Any]:
    """Compare event counts and dosage totals between two inclusive date ranges."""
    _ensure_user_id(user_id)

    def summarize_window(date_from: str, date_to: str) -> dict[str, Any]:
        where = ["user_id = ?"]
        params: list[Any] = [user_id]
        _date_filters(where, params, date_from, date_to)
        if nickname:
            where.append("LOWER(nickname) = LOWER(?)")
            params.append(nickname)
        if medication:
            where.append("LOWER(medication) LIKE LOWER(?)")
            params.append(f"%{medication}%")
        with get_connection() as conn:
            return dict(
                conn.execute(
                    f"""
                    SELECT
                        COUNT(*) AS event_count,
                        COUNT(DISTINCT SUBSTR(date_text, 1, 10)) AS active_days,
                        ROUND(COALESCE(SUM(count), 0), 3) AS total_count,
                        ROUND(COALESCE(SUM(dosage_mg), 0), 3) AS total_dosage_mg
                    FROM medication_events
                    WHERE {" AND ".join(where)}
                    """,
                    params,
                ).fetchone()
            )

    baseline = summarize_window(baseline_from, baseline_to)
    comparison = summarize_window(comparison_from, comparison_to)
    return {
        "user_id": user_id,
        "filters": {
            key: value
            for key, value in {"nickname": nickname, "medication": medication}.items()
            if value is not None
        },
        "baseline": {"date_from": baseline_from, "date_to": baseline_to, **baseline},
        "comparison": {"date_from": comparison_from, "date_to": comparison_to, **comparison},
        "delta": {
            "event_count": comparison["event_count"] - baseline["event_count"],
            "active_days": comparison["active_days"] - baseline["active_days"],
            "total_count": round(comparison["total_count"] - baseline["total_count"], 3),
            "total_dosage_mg": round(
                comparison["total_dosage_mg"] - baseline["total_dosage_mg"], 3
            ),
        },
    }


@mcp.tool()
def get_import_quality_summary(user_id: int, limit: int = 25) -> dict[str, Any]:
    """Summarize recent imports and reconciliation counts for data quality review."""
    _ensure_user_id(user_id)
    limit = _bounded_limit(limit, maximum=100)
    with get_connection() as conn:
        totals = dict(
            conn.execute(
                """
                SELECT
                    COUNT(*) AS import_count,
                    COALESCE(SUM(inserted_count), 0) AS inserted,
                    COALESCE(SUM(updated_count), 0) AS updated,
                    COALESCE(SUM(unchanged_count), 0) AS unchanged,
                    COALESCE(SUM(error_count), 0) AS errors,
                    MIN(created_at) AS first_import_at,
                    MAX(created_at) AS latest_import_at
                FROM import_runs
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        )
        recent = conn.execute(
            """
            SELECT *
            FROM import_runs
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    return {"user_id": user_id, "totals": totals, "recent_imports": _rows_to_dicts(recent)}


@mcp.tool()
def generate_transformed_csv_snapshot(
    user_id: int,
    date_from: str,
    date_to: str,
    nickname: str | None = None,
    medication: str | None = None,
    limit: int = 5000,
) -> str:
    """Generate transformed-format CSV text from reconciled SQLite events for an inclusive date range."""
    _ensure_user_id(user_id)
    limit = _bounded_limit(limit, maximum=10000)
    where = ["user_id = ?"]
    params: list[Any] = [user_id]
    _date_filters(where, params, date_from, date_to)
    if nickname:
        where.append("LOWER(nickname) = LOWER(?)")
        params.append(nickname)
    if medication:
        where.append("LOWER(medication) LIKE LOWER(?)")
        params.append(f"%{medication}%")

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT
                date_text AS "Date",
                medication AS "Medication",
                count AS "Count",
                COALESCE(nickname, '') AS "Nickname",
                COALESCE(unit_mg, '') AS "Unit (mg)",
                COALESCE(dosage_mg, '') AS "Dosage (mg)"
            FROM medication_events
            WHERE {" AND ".join(where)}
            ORDER BY date_text ASC, id ASC
            LIMIT ?
            """,
            [*params, limit],
        ).fetchall()

    columns = ["Date", "Medication", "Count", "Nickname", "Unit (mg)", "Dosage (mg)"]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(dict(row) for row in rows)
    return output.getvalue()


@mcp.tool()
def list_uploads(user_id: int, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    """List raw/transformed CSV uploads for a user."""
    _ensure_user_id(user_id)
    limit = _bounded_limit(limit)
    offset = _bounded_offset(offset)
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
    limit = _bounded_limit(limit)
    offset = _bounded_offset(offset)
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
        "then inspect summarize_date_range, get_medication_catalog, search_medication_events, "
        "or get_daily_totals for specific questions. "
        "Use list_uploads and list_import_runs to explain data provenance. "
        "Call find_mapping_gaps before drawing conclusions about dosage totals. "
        "Do not provide medical advice; focus on data summaries and reconciliation context."
    )


def main() -> None:
    init_db()
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
