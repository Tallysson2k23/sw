"""Optional real-server smoke test. Set TEST_DATABASE_URL to a disposable database."""
import os
import secrets
import tempfile
import unittest
from pathlib import Path
import psycopg
from psycopg import sql
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from app import create_app


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'Defina TEST_DATABASE_URL para testar PostgreSQL real.')
class PostgreSQLIntegrationTests(unittest.TestCase):
    def test_full_postgres_flow_in_isolated_schema(self):
        schema='sw_test_'+secrets.token_hex(8)
        admin=psycopg.connect(os.environ['TEST_DATABASE_URL'],autocommit=True)
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            with tempfile.TemporaryDirectory() as folder:
                parts=urlsplit(os.environ['TEST_DATABASE_URL'])
                query=dict(parse_qsl(parts.query));query['options']=f'-c search_path={schema}'
                url=urlunsplit((parts.scheme,parts.netloc,parts.path,urlencode(query),parts.fragment))
                app=create_app(dict(TESTING=True,SECRET_KEY='test-key-not-for-production-1234567',SERVERLESS=False,DATABASE_URL=url,STORAGE_BACKEND='local',UPLOAD_FOLDER=folder))
                runner=app.test_cli_runner()
                self.assertEqual(runner.invoke(args=['init-db']).exit_code,0)
                self.assertEqual(runner.invoke(args=['init-db']).exit_code,0)
                self.assertEqual(runner.invoke(args=['seed-demo']).exit_code,0)
                client=app.test_client()
                self.assertEqual(client.get('/cursos?q=excel').status_code,200)
                self.assertIn('Excel',client.get('/cursos?q=excel').text)
                client.get('/interesse')
                with client.session_transaction() as session: token=session['csrf']
                result=client.post('/interesse',data={'csrf':token,'name':'Teste PostgreSQL','phone':'85999999999','course_id':'1','consent':'yes'})
                self.assertEqual(result.status_code,302)
                with psycopg.connect(url) as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM leads').fetchone()[0],1)
        finally:
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
            admin.close()
