import hashlib
import json
import shutil
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Path as ApiPath, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api.config import get_settings
from api.database import ensure_user, get_connection, init_db, relative_to_cwd
from api.transform import load_mapping, read_transformed_csv, transform_medication_csv, validate_mapping


DESCRIPTION = """
Upload Apple Health medication CSV snapshots, transform them into a stable CSV
shape, and reconcile overlapping snapshots into a durable SQLite timeline.

Typical flow:

1. Create a user.
2. Upload a raw Apple Health medication CSV.
3. Download or inspect the transformed CSV.
4. Import the transformed upload into the medication events table.
"""

TAGS_METADATA = [
    {"name": "Health", "description": "Service status checks."},
    {"name": "Users", "description": "User records used to partition medication history."},
    {"name": "Mappings", "description": "Per-user medication name and dosage mappings."},
    {"name": "CSVs", "description": "Raw CSV upload, transformation, download, and import workflows."},
    {"name": "Medication Events", "description": "Reconciled medication timeline queries."},
]

app = FastAPI(
    title="Apple Health Medications API",
    summary="Medication CSV transformation and reconciliation backend",
    description=DESCRIPTION,
    version="0.1.0",
    openapi_tags=TAGS_METADATA,
)


class UserCreate(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=120,
        examples=["andrew"],
        description="Display name for the person whose CSV snapshots are being stored.",
    )


class MappingPayload(BaseModel):
    MedsToNicknames: dict[str, str] = Field(
        examples=[{"Vyvanse 50mg Capsule": "Vyvanse", "Clonazepam": "Klonopin"}],
        description="Maps the raw Apple Health medication name to a stable nickname.",
    )
    NicknamesToDosage: dict[str, float] = Field(
        examples=[{"Vyvanse": 50, "Klonopin": 0.5}],
        description="Maps each nickname to a unit dose in milligrams.",
    )
    NicknameToCost: dict[str, float] = Field(
        default_factory=dict,
        examples=[{"Vyvanse": 12.5}],
        description="Optional cost metadata reserved for future reporting.",
    )


