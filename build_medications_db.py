#!/usr/bin/env python3
"""
Builds a SQLite database from medications CSV.
Handles timezone-aware timestamps, nullable fields, and type conversions.
"""

import pandas as pd
import sqlite3
from pathlib import Path
from datetime import datetime

def build_medications_database(csv_file, db_file):
    """
    Read CSV and create SQLite database with proper schema.
    """
    
    # Read CSV with appropriate dtypes and null handling
    df = pd.read_csv(csv_file)
    
    # Rename columns to remove spaces for SQLite compatibility
    df.columns = df.columns.str.lower().str.replace(' ', '_')
    
    # Parse datetime columns, handling timezone info
    # Strip timezone info for SQLite compatibility (ISO 8601 string storage)
    df['date'] = pd.to_datetime(df['date'], utc=False)
    df['date'] = df['date'].dt.strftime('%Y-%m-%d %H:%M:%S')
    
    df['scheduled_date'] = pd.to_datetime(df['scheduled_date'], errors='coerce')
    df['scheduled_date'] = df['scheduled_date'].dt.strftime('%Y-%m-%d %H:%M:%S')
    
    # Convert dosage fields to float
    df['dosage'] = pd.to_numeric(df['dosage'], errors='coerce')
    df['scheduled_dosage'] = pd.to_numeric(df['scheduled_dosage'], errors='coerce')
    
    # Convert boolean-like fields
    df['archived'] = df['archived'].map({'Yes': True, 'No': False})
    
    # Replace empty strings with None for proper NULL handling
    df = df.where(pd.notnull(df), None)
    
    # Connect to SQLite
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    
    # Create table with explicit schema
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS medications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        scheduled_date TEXT,
        medication TEXT NOT NULL,
        nickname TEXT,
        dosage REAL,
        scheduled_dosage REAL,
        unit TEXT,
        status TEXT,
        archived BOOLEAN,
        codings TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Write data to database
    df.to_sql('medications', conn, if_exists='append', index=False)
    
    # Create useful indexes
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_medication ON medications(medication)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_date ON medications(date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_status ON medications(status)')
    
    conn.commit()
    
    # Verify data
    cursor.execute('SELECT COUNT(*) FROM medications')
    count = cursor.fetchone()[0]
    print(f"✓ Database created: {db_file}")
    print(f"✓ Records inserted: {count}")
    
    # Show schema
    cursor.execute("PRAGMA table_info(medications)")
    print("\nSchema:")
    for row in cursor.fetchall():
        print(f"  {row[1]}: {row[2]}")
    
    conn.close()

if __name__ == '__main__':
    csv_path = Path('Medications-2026-03-26-2026-04-26.csv')
    db_path = Path('/data/medications.db')
    
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")
    
    # Ensure output directory
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    build_medications_database(str(csv_path), str(db_path))
    print(f"\n✓ Database ready at: {db_path}")
