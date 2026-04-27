#!/usr/bin/env python3
"""
MCP server for querying medications database.
"""

import sqlite3
import json
from pathlib import Path
from typing import Any

class MedicationsDB:
    def __init__(self, db_path="/data/medications.db"):
        self.db_path = db_path
    
    def query(self, sql: str, params: dict = None) -> list[dict]:
        """Execute query and return results as list of dicts."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
            results = [dict(row) for row in cursor.fetchall()]
            return results
        finally:
            conn.close()
    
    def get_medication_summary(self) -> dict:
        """Get summary statistics."""
        sql = """
        SELECT 
            COUNT(DISTINCT medication) as unique_medications,
            COUNT(*) as total_entries,
            COUNT(CASE WHEN status = 'Taken' THEN 1 END) as taken_count,
            COUNT(CASE WHEN status = 'Not Logged' THEN 1 END) as not_logged_count,
            COUNT(CASE WHEN archived = 1 THEN 1 END) as archived_count
        FROM medications
        """
        results = self.query(sql)
        return results[0] if results else {}
    
    def get_medications_by_date(self, date_str: str) -> list[dict]:
        """Get all medications for a specific date."""
        sql = """
        SELECT * FROM medications 
        WHERE date LIKE :date
        ORDER BY date
        """
        return self.query(sql, {"date": f"{date_str}%"})
    
    def get_medication_by_name(self, medication_name: str) -> list[dict]:
        """Get all entries for a specific medication."""
        sql = """
        SELECT * FROM medications 
        WHERE medication = :name
        ORDER BY date DESC
        """
        return self.query(sql, {"name": medication_name})

if __name__ == '__main__':
    db = MedicationsDB('./medications.db')
    
    # Test summary
    print("Database Summary:")
    print(json.dumps(db.get_medication_summary(), indent=2))
