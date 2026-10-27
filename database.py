"""Small DB-API bridge; application queries use bound ? placeholders."""
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
import psycopg
from psycopg.rows import dict_row

INTEGRITY_ERRORS = (sqlite3.IntegrityError, psycopg.IntegrityError)


class Database:
    def __init__(self, config):
        self.postgres = bool(config.get('DATABASE_URL'))
        if self.postgres:
            mode=parse_qs(urlsplit(config['DATABASE_URL']).query).get('sslmode',[''])[0]
            options = {'sslmode': 'require'} if config.get('SERVERLESS') and mode not in ['verify-ca','verify-full'] else {}
            self.connection = psycopg.connect(config['DATABASE_URL'], row_factory=dict_row, connect_timeout=10, prepare_threshold=None, **options)
        else:
            self.connection = sqlite3.connect(config['DATABASE'])
            self.connection.row_factory = sqlite3.Row
            self.connection.execute('PRAGMA foreign_keys=ON')

    def execute(self, sql, args=()):
        if self.postgres:
            # Only static SQL supplied by the application reaches this bridge.
            sql = sql.replace('?', '%s').replace(' LIKE ', ' ILIKE ')
        return self.connection.execute(sql, args)

    def commit(self): self.connection.commit()
    def rollback(self): self.connection.rollback()
    def close(self): self.connection.close()

    def migrate(self, root):
        if not self.postgres:
            self.connection.executescript((root/'migrations/001_initial.sql').read_text())
            for file in sorted((root/'migrations').glob('*.sql')):
                version = int(file.name.split('_')[0])
                if not self.execute('SELECT version FROM schema_migrations WHERE version=?', (version,)).fetchone():
                    self.connection.executescript(file.read_text())
            return
        # Transaction-scoped lock avoids concurrent schema changes by operators.
        try:
            self.execute('SELECT pg_advisory_xact_lock(8472061)')
            self.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY)')
            for file in sorted((root/'migrations/postgres').glob('*.sql')):
                version = int(file.name.split('_')[0])
                if not self.execute('SELECT version FROM schema_migrations WHERE version=?', (version,)).fetchone():
                    self.connection.execute(file.read_text(), prepare=False)
                    self.execute('INSERT INTO schema_migrations VALUES(?)', (version,))
            self.commit()
        except Exception:
            self.rollback()
            raise
