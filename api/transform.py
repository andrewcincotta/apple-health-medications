import json
import csv
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

TRANSFORMED_COLUMNS = [
    "Date",
    "Medication",
    "Count",
    "Nickname",
    "Unit (mg)",
    "Dosage (mg)",
]


def load_mapping(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_mapping(mapping: dict[str, Any]) -> None:
    for key in ("MedsToNicknames", "NicknamesToDosage"):
        if key not in mapping or not isinstance(mapping[key], dict):
            raise ValueError(f"mapping must contain a {key} object")


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

    meds_to_nicknames = mapping.get("MedsToNicknames", {})
    nicknames_to_dosage = mapping.get("NicknamesToDosage", {})

    rows = raw_rows
    # Preserve the notebook behavior used by the reference before/after CSVs.
    if rows and rows[0]["Scheduled Date"] != "Taken":
        rows = rows[1:]

    transformed_rows = []
    for row in rows:
        count = float(row["Dosage"])
        nickname = meds_to_nicknames.get(row["Medication"])
        unit_mg_value = nicknames_to_dosage.get(nickname) if nickname is not None else None
        unit_mg = float(unit_mg_value) if unit_mg_value is not None else None
        dosage_mg = round(count * float(unit_mg), 3) if unit_mg is not None else ""
        transformed_rows.append(
            {
                "Date": row["Date"],
                "Medication": row["Medication"],
                "Count": count,
                "Nickname": nickname or "",
                "Unit (mg)": unit_mg if unit_mg is not None else "",
                "Dosage (mg)": dosage_mg,
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TRANSFORMED_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(transformed_rows)
    return raw_row_count, len(transformed_rows)


def read_transformed_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = [column for column in TRANSFORMED_COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"transformed CSV is missing required columns: {', '.join(missing)}")
        return [{column: row[column] for column in TRANSFORMED_COLUMNS} for row in reader]
