"""Explicit, operator-run transfer. Never invoked during a web request/build."""
import mimetypes
import re
import sqlite3
from pathlib import Path

TABLES = ('users', 'courses', 'enrollments', 'materials', 'leads', 'settings', 'audit', 'course_photos', 'announcements')
IDENTITY_TABLES = ('users', 'courses', 'materials', 'leads', 'audit', 'course_photos', 'announcements')


def import_local(database, storage, source, uploads):
    if getattr(database, 'firebase', False) is True:
        return import_firebase(database, storage, source, uploads)
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


def import_firebase(database, storage, source, uploads):
    """Atomic record import into an unused Firestore namespace; source is read-only.

    Intentionally bounded below Firestore's transaction size/write limits. Larger
    migrations need an operator-run resumable tool and a separate maintenance plan.
    """
    import hashlib
    import json
    from google.cloud import firestore
    from firestore_database import DEFAULTS
    if not getattr(storage, 'firebase', False):
        raise ValueError('Configure STORAGE_BACKEND=firebase antes da importação.')
    source, uploads = Path(source).resolve(), Path(uploads).resolve()
    connection = sqlite3.connect(source.as_uri()+'?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        data = {table:[dict(row) for row in connection.execute('SELECT * FROM '+table)] for table in TABLES}
    finally: connection.close()
    records = sum(map(len, data.values()))
    writes = records + len(data['users']) + len(IDENTITY_TABLES)
    if writes > 400 or len(json.dumps(data, ensure_ascii=False).encode()) > 4*1024*1024:
        raise ValueError('Importação Firebase limitada a 400 gravações (registros, índices de e-mail e contadores) e 4 MB. Prepare uma migração supervisionada para bases maiores.')
    emails = [row['email'] for row in data['users']]
    if len(set(emails)) != len(emails): raise ValueError('E-mails duplicados na origem.')
    names = {row['filename'] for table in ('course_photos','announcements') for row in data[table]}
    names.update(row['content'] for row in data['materials'] if row['kind']=='file')
    for name in names:
        storage.key(name)
        if not (uploads/name).is_file(): raise ValueError('Faltam arquivos referenciados na origem.')
    # Preflight before uploading any object. No existing record is overwritten.
    for table in TABLES:
        if next(database.collection(table).stream(), None):
            raise ValueError('O destino Firebase deve estar vazio. Nenhum registro foi sobrescrito.')
    for name in names:
        storage.put(name,(uploads/name).read_bytes(),mimetypes.guess_type(name)[0] or 'application/octet-stream')

    @firestore.transactional
    def write(transaction):
        counters = {table:database.client.collection('sw_counters').document(table) for table in IDENTITY_TABLES}
        for ref in counters.values():
            if ref.get(transaction=transaction).exists:
                raise ValueError('O destino Firebase já foi utilizado; use um projeto vazio.')
        for table, rows in data.items():
            for row in rows:
                ref = database.collection(table).document(database.document_id(table,row))
                transaction.create(ref, {**DEFAULTS[table], **row})
                if table == 'users':
                    ref = database.client.collection('sw_unique_emails').document(hashlib.sha256(row['email'].encode()).hexdigest())
                    transaction.create(ref, {'user_id':row['id']})
        for table, ref in counters.items():
            transaction.create(ref, {'value':max((row['id'] for row in data[table]),default=0)})
    write(database.client.transaction())
    return records, len(names)
