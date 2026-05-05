from functools import lru_cache
import os
from pathlib import Path


class Settings:
    def __init__(self) -> None:
        self.database_path = Path(os.getenv("MEDS_DATABASE_PATH", "/data/medications.db"))
        self.storage_dir = Path(os.getenv("MEDS_STORAGE_DIR", "/data/storage"))
        self.default_mapping_path = Path(
            os.getenv("MEDS_DEFAULT_MAPPING_PATH", "ref/medication_mappings.json")
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
