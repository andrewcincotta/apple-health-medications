import hashlib
import json
import shutil
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from api.config import get_settings
from api.database import ensure_user, get_connection, init_db, relative_to_cwd
from api.transform import load_mapping, read_transformed_csv, transform_medication_csv, validate_mapping


app = FastAPI(title="Apple Health Medications API")


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class MappingPayload(BaseModel):
    MedsToNicknames: dict[str, str]
    NicknamesToDosage: dict[str, float]
    NicknameToCost: dict[str, float] = Field(default_factory=dict)


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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/users", status_code=201)
def create_user(payload: UserCreate) -> dict:
    with get_connection() as conn:
        try:
            cursor = conn.execute("INSERT INTO users (name) VALUES (?)", (payload.name,))
        except Exception as exc:
            raise HTTPException(status_code=409, detail="user name already exists") from exc
        return {"id": cursor.lastrowid, "name": payload.name}


@app.get("/users")
def list_users() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT id, name, created_at FROM users ORDER BY id").fetchall()
    return [dict(row) for row in rows]


@app.put("/users/{user_id}/mapping")
def upsert_mapping(user_id: int, payload: MappingPayload) -> dict:
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


@app.get("/users/{user_id}/mapping")
def get_mapping(user_id: int) -> dict:
    try:
        return _user_mapping(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/users/{user_id}/csvs", status_code=201)
def upload_and_transform_csv(
    user_id: int,
    file: Annotated[UploadFile, File(description="Apple Health medications CSV export")],
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


@app.post("/users/{user_id}/transformed-csvs/import", status_code=201)
def import_transformed_csv(
    user_id: int,
    file: Annotated[UploadFile, File(description="Transformed medications CSV")],
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


@app.post("/users/{user_id}/uploads/{upload_id}/import", status_code=201)
def import_existing_upload(user_id: int, upload_id: int) -> dict:
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


@app.get("/users/{user_id}/medication-events")
def list_medication_events(
    user_id: int,
    nickname: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
    offset: int = 0,
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
    params.extend([min(limit, 500), offset])

    with get_connection() as conn:
        try:
            ensure_user(conn, user_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        rows = conn.execute(" ".join(query), params).fetchall()
    return [dict(row) for row in rows]
