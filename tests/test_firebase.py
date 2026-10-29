"""Exercise existing authorization/CRUD flows against an in-memory Firestore double.

The double replaces the network, not the Firestore adapter. Real service access
is a separate deployment check with the project's private credentials.
"""
import copy
import sqlite3
import unittest
from unittest.mock import MagicMock, patch
import test_app as helpers
from firestore_database import FirestoreDatabase
from storage import Storage


class Snapshot:
    def __init__(self, data): self.data = copy.deepcopy(data); self.exists = data is not None
    def to_dict(self): return copy.deepcopy(self.data)


class Reference:
    def __init__(self, client, path): self.client, self.path = client, path; self.id = path[-1]
    def get(self, transaction=None): return Snapshot(self.client.data.get(self.path))
    def set(self, data): self.client.data[self.path] = copy.deepcopy(data)
    def delete(self): self.client.data.pop(self.path, None)


class Collection:
    def __init__(self, client, name, filters=()): self.client, self.name, self.filters = client, name, filters
    def document(self, id=None):
        if id is None: self.client.serial += 1; id = f'random-{self.client.serial}'
        return Reference(self.client, (self.name, id))
    def where(self, *, filter): return Collection(self.client, self.name, (*self.filters, filter))
    def stream(self):
        for (name, _), row in list(self.client.data.items()):
            if name != self.name: continue
            if all({'==':lambda a,b:a==b, '!=':lambda a,b:a!=b, '<':lambda a,b:a<b}[f.op_string](row.get(f.field_path), f.value) for f in self.filters):
                yield Snapshot(row)


class Transaction:
    def set(self, ref, data): ref.set(data)
    def create(self, ref, data):
        if ref.get().exists: raise sqlite3.IntegrityError('Document exists')
        ref.set(data)
    def update(self, ref, data): ref.set({**ref.get().to_dict(), **data})
    def delete(self, ref): ref.delete()


class Client:
    def __init__(self): self.data = {}; self.serial = 0
    def collection(self, name): return Collection(self, name)
    def transaction(self): return Transaction()


class FixtureConnection:
    """Keep the original tests' SQLite inspection interface for their assertions."""
    def __init__(self, database): self.database = database
    def execute(self, sql, args=()):
        if 'SELECT COUNT(*) FROM' in sql: sql = sql.replace('COUNT(*)', 'COUNT(*) n')
        result = self.database.execute(sql, args)
        for i, row in enumerate(result.rows):
            class Row(dict):
                def __getitem__(self, key): return list(self.values())[key] if isinstance(key,int) else super().__getitem__(key)
            result.rows[i] = Row(row)
        return result
    def commit(self): pass
    def close(self): pass


class FirebasePlatformTests(helpers.PlatformTests):
    def setUp(self):
        super().setUp()
        self.network = Client()
        self.client_patch = patch('firestore_database.configured_clients', return_value=(self.network, MagicMock()))
        self.client_patch.start(); self.addCleanup(self.client_patch.stop)
        self.transaction_patch = patch('firestore_database.firestore.transactional', side_effect=lambda fn:fn)
        self.transaction_patch.start(); self.addCleanup(self.transaction_patch.stop)
        config = dict(self.app.config, DATABASE_BACKEND='firestore', FIREBASE_PROJECT_ID='test-only', FIREBASE_CREDENTIALS_JSON='{}', FIREBASE_STORAGE_BUCKET='test-only')
        database = FirestoreDatabase(config)
        self.conn.row_factory = sqlite3.Row
        for table in ['users','courses']:
            for row in self.conn.execute('SELECT * FROM '+table):
                values = dict(row); values.pop('id')
                database.insert(table, values)
        self.conn.close(); self.conn = FixtureConnection(database)
        self.app.config.update(config)

    def test_duplicate_email_and_changed_email_index(self):
        database = self.conn.database
        with self.assertRaises(sqlite3.IntegrityError):
            database.insert('users', dict(name='Duplicado',email='admin@example.test',password='hash',role='student'))
        database.execute('UPDATE users SET name=?,email=? WHERE id=?', ('Admin','new@example.test',1))
        self.assertFalse(database.email_ref('admin@example.test').get().exists)
        self.assertEqual(database.email_ref('new@example.test').get().to_dict()['user_id'],1)
        with self.assertRaises(sqlite3.IntegrityError):
            database.execute('UPDATE users SET name=?,email=? WHERE id=?', ('Admin','aluno@example.test',1))
        self.assertEqual(database.get('users',1)['email'],'new@example.test')

    def test_import_local_preserves_source_and_ids(self):
        from cloud_import import import_local
        from pathlib import Path
        source=Path(self.app.config['DATABASE'])
        original=source.read_bytes()
        target=Client()
        with patch('firestore_database.configured_clients',return_value=(target,MagicMock())):
            database=FirestoreDatabase(self.app.config)
        storage=MagicMock(); storage.firebase=True
        records, objects=import_local(database,storage,source,self.app.config['UPLOAD_FOLDER'])
        self.assertEqual((records,objects),(6,0))
        self.assertEqual(source.read_bytes(),original)
        self.assertEqual(database.get('users',1)['email'],'admin@example.test')
        self.assertEqual(database.get('courses',3)['id'],3)
        database.insert('courses',dict(title='Novo',description='Teste',category='Teste'))
        self.assertEqual(database.get('courses',4)['title'],'Novo')
        with self.assertRaisesRegex(ValueError,'vazio'):
            import_local(database,storage,source,self.app.config['UPLOAD_FOLDER'])

    def test_import_refuses_large_source_before_writes(self):
        from cloud_import import import_local
        source=sqlite3.connect(self.app.config['DATABASE'])
        try:
            source.executemany('INSERT INTO courses(title,description,category) VALUES(?,?,?)',[('Curso','Descrição','Categoria')]*400)
            source.commit()
        finally: source.close()
        storage=MagicMock(); storage.firebase=True
        target=Client()
        with patch('firestore_database.configured_clients',return_value=(target,MagicMock())):
            database=FirestoreDatabase(self.app.config)
        with self.assertRaisesRegex(ValueError,'400 gravações'):
            import_local(database,storage,self.app.config['DATABASE'],self.app.config['UPLOAD_FOLDER'])
        self.assertEqual(target.data,{})
        storage.put.assert_not_called()


