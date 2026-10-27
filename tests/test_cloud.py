import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse, parse_qs
from botocore.stub import Stubber
import test_app as helpers
from app import create_app
from database import Database
from storage import Storage
from cloud_import import import_local


class CloudConfigurationTests(unittest.TestCase):
    def config(self):
        return dict(TESTING=True, SECRET_KEY='testing-key-for-config-only-123456789', SERVERLESS=True,
            DATABASE_URL='postgresql://example.invalid/db', STORAGE_BACKEND='s3', S3_ENDPOINT_URL='https://storage.example.test',
            S3_BUCKET='test-bucket', S3_ACCESS_KEY_ID='test-only', S3_SECRET_ACCESS_KEY='test-only', S3_REGION='auto')

    def test_serverless_has_no_local_writes_or_network_on_import(self):
        with patch('pathlib.Path.mkdir') as mkdir, patch('psycopg.connect') as connect:
            app=create_app(self.config())
        mkdir.assert_not_called(); connect.assert_not_called()
        self.assertTrue(app.config['SESSION_COOKIE_SECURE'])
        self.assertEqual(app.config['MAX_CONTENT_LENGTH'],4*1024*1024)

    def test_serverless_refuses_local_persistence(self):
        config=self.config();config['DATABASE_URL']=''
        with self.assertRaisesRegex(RuntimeError,'DATABASE_URL'): create_app(config)

    def test_s3_operations_and_short_lived_download(self):
        storage=Storage({**self.config(),'UPLOAD_FOLDER':'unused'})
        name='a'*48+'.pdf'
        with Stubber(storage.client) as stub:
            stub.add_response('put_object',{},dict(Bucket='test-bucket',Key=name,Body=b'%PDF-test',ContentType='application/pdf',CacheControl='private, no-store'))
            storage.put(name,b'%PDF-test','application/pdf')
            stub.add_response('delete_object',{},dict(Bucket='test-bucket',Key=name))
            storage.delete(name);stub.assert_no_pending_responses()
        app=create_app(self.config())
        with app.test_request_context(): response=storage.response(name,'application/pdf','Guia.pdf')
        query=parse_qs(urlparse(response.location).query)
        self.assertEqual(query['X-Amz-Expires'],['60'])
        self.assertEqual(query['response-content-disposition'],['attachment; filename="Guia.pdf"'])
        self.assertEqual(urlparse(response.location).netloc,'storage.example.test')

    def test_storage_rejects_paths_and_insecure_endpoints(self):
        with self.assertRaises(ValueError): Storage.key('../private.pdf')
        config={**self.config(),'UPLOAD_FOLDER':'unused','S3_ENDPOINT_URL':'http://storage.test'}
        with self.assertRaises(RuntimeError): Storage(config)

    def test_postgres_parameters_tls_and_pooler_support(self):
        with patch('database.psycopg.connect') as connect:
            db=Database(self.config())
            db.execute('SELECT * FROM courses WHERE title LIKE ? AND id=?',('%Excel%',1))
            connect.return_value.execute.assert_called_once_with('SELECT * FROM courses WHERE title ILIKE %s AND id=%s',('%Excel%',1))
            self.assertEqual(connect.call_args.kwargs['sslmode'],'require')
            self.assertIsNone(connect.call_args.kwargs['prepare_threshold'])


class CloudAuthorizationTests(unittest.TestCase):
    setUp=helpers.PlatformTests.setUp
    tearDown=helpers.PlatformTests.tearDown
    csrf=helpers.PlatformTests.csrf
    post=helpers.PlatformTests.post
    login=helpers.PlatformTests.login

    def test_material_permission_before_signed_url(self):
        name='b'*48+'.pdf'
        self.conn.execute("INSERT INTO materials(course_id,title,kind,content,filename,mime) VALUES(1,'Privado','file',?,'Guia.pdf','application/pdf')",(name,));self.conn.commit()
        storage=self.app.extensions['storage'];storage.remote=True;storage.bucket='test-bucket';storage.origin='https://storage.example.test';storage.client=MagicMock()
        storage.client.generate_presigned_url.return_value='https://storage.example.test/private?test-signature'
        self.login('aluno');self.assertEqual(self.client.get('/material/1').status_code,403)
        storage.client.generate_presigned_url.assert_not_called()
        self.conn.execute('INSERT INTO enrollments VALUES(2,1)');self.conn.commit()
        response=self.client.get('/material/1');self.assertEqual(response.status_code,302)
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertIn('https://storage.example.test',response.headers['Content-Security-Policy'])
        self.assertEqual(storage.client.generate_presigned_url.call_args.kwargs['ExpiresIn'],60)
        storage.client.generate_presigned_url.reset_mock()
        self.conn.execute('DELETE FROM enrollments');self.conn.commit()
        self.assertEqual(self.client.get('/material/1').status_code,403)
        storage.client.generate_presigned_url.assert_not_called()

    def test_runtime_upload_limit_shown_and_enforced(self):
        self.app.config['MAX_CONTENT_LENGTH']=4*1024*1024
        self.login()
        self.assertIn('até 4 MB',self.client.get('/admin').text)
        response=self.client.post('/admin/material',data=b'x'*(4*1024*1024+1),content_type='application/octet-stream')
        self.assertEqual(response.status_code,413)

    def test_import_preserves_source_and_rejects_nonempty_destination(self):
        name='c'*48+'.pdf'
        source=Path(self.app.config['DATABASE']);uploads=Path(self.app.config['UPLOAD_FOLDER'])
        (uploads/name).write_bytes(b'%PDF-test')
        self.conn.execute("INSERT INTO materials(course_id,title,kind,content,filename,mime) VALUES(1,'Guia','file',?,'Guia.pdf','application/pdf')",(name,));self.conn.commit()
        original=source.read_bytes()
        destination=MagicMock();destination.postgres=True
        destination.execute.return_value.fetchone.return_value={'n':0}
        storage=MagicMock();storage.remote=True
        records,objects=import_local(destination,storage,source,uploads)
        self.assertGreater(records,0);self.assertEqual(objects,1)
        storage.put.assert_called_once_with(name,b'%PDF-test','application/pdf')
        destination.commit.assert_called_once()
        self.assertEqual(source.read_bytes(),original)
        destination.reset_mock();storage.reset_mock()
        destination.execute.return_value.fetchone.return_value={'n':1}
        with self.assertRaisesRegex(ValueError,'vazio'):import_local(destination,storage,source,uploads)
        storage.put.assert_not_called();destination.rollback.assert_called_once()