def _store_upload(file: UploadFile, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as f:
        shutil.copyfileobj(file.file, f)


def _safe_filename(filename: str | None) -> str:
    name = Path(filename or "upload.csv").name
    return name if name.endswith(".csv") else f"{name}.csv"


def _user_mapping(user_id: int) -> dict:
    settings = get_settings()
    with get_connection() as conn:
        ensure_user(conn, user_id)
        row = conn.execute(
            "SELECT mapping_json FROM medication_mappings WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if row:
        return json.loads(row["mapping_json"])
    return load_mapping(settings.default_mapping_path)


def _row_hash(row: dict) -> str:
    body = json.dumps(row, sort_keys=True, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _optional_float(value: str) -> float | None:
    return None if value == "" else float(value)


@app.on_event("startup")
def startup() -> None:
    init_db()
    get_settings().storage_dir.mkdir(parents=True, exist_ok=True)


@app.get(
    "/health",
    tags=["Health"],
    summary="Check API health",
    description="Returns `ok` when the API process is running.",
)
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/users",
    status_code=201,
    tags=["Users"],
    summary="Create a user",
    description="Creates a user namespace for uploads, mappings, and medication events.",
)
def create_user(payload: UserCreate) -> dict:
    with get_connection() as conn:
        try:
            cursor = conn.execute("INSERT INTO users (name) VALUES (?)", (payload.name,))
        except Exception as exc:
            raise HTTPException(status_code=409, detail="user name already exists") from exc
        return {"id": cursor.lastrowid, "name": payload.name}


@app.get(
    "/users",
    tags=["Users"],
    summary="List users",
    description="Returns all users ordered by creation id.",
)
def list_users() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT id, name, created_at FROM users ORDER BY id").fetchall()
    return [dict(row) for row in rows]


@app.put(
    "/users/{user_id}/mapping",
    tags=["Mappings"],
    summary="Store a user mapping",
    description=(
        "Creates or replaces the user's medication mapping JSON. Future raw CSV "
        "transforms for this user will use this mapping instead of the default file."
    ),
)
def upsert_mapping(
    user_id: Annotated[int, ApiPath(description="User id returned by `POST /users`.")],
    payload: MappingPayload,
) -> dict:
    mapping = payload.model_dump()
    validate_mapping(mapping)
    with get_connection() as conn:
        try:
            ensure_user(conn, user_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        conn.execute(
            """
            INSERT INTO medication_mappings (user_id, mapping_json)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                mapping_json = excluded.mapping_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, json.dumps(mapping, sort_keys=True)),
        )
    return {"user_id": user_id, "mapping_keys": list(mapping.keys())}


@app.get(
    "/users/{user_id}/mapping",
    tags=["Mappings"],
    summary="Get a user mapping",
    description=(
        "Returns the stored user mapping, or the default `config/default_medication_map.json` "
        "mapping when the user has not uploaded one."
    ),
)
def get_mapping(
    user_id: Annotated[int, ApiPath(description="User id returned by `POST /users`.")],
) -> dict:
    try:
        return _user_mapping(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post(
    "/users/{user_id}/csvs",
    status_code=201,
    tags=["CSVs"],
    summary="Upload and transform a raw CSV",
    description=(
        "Stores the raw Apple Health medication CSV, transforms it using the user's "
        "mapping, stores the transformed CSV, and returns the upload id."
    ),
)
def upload_and_transform_csv(
    user_id: Annotated[int, ApiPath(description="User id returned by `POST /users`.")],
    file: Annotated[
        UploadFile,
        File(description="Raw Apple Health medication CSV export."),
    ],
) -> dict:
    settings = get_settings()
    filename = _safe_filename(file.filename)
    token = uuid4().hex
    raw_path = settings.storage_dir / "raw" / str(user_id) / f"{token}-{filename}"
    transformed_path = settings.storage_dir / "transformed" / str(user_id) / f"{token}-{filename}"

    with get_connection() as conn:
        try:
            ensure_user(conn, user_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    _store_upload(file, raw_path)
    try:
        raw_rows, transformed_rows = transform_medication_csv(raw_path, transformed_path, _user_mapping(user_id))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO csv_uploads
                (user_id, original_filename, raw_path, transformed_path, raw_row_count, transformed_row_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                filename,
                str(raw_path),
                str(transformed_path),
                raw_rows,
                transformed_rows,
            ),
        )
        upload_id = cursor.lastrowid

    return {
        "upload_id": upload_id,
        "raw_rows": raw_rows,
        "transformed_rows": transformed_rows,
        "raw_path": relative_to_cwd(raw_path),
        "transformed_path": relative_to_cwd(transformed_path),
    }


@app.get(
    "/users/{user_id}/uploads",
    tags=["CSVs"],
    summary="List CSV uploads",
    description=(
        "Lists stored raw/transformed CSV uploads for a user. Use the returned "
        "`id` as `upload_id` for transformed CSV download or import."
    ),
)
def list_uploads(
    user_id: Annotated[int, ApiPath(description="User id returned by `POST /users`.")],
    limit: Annotated[int, Query(ge=1, le=500, description="Maximum number of uploads to return.")] = 100,
    offset: Annotated[int, Query(ge=0, description="Number of uploads to skip for pagination.")] = 0,
) -> list[dict]:
    with get_connection() as conn:
        try:
            ensure_user(conn, user_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
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
    return [dict(row) for row in rows]


@app.get(
    "/users/{user_id}/uploads/{upload_id}/transformed-csv",
    tags=["CSVs"],
    summary="Download a transformed CSV",
    description=(
        "Downloads the transformed CSV created by `POST /users/{user_id}/csvs`. "
        "Use the `upload_id` returned from the upload response."
    ),
    response_class=FileResponse,
)
def download_transformed_csv(
    user_id: Annotated[int, ApiPath(description="User id returned by `POST /users`.")],
    upload_id: Annotated[int, ApiPath(description="Upload id returned by `POST /users/{user_id}/csvs`.")],
) -> FileResponse:
    with get_connection() as conn:
        try:
            ensure_user(conn, user_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        upload = conn.execute(
            """
            SELECT transformed_path, original_filename
            FROM csv_uploads
            WHERE id = ? AND user_id = ?
            """,
            (upload_id, user_id),
        ).fetchone()

    if upload is None:
        raise HTTPException(status_code=404, detail="upload not found")

    transformed_path = Path(upload["transformed_path"])
    if not transformed_path.exists():
        raise HTTPException(status_code=404, detail="transformed CSV file not found")

    return FileResponse(
        transformed_path,
        media_type="text/csv",
        filename=f"transformed-{upload['original_filename']}",
    )


@app.post(
    "/users/{user_id}/transformed-csvs/import",
    status_code=201,
    tags=["CSVs"],
    summary="Upload and import a transformed CSV",
    description=(
        "Accepts a CSV that already has the transformed columns "
        "`Date`, `Medication`, `Count`, `Nickname`, `Unit (mg)`, and `Dosage (mg)`, "
        "then reconciles it into SQLite."
    ),
)
def import_transformed_csv(
    user_id: Annotated[int, ApiPath(description="User id returned by `POST /users`.")],
    file: Annotated[
        UploadFile,
        File(description="Transformed medications CSV."),
    ],
) -> dict:
    settings = get_settings()
    filename = _safe_filename(file.filename)
    path = settings.storage_dir / "imports" / str(user_id) / f"{uuid4().hex}-{filename}"

    with get_connection() as conn:
        try:
            ensure_user(conn, user_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    _store_upload(file, path)
    return _import_transformed_path(user_id, path, filename, upload_id=None)


@app.post(
    "/users/{user_id}/uploads/{upload_id}/import",
    status_code=201,
    tags=["CSVs"],
    summary="Import a transformed upload",
    description=(
        "Reconciles a previously transformed upload into the medication events table. "
        "Repeated imports are idempotent; overlapping changed rows update the timeline."
    ),
)
def import_existing_upload(
    user_id: Annotated[int, ApiPath(description="User id returned by `POST /users`.")],
    upload_id: Annotated[int, ApiPath(description="Upload id returned by `POST /users/{user_id}/csvs`.")],
) -> dict:
    with get_connection() as conn:
        try:
            ensure_user(conn, user_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        upload = conn.execute(
            """
            SELECT transformed_path, original_filename
            FROM csv_uploads
            WHERE id = ? AND user_id = ?
            """,
            (upload_id, user_id),
        ).fetchone()
    if upload is None:
        raise HTTPException(status_code=404, detail="upload not found")
    return _import_transformed_path(
        user_id,
        Path(upload["transformed_path"]),
        upload["original_filename"],
        upload_id=upload_id,
    )


def _import_transformed_path(
    user_id: int,
    path: Path,
    source_filename: str,
    upload_id: int | None,
) -> dict:
    try:
        rows = read_transformed_csv(path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    inserted = updated = unchanged = errors = 0
    with get_connection() as conn:
        for row in rows:
            try:
                event = {
                    "Date": row["Date"],
                    "Medication": row["Medication"],
                    "Count": float(row["Count"]),
                    "Nickname": row["Nickname"] or None,
                    "Unit (mg)": _optional_float(row["Unit (mg)"]),
                    "Dosage (mg)": _optional_float(row["Dosage (mg)"]),
                }
                row_hash = _row_hash(event)
                existing = conn.execute(
                    """
                    SELECT id, row_hash
                    FROM medication_events
                    WHERE user_id = ? AND date_text = ? AND medication = ?
                    """,
                    (user_id, event["Date"], event["Medication"]),
                ).fetchone()

                if existing is None:
                    conn.execute(
                        """
                        INSERT INTO medication_events
                            (user_id, date_text, medication, count, nickname, unit_mg, dosage_mg,
                             row_hash, source_filename, upload_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            user_id,
                            event["Date"],
                            event["Medication"],
                            event["Count"],
                            event["Nickname"],
                            event["Unit (mg)"],
                            event["Dosage (mg)"],
                            row_hash,
                            source_filename,
                            upload_id,
                        ),
                    )
                    inserted += 1
                elif existing["row_hash"] == row_hash:
                    conn.execute(
                        """
                        UPDATE medication_events
                        SET last_seen_at = CURRENT_TIMESTAMP,
                            source_filename = ?,
                            upload_id = COALESCE(?, upload_id)
                        WHERE id = ?
                        """,
                        (source_filename, upload_id, existing["id"]),
                    )
                    unchanged += 1
                else:
                    conn.execute(
                        """
                        UPDATE medication_events
                        SET count = ?,
                            nickname = ?,
                            unit_mg = ?,
                            dosage_mg = ?,
                            row_hash = ?,
                            source_filename = ?,
                            upload_id = COALESCE(?, upload_id),
                            last_seen_at = CURRENT_TIMESTAMP,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (
                            event["Count"],
                            event["Nickname"],
                            event["Unit (mg)"],
                            event["Dosage (mg)"],
                            row_hash,
                            source_filename,
                            upload_id,
                            existing["id"],
                        ),
                    )
                    updated += 1
            except Exception:
                errors += 1

        cursor = conn.execute(
            """
            INSERT INTO import_runs
                (user_id, upload_id, source_filename, inserted_count, updated_count, unchanged_count, error_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, upload_id, source_filename, inserted, updated, unchanged, errors),
        )

    return {
        "import_id": cursor.lastrowid,
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
        "errors": errors,
    }


@app.get(
    "/users/{user_id}/medication-events",
    tags=["Medication Events"],
    summary="List medication events",
    description="Returns reconciled medication events for a user, ordered by event date.",
)
def list_medication_events(
    user_id: Annotated[int, ApiPath(description="User id returned by `POST /users`.")],
    nickname: Annotated[str | None, Query(description="Exact nickname filter, for example `Klonopin`.")] = None,
    date_from: Annotated[str | None, Query(description="Inclusive lower bound for the raw Apple Health date text.")] = None,
    date_to: Annotated[str | None, Query(description="Inclusive upper bound for the raw Apple Health date text.")] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="Maximum number of events to return.")] = 100,
    offset: Annotated[int, Query(ge=0, description="Number of events to skip for pagination.")] = 0,
) -> list[dict]:
    query = ["SELECT * FROM medication_events WHERE user_id = ?"]
    params: list[object] = [user_id]
    if nickname:
        query.append("AND nickname = ?")
        params.append(nickname)
    if date_from:
        query.append("AND date_text >= ?")
        params.append(date_from)
    if date_to:
        query.append("AND date_text <= ?")
        params.append(date_to)
    query.append("ORDER BY date_text LIMIT ? OFFSET ?")
    params.extend([limit, offset])

    with get_connection() as conn:
        try:
            ensure_user(conn, user_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        rows = conn.execute(" ".join(query), params).fetchall()
    return [dict(row) for row in rows]
