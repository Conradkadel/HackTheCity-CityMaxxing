import os
from pathlib import Path
import psycopg
from psycopg.rows import dict_row

def connect():
    return psycopg.connect(os.environ.get('DATABASE_URL', ''), row_factory=dict_row,
                           connect_timeout=5, autocommit=True)

def migrate(conn):
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(717001)')
        for path in sorted((Path(__file__).parent/'migrations').glob('*.sql')):
            conn.execute(path.read_text())

def active_version(conn):
    row=conn.execute('SELECT version_id FROM active_dataset WHERE singleton=true').fetchone()
    return row['version_id'] if row else None