class FirebaseConfigurationTests(unittest.TestCase):
    def config(self):
        return dict(TESTING=True, SECRET_KEY='test-only-key-for-firebase-123456789', SERVERLESS=True,
            DATABASE_BACKEND='firestore', DATABASE_URL='', STORAGE_BACKEND='firebase',
            FIREBASE_PROJECT_ID='test-only', FIREBASE_CREDENTIALS_JSON='{}', FIREBASE_STORAGE_BUCKET='test-only.appspot.com')

    def test_serverless_without_local_writes(self):
        from app import create_app
        with patch('firebase_backend.configured_clients',return_value=(Client(),MagicMock())), patch('pathlib.Path.mkdir') as mkdir:
            app = create_app(self.config())
        mkdir.assert_not_called()
        self.assertTrue(app.config['SESSION_COOKIE_SECURE'])
        self.assertEqual(app.config['MAX_CONTENT_LENGTH'],4*1024*1024)

    def test_missing_credentials(self):
        from app import create_app
        config = self.config(); config['FIREBASE_CREDENTIALS_JSON']=''
        with self.assertRaisesRegex(RuntimeError,'FIREBASE_CREDENTIALS_JSON'): create_app(config)

    def test_base64_credentials_without_multiline_env(self):
        import base64
        from firebase_backend import configured_clients
        config=self.config(); config['FIREBASE_CREDENTIALS_JSON']=''
        config['FIREBASE_CREDENTIALS_BASE64']=base64.b64encode(b'{"project_id":"test-only"}').decode()
        with patch('firebase_backend.clients',return_value=('database','bucket')) as clients:
            self.assertEqual(configured_clients(config),('database','bucket'))
        clients.assert_called_once_with('test-only','{"project_id":"test-only"}','test-only.appspot.com')
        config['FIREBASE_CREDENTIALS_BASE64']='invalid-secret!'
        with self.assertRaises(RuntimeError) as error: configured_clients(config)
        self.assertNotIn('invalid-secret!',str(error.exception))

    def test_mismatched_project_and_invalid_credentials_are_redacted(self):
        from firebase_backend import clients
        for credentials in ['secret-invalid-json', '{"project_id":"other"}']:
            with self.assertRaises(RuntimeError) as error: clients('test-only',credentials,'bucket')
            self.assertNotIn(credentials,str(error.exception))

    def test_firebase_storage_and_private_signed_download(self):
        bucket = MagicMock()
        with patch('firebase_backend.configured_clients',return_value=(Client(),bucket)):
            storage = Storage({**self.config(),'UPLOAD_FOLDER':'unused'})
        name = 'a'*48+'.pdf'
        storage.put(name,b'%PDF-test','application/pdf')
        blob=bucket.blob.return_value
        blob.upload_from_string.assert_called_once_with(b'%PDF-test',content_type='application/pdf',timeout=20)
        self.assertEqual(blob.cache_control,'private, no-store')
        blob.generate_signed_url.return_value='https://storage.googleapis.com/test/file?signature=test'
        from flask import Flask
        with Flask(__name__).test_request_context(): response=storage.response(name,'application/pdf','Guia.pdf')
        self.assertEqual(response.status_code,302)
        self.assertEqual(blob.generate_signed_url.call_args.kwargs['expiration'].total_seconds(),60)
        self.assertEqual(blob.generate_signed_url.call_args.kwargs['response_disposition'],'attachment; filename="Guia.pdf"')
        storage.delete(name); blob.delete.assert_called_once_with(timeout=20)

    def test_authorization_before_firebase_download(self):
        fixture = FirebasePlatformTests(methodName='test_public_pages')
        fixture.setUp()
        try:
            database=fixture.conn.database
            database.insert('materials',dict(course_id=1,title='PDF',kind='file',content='b'*48+'.pdf',filename='Guia.pdf',mime='application/pdf'))
            storage=fixture.app.extensions['storage']; storage.firebase=True; storage.remote=True; storage.firebase_bucket=MagicMock()
            storage.firebase_bucket.blob.return_value.generate_signed_url.return_value='https://storage.googleapis.com/test/pdf?signature=test'
            fixture.login('aluno')
            self.assertEqual(fixture.client.get('/material/1').status_code,403)
            storage.firebase_bucket.blob.assert_not_called()
            database.execute('INSERT INTO enrollments VALUES(?,?) ON CONFLICT DO NOTHING',(2,1))
            self.assertEqual(fixture.client.get('/material/1').status_code,302)
            database.execute('DELETE FROM enrollments WHERE user_id=? AND course_id=?',(2,1))
            storage.firebase_bucket.reset_mock()
            self.assertEqual(fixture.client.get('/material/1').status_code,403)
            storage.firebase_bucket.blob.assert_not_called()
        finally:
            fixture.tearDown(); fixture.doCleanups()
