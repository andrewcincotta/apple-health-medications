import csv
import json
import os
import tempfile
import unittest
from pathlib import Path


class RemapMedicationEventsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.mapping_path = self.root / "mapping.json"
        self.mapping_path.write_text(
            json.dumps(
                {
                    "MedsToNicknames": {
                        "lisdexamfetamine 50 MG Oral Capsule": "Vyvanse",
                    },
                    "NicknamesToDosage": {
                        "Vyvanse": 50,
                    },
                    "NicknameToCost": {},
                }
            ),
            encoding="utf-8",
        )
        os.environ["MEDS_DATABASE_PATH"] = str(self.root / "medications.db")
        os.environ["MEDS_STORAGE_DIR"] = str(self.root / "storage")
        os.environ["MEDS_DEFAULT_MAPPING_PATH"] = str(self.mapping_path)

        from api.config import get_settings

        get_settings.cache_clear()

        from api.database import get_connection, init_db

        init_db()
        with get_connection() as conn:
            cursor = conn.execute("INSERT INTO users (name) VALUES (?)", ("Andrew",))
            self.user_id = cursor.lastrowid
            conn.execute(
                """
                INSERT INTO medication_events
                    (user_id, date_text, medication, count, nickname, unit_mg, dosage_mg, row_hash, source_filename)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.user_id,
                    "2026-05-15 08:00:00 -0400",
                    "lisdexamfetamine 50 MG Oral Capsule",
                    1,
                    None,
                    None,
                    None,
                    "old-hash",
                    "old.csv",
                ),
            )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()
        for key in ("MEDS_DATABASE_PATH", "MEDS_STORAGE_DIR", "MEDS_DEFAULT_MAPPING_PATH"):
            os.environ.pop(key, None)

        from api.config import get_settings

        get_settings.cache_clear()

    def test_transform_medication_csv_only_keeps_taken_rows(self) -> None:
        from api.transform import transform_medication_csv

        input_path = self.root / "raw.csv"
        output_path = self.root / "transformed.csv"
        mapping = {
            "MedsToNicknames": {
                "Drug A": "Drug A Nick",
                "Drug D": "Drug D Nick",
            },
            "NicknamesToDosage": {
                "Drug A Nick": 10,
                "Drug D Nick": 20,
            },
        }
        input_path.write_text(
            "\n".join(
                [
                    "Date,Scheduled Date,Medication,Nickname,Dosage,Scheduled Dosage,Unit,Status,Archived,Codings",
                    "2026-01-01,,Drug A,,1,,mg,Taken,,",
                    "2026-01-02,,Drug B,,2,,mg,Skipped,,",
                    "2026-01-03,,Drug C,,3,,mg,Not Logged,,",
                    "2026-01-04,,Drug D,,4,,mg,Taken,,",
                ]
            ),
            encoding="utf-8",
        )

        raw_count, transformed_count = transform_medication_csv(input_path, output_path, mapping)

        self.assertEqual(raw_count, 4)
        self.assertEqual(transformed_count, 2)

        with output_path.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))

        self.assertEqual(
            [row["Medication"] for row in rows],
            ["Drug A", "Drug D"],
        )
        self.assertEqual(
            [row["Dosage (mg)"] for row in rows],
            ["10.0", "80.0"],
        )

    def test_remap_medication_events_repairs_existing_rows(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI is not installed in this Python environment")

        from api.database import get_connection
        from api.main import app

        with TestClient(app) as client:
            response = client.post(f"/users/{self.user_id}/medication-events/remap")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "user_id": self.user_id,
                "scanned": 1,
                "updated": 1,
                "unchanged": 0,
                "errors": 0,
            },
        )

        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT nickname, unit_mg, dosage_mg, row_hash
                FROM medication_events
                WHERE user_id = ?
                """,
                (self.user_id,),
            ).fetchone()

        self.assertEqual(row["nickname"], "Vyvanse")
        self.assertEqual(row["unit_mg"], 50)
        self.assertEqual(row["dosage_mg"], 50)
        self.assertNotEqual(row["row_hash"], "old-hash")


if __name__ == "__main__":
    unittest.main()
