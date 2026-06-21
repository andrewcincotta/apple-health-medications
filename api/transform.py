import json
import csv
from datetime import datetime
from pathlib import Path
from typing import Any


RAW_COLUMNS = [
    "Date",
    "Scheduled Date",
    "Medication",
    "Nickname",
    "Dosage",
    "Scheduled Dosage",
    "Unit",
    "Status",
    "Archived",
    "Codings",
]

MEDISAFE_RAW_COLUMNS = [
    "Type",
    "Name",
    "Recorded on",
    "Scheduled for",
    "Value",
    "Notes",
]

TRANSFORMED_COLUMNS = [
    "Date",
    "Medication",
    "Count",
    "Nickname",
    "Unit (mg)",
    "Dosage (mg)",
]

MEDISAFE_DATE_FORMATS = [
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%Y %I:%M:%S %p",
]


def load_mapping(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_mapping(mapping: dict[str, Any]) -> None:
    for key in ("MedsToNicknames", "NicknamesToDosage"):
        if key not in mapping or not isinstance(mapping[key], dict):
            raise ValueError(f"mapping must contain a {key} object")


def _mapped_dosage_fields(
    medication: str,
    count: float,
    mapping: dict[str, Any],
) -> tuple[str, float | None, float | str]:
    meds_to_nicknames = mapping.get("MedsToNicknames", {})
    nicknames_to_dosage = mapping.get("NicknamesToDosage", {})

    nickname = meds_to_nicknames.get(medication)
    if nickname is None and medication in nicknames_to_dosage:
        nickname = medication

    unit_mg_value = nicknames_to_dosage.get(nickname) if nickname is not None else None
    unit_mg = float(unit_mg_value) if unit_mg_value is not None else None
    dosage_mg = round(count * unit_mg, 3) if unit_mg is not None else ""
    return nickname or "", unit_mg, dosage_mg


def _write_transformed_csv(output_path: Path, rows: list[dict[str, Any]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TRANSFORMED_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _parse_medisafe_date(value: str) -> str:
    normalized = value.strip().replace("\u202f", " ").replace("\xa0", " ")
    for date_format in MEDISAFE_DATE_FORMATS:
        try:
            return datetime.strptime(normalized, date_format).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    raise ValueError(f"could not parse Medisafe date '{value}'")


def transform_medication_csv(
    input_path: Path,
    output_path: Path,
    mapping: dict[str, Any],
) -> tuple[int, int]:
    validate_mapping(mapping)
    with input_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = [column for column in RAW_COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"raw CSV is missing required columns: {', '.join(missing)}")
        raw_rows = list(reader)

    raw_row_count = len(raw_rows)
    if raw_row_count == 0:
        raise ValueError("raw CSV has headers but no medication rows")

    rows = [
        row
        for row in raw_rows
        if row.get("Status", "").strip().casefold() == "taken"
    ]

    rows = [row for row in rows if row["Dosage"].strip() != ""]
    if not rows:
        raise ValueError(
            "raw CSV has no medication rows with status Taken and a dosage value"
        )

    transformed_rows = []
    for row in rows:
        try:
            count = float(row["Dosage"].strip())
        except ValueError as exc:
            raise ValueError(
                f"could not parse Dosage '{row['Dosage']}' for "
                f"{row['Medication']} on {row['Date']}"
            ) from exc
        nickname, unit_mg, dosage_mg = _mapped_dosage_fields(row["Medication"], count, mapping)
        transformed_rows.append(
            {
                "Date": row["Date"],
                "Medication": row["Medication"],
                "Count": count,
                "Nickname": nickname,
                "Unit (mg)": unit_mg if unit_mg is not None else "",
                "Dosage (mg)": dosage_mg,
            }
        )

    _write_transformed_csv(output_path, transformed_rows)
    return raw_row_count, len(transformed_rows)


def transform_medisafe_csv(
    input_path: Path,
    output_path: Path,
    mapping: dict[str, Any],
) -> tuple[int, int]:
    validate_mapping(mapping)
    with input_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [
            column for column in MEDISAFE_RAW_COLUMNS if column not in (reader.fieldnames or [])
        ]
        if missing:
            raise ValueError(f"Medisafe CSV is missing required columns: {', '.join(missing)}")
        raw_rows = list(reader)

    raw_row_count = len(raw_rows)
    if raw_row_count == 0:
        raise ValueError("Medisafe CSV has headers but no medication rows")

    rows = [
        row
        for row in raw_rows
        if row.get("Type", "").strip().casefold() == "medication"
        and row.get("Value", "").strip().casefold() == "taken"
        and row.get("Name", "").strip() != ""
        and row.get("Recorded on", "").strip() != ""
    ]
    if not rows:
        raise ValueError("Medisafe CSV has no medication rows with value Taken")

    event_counts: dict[tuple[str, str], float] = {}
    for row in rows:
        medication = row["Name"].strip()
        date_text = _parse_medisafe_date(row["Recorded on"])
        key = (date_text, medication)
        event_counts[key] = event_counts.get(key, 0.0) + 1.0

    transformed_rows = []
    for (date_text, medication), count in event_counts.items():
        nickname, unit_mg, dosage_mg = _mapped_dosage_fields(medication, count, mapping)
        transformed_rows.append(
            {
                "Date": date_text,
                "Medication": medication,
                "Count": count,
                "Nickname": nickname,
                "Unit (mg)": unit_mg if unit_mg is not None else "",
                "Dosage (mg)": dosage_mg,
            }
        )

    transformed_rows.sort(key=lambda row: row["Date"])
    _write_transformed_csv(output_path, transformed_rows)
    return raw_row_count, len(transformed_rows)


def read_transformed_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = [column for column in TRANSFORMED_COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"transformed CSV is missing required columns: {', '.join(missing)}")
        rows = [{column: row[column] for column in TRANSFORMED_COLUMNS} for row in reader]
    if not rows:
        raise ValueError("transformed CSV has headers but no medication rows")
    return rows
