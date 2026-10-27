import io, re, sqlite3, tempfile, unittest
from pathlib import Path
from werkzeug.security import generate_password_hash
from app import create_app, PRIVACY_DEFAULT
from PIL import Image

class PlatformTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.app=create_app({'TESTING':True,'SECRET_KEY':'test-only-key-not-for-deployment-12345','DATABASE_URL':'','STORAGE_BACKEND':'local','SERVERLESS':False,'DATABASE':str(Path(self.tmp.name)/'test.db'),'UPLOAD_FOLDER':str(Path(self.tmp.name)/'uploads')})
        runner=self.app.test_cli_runner()
        self.assertEqual(runner.invoke(args=['init-db']).exit_code,0)
        self.assertEqual(runner.invoke(args=['seed-demo']).exit_code,0)
        self.conn=sqlite3.connect(self.app.config['DATABASE'])
        for name,role in [('Admin','admin'),('Aluno','student'),('Outro','student')]:
            self.conn.execute('INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)',(name,name.lower()+'@example.test',generate_password_hash('a-test-password-123',method='scrypt'),role))
        self.conn.commit();self.client=self.app.test_client()
    def tearDown(self): self.conn.close(); self.tmp.cleanup()
    def csrf(self):
        self.client.get('/login')
        with self.client.session_transaction() as s: return s['csrf']
    def post(self,url,data=None,**kwargs):
        data=dict(data or {});data['csrf']=self.csrf()
        return self.client.post(url,data=data,**kwargs)
    def login(self,who='admin'):
        return self.post('/login',{'email':who+'@example.test','password':'a-test-password-123'})
    def test_public_pages(self):
        for path in ['/','/cursos','/cursos/1','/interesse','/privacidade','/login','/static/manifest.webmanifest','/sw.js','/static/icon-192.png']:
            with self.client.get(path) as response: self.assertEqual(response.status_code,200,path)
        self.assertEqual(self.client.get('/inexistente').status_code,404)
        self.assertIn('Demonstração',self.client.get('/').text)
    def test_csrf_and_lead_validation(self):
        self.assertEqual(self.client.post('/interesse',data={}).status_code,400)
        result=self.post('/interesse',{'name':'Maria','phone':'85999999999','course_id':'1'})
        self.assertEqual(result.status_code,400)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM leads').fetchone()[0],0)
    def test_lead_admin_and_status(self):
        r=self.post('/interesse',{'name':'Maria','phone':'85999999999','course_id':'1','consent':'yes','message':'Informações'})
        self.assertEqual(r.status_code,302)
        self.assertEqual(self.conn.execute('SELECT privacy_snapshot FROM leads').fetchone()[0],PRIVACY_DEFAULT)
        self.login();self.assertIn('Maria',self.client.get('/admin').text)
        self.assertEqual(self.post('/admin/lead',{'id':'1','status':'em atendimento'}).status_code,302)
        self.assertEqual(self.conn.execute('SELECT status FROM leads').fetchone()[0],'em atendimento')
    def test_login_logout_roles(self):
        self.assertEqual(self.client.get('/admin').status_code,302)
        self.assertEqual(self.login('aluno').status_code,302)
        self.assertEqual(self.client.get('/admin').status_code,403)
        self.assertEqual(self.post('/admin/course',{'title':'Ataque'}).status_code,403)
        self.assertEqual(self.client.get('/aluno').status_code,200)
        self.post('/logout');self.assertEqual(self.client.get('/aluno').status_code,302)
    def test_bad_password_and_throttle(self):
        for _ in range(10):
            self.assertEqual(self.post('/login',{'email':'admin@example.test','password':'wrong'}).status_code,401)
        self.assertEqual(self.login().status_code,429)
    def test_course_student_and_material_flow(self):
        self.login()
        self.assertEqual(self.post('/admin/course',{'title':'Novo curso','description':'Conteúdo real','category':'Gestão','active':'on'}).status_code,302)
        self.assertEqual(self.post('/admin/student',{'name':'Novo','email':'novo@example.test','password':'a-test-password-123','active':'on'}).status_code,302)
        self.assertEqual(self.post('/admin/material',{'course_id':'4','title':'Orientação','kind':'text','content':'Estude com atenção.'}).status_code,302)
        self.assertEqual(self.post('/admin/enroll',{'user_id':'4','course_id':'4'}).status_code,302)
        self.post('/logout');self.login('novo')
        self.assertIn('Novo curso',self.client.get('/aluno').text)
        self.assertIn('Orientação',self.client.get('/aluno/curso/4').text)
        self.assertIn('Estude com atenção.',self.client.get('/material/1').text)
        self.post('/logout');self.login('outro')
        self.assertEqual(self.client.get('/material/1').status_code,403)
        self.assertEqual(self.client.get('/aluno/curso/4').status_code,403)
    def test_private_upload(self):
        self.login()
        r=self.post('/admin/material',{'course_id':'1','title':'PDF','kind':'file','file':(io.BytesIO(b'%PDF-1.4\n test'),'guia.pdf')},content_type='multipart/form-data')
        self.assertEqual(r.status_code,302)
        r=self.client.get('/material/1');self.assertEqual(r.status_code,200);self.assertIn('attachment',r.headers['Content-Disposition']);r.close()
        self.assertEqual(self.client.get('/static/uploads/guia.pdf').status_code,404)
        self.post('/logout');self.login('aluno');self.assertEqual(self.client.get('/material/1').status_code,403)
    def test_invalid_upload_and_url(self):
        self.login()
        self.assertEqual(self.post('/admin/material',{'course_id':'1','title':'Bad','kind':'file','file':(io.BytesIO(b'javascript'),'bad.pdf')},content_type='multipart/form-data').status_code,400)
        self.assertEqual(self.post('/admin/material',{'course_id':'1','title':'Bad','kind':'link','content':'javascript:alert(1)'}).status_code,400)
    def test_disabled_course_revokes_material(self):
        self.login();self.post('/admin/enroll',{'user_id':'2','course_id':'1'});self.post('/admin/material',{'course_id':'1','title':'Text','kind':'text','content':'Private'})
        self.post('/admin/course',{'id':'1','title':'Disabled','description':'Hidden','category':'Test'})
        self.post('/logout');self.login('aluno')
        self.assertEqual(self.client.get('/material/1').status_code,403)
        self.assertEqual(self.client.get('/cursos/1').status_code,404)
    def test_profile_password_revokes_session(self):
        self.login('aluno')
        self.assertEqual(self.post('/aluno',{'name':'Aluno editado','email':'aluno@example.test','password':'changed-password-123'}).status_code,302)
        self.assertEqual(self.client.get('/aluno').status_code,302)
        self.assertEqual(self.post('/login',{'email':'aluno@example.test','password':'changed-password-123'}).status_code,302)
    def test_admin_edits_and_audit(self):
        self.login();self.post('/admin/material',{'course_id':'1','title':'Text','kind':'text','content':'First'})
        self.assertEqual(self.post('/admin/edit-material',{'id':'1','course_id':'2','title':'Edited','content':'Second'}).status_code,302)
        self.assertIn('Second',self.client.get('/material/1').text)
        self.assertGreater(self.conn.execute('SELECT COUNT(*) FROM audit').fetchone()[0],0)
        self.post('/admin/delete-material',{'id':'1'});self.assertEqual(self.client.get('/material/1').status_code,404)
    def test_settings_xss_and_sql(self):
        self.login()
        self.assertEqual(self.post('/admin/settings',dict(company='<script>alert(1)</script>',intro='Teste',contact='Contato',privacy='Aviso',about='Sobre',benefit1='Um',benefit2='Dois',benefit3='Três')).status_code,302)
        page=self.client.get('/');self.assertNotIn('<script>alert(1)</script>',page.text);self.assertIn('&lt;script&gt;',page.text)
        self.assertEqual(self.client.get('/cursos?q=%27%20OR%201=1--').status_code,200)
    def test_cache_security_headers_and_sw(self):
        self.login();r=self.client.get('/admin')
        self.assertEqual(r.headers['Cache-Control'],'no-store');self.assertIn("object-src 'none'",r.headers['Content-Security-Policy'])
        with self.client.get('/sw.js') as response: sw=response.text
        self.assertIn("ASSETS.includes(assetKey)",sw)
        self.assertNotIn("cache.put",sw)
        with self.client.get('/static/offline.html') as response: self.assertEqual(response.status_code,200)
    def test_seed_idempotent(self):
        self.app.test_cli_runner().invoke(args=['init-db']);self.app.test_cli_runner().invoke(args=['seed-demo'])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM courses').fetchone()[0],3)


    def image_data(self):
        data=io.BytesIO();Image.new('RGB',(24,16),'navy').save(data,format='PNG');data.seek(0);return data
    def test_public_gallery_and_cover(self):
        self.login()
        self.assertEqual(self.post('/admin/photo',{'course_id':'1','caption':'Laboratório','sort_order':'0','image':(self.image_data(),'foto.png')}).status_code,302)
        self.assertIn('/foto/1',self.client.get('/cursos').text)
        self.assertIn('Laboratório',self.client.get('/cursos/1').text)
        self.assertIn('Editar foto',self.client.get('/admin').text)
        self.assertEqual(self.post('/admin/photo',{'id':'1','course_id':'1','caption':'Nova legenda','sort_order':'1'}).status_code,302)
        self.post('/logout')
        with self.client.get('/foto/1') as response:
            self.assertEqual(response.status_code,200);self.assertEqual(response.mimetype,'image/jpeg')
        self.assertIn('Nova legenda',self.client.get('/cursos/1').text)
        self.assertNotIn('Gerenciar fotos',self.client.get('/cursos/1').text)
        self.login();self.post('/admin/delete-photo',{'id':'1'})
        self.assertEqual(self.client.get('/foto/1').status_code,404)
    def test_media_admin_only_and_invalid_images(self):
        for role in [None,'aluno']:
            if role:self.login(role)
            for action in ['course','delete-course','photo','delete-photo','announcement','delete-announcement']:
                self.assertEqual(self.post('/admin/'+action,{'id':'1'}).status_code,403 if role else 302)
        self.post('/logout');self.login()
        self.assertEqual(self.post('/admin/photo',{'course_id':'1','caption':'Bad','sort_order':'0','image':(io.BytesIO(b'not png'),'fake.png')}).status_code,400)
        self.assertEqual(self.post('/admin/photo',{'course_id':'1','caption':'Bad','sort_order':'-1','image':(self.image_data(),'good.png')}).status_code,400)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM course_photos').fetchone()[0],0)
    def test_announcements_edit_disable_delete(self):
        self.login()
        data={'title':'Novidades','description':'Confira nossos cursos','link':'/cursos','active':'on','sort_order':'1','image':(self.image_data(),'banner.png')}
        self.assertEqual(self.post('/admin/announcement',data).status_code,302)
        self.assertIn('Novidades',self.client.get('/').text)
        self.assertEqual(self.post('/admin/announcement',{'id':'1','title':'Editado','description':'Atualizado','link':'https://example.test','sort_order':'2'}).status_code,302)
        self.assertIn('Editado',self.client.get('/admin').text)
        self.post('/logout');self.assertNotIn('Editado',self.client.get('/').text)
        self.assertEqual(self.client.get('/anuncio/1/imagem').status_code,404)
        self.login();self.post('/admin/delete-announcement',{'id':'1'})
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM announcements').fetchone()[0],0)
    def test_bad_announcement_link(self):
        self.login()
        for link in ['javascript:alert(1)','//evil.test','/\\evil.test']:
            self.assertEqual(self.post('/admin/announcement',{'title':'Bad','sort_order':'0','link':link,'image':(self.image_data(),'banner.png')}).status_code,400)
    def test_course_delete_revokes_public_and_student_access(self):
        self.login();self.post('/admin/enroll',{'user_id':'2','course_id':'1'})
        self.post('/admin/material',{'course_id':'1','title':'Privado','kind':'text','content':'Teste'})
        self.post('/admin/photo',{'course_id':'1','caption':'Foto','sort_order':'0','image':(self.image_data(),'foto.png')})
        self.assertEqual(self.post('/admin/delete-course',{'id':'1'}).status_code,302)
        self.assertEqual(self.client.get('/cursos/1').status_code,404)
        self.assertEqual(self.client.get('/foto/1').status_code,404)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM enrollments').fetchone()[0],1)
        self.post('/logout');self.login('aluno')
        self.assertEqual(self.client.get('/aluno/curso/1').status_code,403)
        self.assertEqual(self.client.get('/material/1').status_code,403)
        self.assertNotIn('Excel na prática',self.client.get('/aluno').text)

if __name__=='__main__': unittest.main()
