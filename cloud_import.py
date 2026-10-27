"""Explicit, operator-run transfer. Never invoked during a web request/build."""
import mimetypes
import re
import sqlite3
from pathlib import Path

TABLES = ('users', 'courses', 'enrollments', 'materials', 'leads', 'settings', 'audit', 'course_photos', 'announcements')
IDENTITY_TABLES = ('users', 'courses', 'materials', 'leads', 'audit', 'course_photos', 'announcements')


def import_local(database, storage, source, uploads):
    if not database.postgres or not storage.remote:
        raise ValueError('Configure PostgreSQL e S3 como destino antes da importação.')
    source = Path(source).resolve()
    uploads = Path(uploads).resolve()
    if not source.is_file(): raise ValueError('O banco de origem não existe.')
    connection = sqlite3.connect(source.as_uri()+'?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        data = {table: [dict(row) for row in connection.execute(f'SELECT * FROM {table}')] for table in TABLES}
    finally: connection.close()
    names = {row['filename'] for table in ('course_photos', 'announcements') for row in data[table]}
    names.update(row['content'] for row in data['materials'] if row['kind'] == 'file')
    for name in names:
        storage.key(name)
        if not (uploads/name).is_file(): raise ValueError('Faltam arquivos de uploads referenciados no banco de origem.')
    try:
        database.execute('SELECT pg_advisory_xact_lock(8472061)')
        database.execute('LOCK TABLE '+', '.join(TABLES)+' IN ACCESS EXCLUSIVE MODE')
        if any(database.execute(f'SELECT COUNT(*) n FROM {table}').fetchone()['n'] for table in TABLES):
            raise ValueError('O banco de destino deve estar vazio. Nenhum registro foi sobrescrito.')
        # Upload before committing references. On failure the DB rolls back; remote orphan
        # objects may remain and can be removed by an operator after checking references.
        for name in names:
            storage.put(name, (uploads/name).read_bytes(), mimetypes.guess_type(name)[0] or 'application/octet-stream')
        for table, records in data.items():
            for row in records:
                if any(not re.fullmatch(r'[a-z_]+', column) for column in row):
                    raise ValueError('O esquema do banco de origem contém colunas inválidas.')
                columns = ','.join(row)
                placeholders = ','.join('?' for _ in row)
                database.execute(f'INSERT INTO {table}({columns}) VALUES({placeholders})', tuple(row.values()))
        for table in IDENTITY_TABLES:
            database.execute(f"SELECT setval(pg_get_serial_sequence('{table}','id'), COALESCE((SELECT MAX(id) FROM {table}),1), EXISTS(SELECT 1 FROM {table}))")
        database.commit()
        return sum(map(len, data.values())), len(names)
    except Exception:
        database.rollback()
        raise
