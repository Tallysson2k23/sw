import os, secrets, time, hashlib, getpass, io
from database import Database, INTEGRITY_ERRORS
from storage import Storage, BotoCoreError, ClientError
from PIL import Image, ImageOps, UnidentifiedImageError
from pathlib import Path
from datetime import datetime, timezone, timedelta
from functools import wraps
from urllib.parse import urlparse
import click
from flask import Flask, render_template, request, redirect, url_for, session, g, abort, flash, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import HTTPException

ROOT = Path(__file__).parent
PRIVACY_DEFAULT = 'MODELO PARA REVISÃO: os dados informados serão utilizados para responder ao seu interesse nos cursos. O responsável pelo negócio deve definir contato de privacidade, bases legais e prazos de retenção antes da operação.'

def create_app(test_config=None):
    # Minimal dotenv reader: secrets remain outside source control.
    env = ROOT / '.env'
    if env.exists():
        for line in env.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())
    app = Flask(__name__)
    app.config.update(SECRET_KEY=os.environ.get('SECRET_KEY'), DATABASE=os.environ.get('DATABASE', str(ROOT/'instance/sw.sqlite3')), UPLOAD_FOLDER=str(ROOT/'instance/uploads'), MAX_CONTENT_LENGTH=10*1024*1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE') == '1', PERMANENT_SESSION_LIFETIME=timedelta(hours=8))
    app.config.update(DATABASE_URL=os.environ.get('DATABASE_URL',''), STORAGE_BACKEND=os.environ.get('STORAGE_BACKEND','local'), SERVERLESS=os.environ.get('VERCEL')=='1')
    for key in ['S3_ENDPOINT_URL','S3_BUCKET','S3_ACCESS_KEY_ID','S3_SECRET_ACCESS_KEY','S3_REGION']:
        app.config[key]=os.environ.get(key, 'auto' if key=='S3_REGION' else '')
    if test_config: app.config.update(test_config)
    if app.config['SERVERLESS']:
        if not app.config['DATABASE_URL'] or app.config['STORAGE_BACKEND']!='s3':
            raise RuntimeError('Na Vercel configure DATABASE_URL PostgreSQL e STORAGE_BACKEND=s3; armazenamento local não é persistente.')
        app.config.update(SESSION_COOKIE_SECURE=True, MAX_CONTENT_LENGTH=4*1024*1024)
    if app.config['DATABASE_URL'] and not app.config['DATABASE_URL'].startswith(('postgres://','postgresql://')):
        raise RuntimeError('DATABASE_URL deve ser uma conexão PostgreSQL.')
    if app.config['STORAGE_BACKEND'] not in ['local','s3']:
        raise RuntimeError('STORAGE_BACKEND deve ser local ou s3.')
    if not app.config['SECRET_KEY'] or len(app.config['SECRET_KEY']) < 32 or app.config['SECRET_KEY']=='gere-uma-chave-aleatoria-com-pelo-menos-32-caracteres':
        raise RuntimeError('Configure SECRET_KEY com pelo menos 32 caracteres no .env antes de iniciar.')
    if not app.config['DATABASE_URL']: Path(app.config['DATABASE']).parent.mkdir(parents=True, exist_ok=True)
    files=Storage(app.config)
    app.extensions['storage']=files

    def db():
        if 'db' not in g:
            g.db = Database(app.config)
        return g.db

    def rows(sql, args=()): return db().execute(sql,args).fetchall()
    def one(sql, args=()): return db().execute(sql,args).fetchone()
    def change(sql,args=()):
        cur=db().execute(sql,args); db().commit(); return cur.rowcount
    def audit(action): change('INSERT INTO audit(actor,action,created_at) VALUES(?,?,?)',(g.user['id'],action,now()))
    def now(): return datetime.now(timezone.utc).isoformat()
    def setting(key, default=''):
        item=one('SELECT value FROM settings WHERE key=?',(key,)); return item['value'] if item else default
    def required(name, limit=300):
        value=request.form.get(name,'').strip()
        if not value or len(value)>limit: abort(400, f'Preencha {name} corretamente (até {limit} caracteres).')
        if name in ['id','course_id','user_id'] and (not value.isascii() or not value.isdecimal()): abort(400,'Identificador inválido.')
        return value
    def email(value):
        value=value.strip().lower()
        if len(value)>254 or '@' not in value or '.' not in value.split('@')[-1]: abort(400,'Informe um e-mail válido.')
        return value
    def password(value):
        if len(value)<12 or len(value)>128: abort(400,'A senha deve ter entre 12 e 128 caracteres.')
        return generate_password_hash(value,method='scrypt')
    def protect(role=None):
        def decorator(fn):
            @wraps(fn)
            def wrapped(*args,**kwargs):
                if not g.user: return redirect(url_for('login'))
                if role and g.user['role']!=role: abort(403)
                return fn(*args,**kwargs)
            return wrapped
        return decorator
    def allowed(course_id):
        return g.user and (g.user['role']=='admin' or one('SELECT 1 FROM enrollments e JOIN courses c ON c.id=e.course_id WHERE e.user_id=? AND e.course_id=? AND c.active=1 AND c.deleted=0',(g.user['id'],course_id)))

    def order_value():
        value=request.form.get('sort_order','0')
        if not value.isascii() or not value.isdecimal() or len(value)>4 or int(value)>999: abort(400,'A ordem deve ser um número de 0 a 999.')
        return int(value)

    def public_image():
        file=request.files.get('image')
        if not file or not file.filename: abort(400,'Selecione uma imagem PNG ou JPEG.')
        if Path(file.filename).suffix.lower() not in ['.png','.jpg','.jpeg']: abort(400,'Utilize PNG ou JPEG.')
        try:
            with Image.open(file.stream) as image:
                if image.format not in ['PNG','JPEG'] or image.width*image.height>20_000_000: abort(400,'Imagem inválida ou muito grande (máximo 20 milhões de pixels).')
                image.load()
                clean=ImageOps.exif_transpose(image).convert('RGB')
                clean.thumbnail((2400,2400))
                # Re-encode decoded pixels: discard metadata and any appended payload.
                output=io.BytesIO(); clean.save(output,format='JPEG',quality=90)
        except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError): abort(400,'O arquivo não é uma imagem válida.')
        filename=secrets.token_hex(24)+'.jpg'
        files.put(filename,output.getvalue(),'image/jpeg')
        return filename

    def announcement_link():
        value=request.form.get('link','').strip()
        parsed=urlparse(value)
        if len(value)>1000 or any(ord(c)<32 or c=='\\' for c in value): abort(400,'Link inválido.')
        if value and not ((parsed.scheme=='https' and parsed.netloc) or (value.startswith('/') and not value.startswith('//') and not parsed.netloc and not parsed.scheme)):
            abort(400,'Use um endereço HTTPS ou um caminho do site começando com /.')
        return value

    @app.teardown_appcontext
    def close(error):
        conn=g.pop('db',None)
        if conn: conn.close()

    @app.before_request
    def before():
        g.user=one('SELECT * FROM users WHERE id=? AND active=1',(session.get('uid'),)) if session.get('uid') else None
        if g.user and session.get('auth') != hashlib.sha256(g.user['password'].encode()).hexdigest():
            session.clear(); g.user=None
        session.setdefault('csrf',secrets.token_hex(32))
        if request.method=='POST' and not secrets.compare_digest(session['csrf'],request.form.get('csrf','')): abort(400,'Sessão de formulário expirada. Recarregue a página.')

    @app.after_request
    def headers(response):
        response.headers.update({'X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'same-origin','Content-Security-Policy':"default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'",'Cache-Control':'no-store'})
        if files.origin:
            response.headers['Content-Security-Policy']=response.headers['Content-Security-Policy'].replace("img-src 'self' data:","img-src 'self' data: "+files.origin)
        if app.config['SESSION_COOKIE_SECURE']: response.headers['Strict-Transport-Security']='max-age=31536000'
        return response

    @app.context_processor
    def context(): return dict(upload_limit_mb=app.config['MAX_CONTENT_LENGTH']//(1024*1024),theme=setting('theme','school'),user=g.user,csrf=session.get('csrf'),company=setting('company','SW Cursos'),intro=setting('intro','Conhecimento para abrir novos caminhos.'),privacy=setting('privacy',PRIVACY_DEFAULT),contact=setting('contact','Contato a ser informado pela SW Cursos.'),about=setting('about','Um espaço para conhecer possibilidades de formação e acessar os materiais dos seus cursos em um só lugar.'),benefit1=setting('benefit1','Encontre seu interesse: consulte categorias e descrições antes de escolher.'),benefit2=setting('benefit2','Converse com a equipe: solicite informações sobre os cursos disponíveis.'),benefit3=setting('benefit3','Continue aprendendo: alunos matriculados acessam seus materiais na área do aluno.'))

    @app.errorhandler(BotoCoreError)
    @app.errorhandler(ClientError)
    def storage_error(error):
        return render_template('error.html',code=503,message='O armazenamento está indisponível. Tente novamente em instantes.'),503

    @app.errorhandler(HTTPException)
    def error(e):
        messages={403:'Você não tem permissão para acessar este conteúdo.',404:'O endereço não existe ou o conteúdo está indisponível.',413:f"O envio ultrapassou o limite de {app.config['MAX_CONTENT_LENGTH']//(1024*1024)} MB.",500:'Ocorreu um erro interno. Tente novamente ou contate a administração.'}
        return render_template('error.html',code=e.code,message=messages.get(e.code,e.description)),e.code

    @app.route('/')
    def home(): return render_template('home.html',announcements=rows('SELECT * FROM announcements WHERE active=1 ORDER BY sort_order,id'),courses=rows('SELECT c.*,(SELECT id FROM course_photos WHERE course_id=c.id ORDER BY sort_order,id LIMIT 1) photo_id FROM courses c WHERE active=1 AND deleted=0 LIMIT 3'))
    @app.route('/cursos')
    def courses(): return render_template('courses.html',courses=rows('SELECT c.*,(SELECT id FROM course_photos WHERE course_id=c.id ORDER BY sort_order,id LIMIT 1) photo_id FROM courses c WHERE active=1 AND deleted=0 AND (title LIKE ? OR category LIKE ?)',['%'+request.args.get('q','')+'%']*2))
    @app.route('/cursos/<int:id>')
    def course(id):
        item=one('SELECT * FROM courses WHERE id=? AND active=1 AND deleted=0',(id,))
        if not item: abort(404)
        return render_template('course.html',course=item,photos=rows('SELECT * FROM course_photos WHERE course_id=? ORDER BY sort_order,id',(id,)))
    @app.route('/privacidade')
    def privacy_page(): return render_template('privacy.html')

    @app.get('/foto/<int:id>')
    def course_photo(id):
        photo=one('SELECT p.*,c.active,c.deleted FROM course_photos p JOIN courses c ON c.id=p.course_id WHERE p.id=?',(id,))
        if not photo or photo['deleted'] or (not photo['active'] and not (g.user and g.user['role']=='admin')): abort(404)
        return files.response(photo['filename'],'image/jpeg')

    @app.get('/anuncio/<int:id>/imagem')
    def announcement_image(id):
        item=one('SELECT * FROM announcements WHERE id=?',(id,))
        if not item or (not item['active'] and not (g.user and g.user['role']=='admin')): abort(404)
        return files.response(item['filename'],'image/jpeg')
    @app.route('/interesse',methods=['GET','POST'])
    def interest():
        if request.method=='POST':
            key='lead:'+request.remote_addr
            throttle(key,10)
            name=required('name',150); phone=required('phone',30)
            if sum(c.isdigit() for c in phone)<8: abort(400,'Informe um telefone válido.')
            cid=required('course_id',10)
            if not one('SELECT id FROM courses WHERE id=? AND active=1 AND deleted=0',(cid,)): abort(400,'Selecione um curso ativo.')
            if request.form.get('consent')!='yes': abort(400,'É necessário ler e declarar ciência do aviso de privacidade.')
            mail=email(request.form['email']) if request.form.get('email') else ''
            change('INSERT INTO leads(name,phone,email,course_id,message,consent_at,privacy_snapshot) VALUES(?,?,?,?,?,?,?)',(name,phone,mail,cid,request.form.get('message','')[:2000],now(),setting('privacy',PRIVACY_DEFAULT)))
            flash('Interesse registrado. A equipe poderá consultar seus dados para retornar o contato.'); return redirect(url_for('interest'))
        return render_template('interest.html',courses=rows('SELECT * FROM courses WHERE active=1 AND deleted=0'))

    def throttle(key,limit):
        change('DELETE FROM attempts WHERE created < ?',(time.time()-900,))
        if one('SELECT COUNT(*) n FROM attempts WHERE key=?',(key,))['n']>=limit: abort(429,'Muitas tentativas. Aguarde 15 minutos.')
        change('INSERT INTO attempts VALUES(?,?)',(key,time.time()))

    @app.route('/login',methods=['GET','POST'])
    def login():
        if request.method=='POST':
            throttle('login:'+request.remote_addr,10)
            mail=email(required('email')); throttle('account:'+hashlib.sha256(mail.encode()).hexdigest(),10)
            u=one('SELECT * FROM users WHERE email=? AND active=1',(mail,))
            valid=check_password_hash(u['password'] if u else app.config['DUMMY_HASH'],request.form.get('password',''))
            if not u or not valid: flash('E-mail ou senha inválidos.'); return render_template('login.html'),401
            session.clear(); session.update(uid=u['id'],auth=hashlib.sha256(u['password'].encode()).hexdigest(),csrf=secrets.token_hex(32)); session.permanent=True
            return redirect(url_for('admin' if u['role']=='admin' else 'student'))
        return render_template('login.html')
    @app.post('/logout')
    def logout(): session.clear(); return redirect(url_for('home'))

    @app.route('/aluno',methods=['GET','POST'])
    @protect()
    def student():
        if request.method=='POST':
            name=required('name',150); mail=email(required('email'))
            if one('SELECT id FROM users WHERE email=? AND id<>?',(mail,g.user['id'])): abort(400,'E-mail já cadastrado.')
            change('UPDATE users SET name=?,email=? WHERE id=?',(name,mail,g.user['id']))
            if request.form.get('password'): change('UPDATE users SET password=? WHERE id=?',(password(request.form['password']),g.user['id']))
            flash('Dados atualizados.'); return redirect(url_for('student'))
        return render_template('student.html',courses=rows('SELECT c.* FROM courses c JOIN enrollments e ON e.course_id=c.id WHERE e.user_id=? AND c.active=1 AND c.deleted=0',(g.user['id'],)))
    @app.get('/aluno/curso/<int:id>')
    @protect()
    def classroom(id):
        if not allowed(id): abort(403)
        c=one('SELECT * FROM courses WHERE id=?',(id,))
        if not c: abort(404)
        return render_template('classroom.html',course=c,materials=rows('SELECT * FROM materials WHERE course_id=? ORDER BY id',(id,)))
    @app.get('/material/<int:id>')
    @protect()
    def material(id):
        item=one('SELECT * FROM materials WHERE id=?',(id,))
        if not item: abort(404)
        if not allowed(item['course_id']): abort(403)
        if item['kind']=='file': return files.response(item['content'],item['mime'],item['filename'])
        if item['kind']=='link': return redirect(item['content'])
        return render_template('text.html',material=item)

    @app.get('/admin')
    @protect('admin')
    def admin():
        return render_template('admin.html',counts=[one('SELECT COUNT(*) n FROM '+table)['n'] for table in ['courses WHERE deleted=0','users','leads']],photos=rows('SELECT p.*,c.title course_title FROM course_photos p JOIN courses c ON c.id=p.course_id WHERE c.deleted=0 ORDER BY p.course_id,p.sort_order,p.id'),announcements=rows('SELECT * FROM announcements ORDER BY sort_order,id'),courses=rows('SELECT * FROM courses WHERE deleted=0 ORDER BY id DESC'),students=rows("SELECT id,name,email,active FROM users WHERE role='student' ORDER BY name"),leads=rows('SELECT l.*,c.title FROM leads l LEFT JOIN courses c ON c.id=l.course_id ORDER BY l.id DESC'),enrollments=rows('SELECT e.*,u.name,c.title FROM enrollments e JOIN users u ON u.id=e.user_id JOIN courses c ON c.id=e.course_id'),materials=rows('SELECT m.*,c.title course_title FROM materials m JOIN courses c ON c.id=m.course_id WHERE c.deleted=0'),settings=rows('SELECT * FROM settings'),audit=rows('SELECT a.*,u.name FROM audit a LEFT JOIN users u ON u.id=a.actor ORDER BY a.id DESC LIMIT 50'))

    @app.post('/admin/<action>')
    @protect('admin')
    def mutate(action):
        f=request.form
        if f.get('id') and (not f['id'].isascii() or not f['id'].isdecimal()): abort(400,'Identificador inválido.')
        if action=='course':
            values=(required('title',180),required('description',5000),required('category',100),int(f.get('active')=='on'),int(f.get('demo')=='on'))
            if f.get('id'): change('UPDATE courses SET title=?,description=?,category=?,active=?,demo=? WHERE id=? AND deleted=0',(*values,int(f['id'])))
            else: change('INSERT INTO courses(title,description,category,active,demo) VALUES(?,?,?,?,?)',values)
        elif action=='delete-course':
            cid=required('id',10)
            if not one('SELECT id FROM courses WHERE id=? AND deleted=0',(cid,)): abort(404)
            # Logical deletion preserves historical contacts and enrollment records.
            change('UPDATE courses SET deleted=1,active=0 WHERE id=?',(cid,))
        elif action=='photo':
            cid=required('course_id',10)
            if not one('SELECT id FROM courses WHERE id=? AND deleted=0',(cid,)): abort(404)
            caption=required('caption',250); order=order_value()
            pid=f.get('id')
            old=one('SELECT * FROM course_photos WHERE id=? AND course_id=?',(pid,cid)) if pid else None
            if pid and not old: abort(404)
            replacement=request.files.get('image')
            filename=public_image() if not old or (replacement and replacement.filename) else old['filename']
            if old:
                change('UPDATE course_photos SET caption=?,sort_order=?,filename=? WHERE id=?',(caption,order,filename,pid))
                if filename!=old['filename']: files.delete(old['filename'])
            else: change('INSERT INTO course_photos(course_id,filename,caption,sort_order) VALUES(?,?,?,?)',(cid,filename,caption,order))
        elif action=='delete-photo':
            item=one('SELECT * FROM course_photos WHERE id=?',(required('id',10),))
            if not item: abort(404)
            change('DELETE FROM course_photos WHERE id=?',(item['id'],))
            files.delete(item['filename'])
        elif action=='announcement':
            title=required('title',180); description=f.get('description','').strip()
            if len(description)>1000: abort(400,'A descrição deve ter até 1000 caracteres.')
            link=announcement_link(); order=order_value(); aid=f.get('id')
            old=one('SELECT * FROM announcements WHERE id=?',(aid,)) if aid else None
            if aid and not old: abort(404)
            replacement=request.files.get('image')
            filename=public_image() if not old or (replacement and replacement.filename) else old['filename']
            values=(title,description,filename,link,int(f.get('active')=='on'),order)
            if old:
                change('UPDATE announcements SET title=?,description=?,filename=?,link=?,active=?,sort_order=? WHERE id=?',(*values,aid))
                if filename!=old['filename']: files.delete(old['filename'])
            else: change('INSERT INTO announcements(title,description,filename,link,active,sort_order) VALUES(?,?,?,?,?,?)',values)
        elif action=='delete-announcement':
            item=one('SELECT * FROM announcements WHERE id=?',(required('id',10),))
            if not item: abort(404)
            change('DELETE FROM announcements WHERE id=?',(item['id'],))
            files.delete(item['filename'])
        elif action=='student':
            name=required('name',150); mail=email(required('email')); active=int(f.get('active')=='on'); uid=f.get('id')
            if one('SELECT id FROM users WHERE email=? AND id<>?',(mail,int(uid or 0))): abort(400,'E-mail já cadastrado.')
            if uid:
                change("UPDATE users SET name=?,email=?,active=? WHERE id=? AND role='student'",(name,mail,active,int(uid)))
                if f.get('password'): change("UPDATE users SET password=? WHERE id=? AND role='student'",(password(f['password']),int(uid)))
            else: change("INSERT INTO users(name,email,password,role,active) VALUES(?,?,?,'student',?)",(name,mail,password(required('password',128)),active))
        elif action=='enroll':
            uid=required('user_id',10); cid=required('course_id',10)
            if not one("SELECT id FROM users WHERE id=? AND role='student'",(uid,)) or not one('SELECT id FROM courses WHERE id=? AND deleted=0',(cid,)): abort(400,'Aluno ou curso inválido.')
            if f.get('remove'): change('DELETE FROM enrollments WHERE user_id=? AND course_id=?',(uid,cid))
            else: change('INSERT INTO enrollments VALUES(?,?) ON CONFLICT DO NOTHING',(uid,cid))
        elif action=='lead':
            status=required('status')
            if status not in ['novo','em atendimento','concluído']: abort(400)
            change('UPDATE leads SET status=? WHERE id=?',(status,int(required('id',10))))
        elif action=='settings':
            theme=f.get('theme','school')
            if theme not in ['school','green','blue','purple']: abort(400,'Tema inválido.')
            change('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('theme',theme))
            for key in ['company','intro','contact','privacy','about','benefit1','benefit2','benefit3']:
                change('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,required(key,5000)))
        elif action=='material':
            cid=required('course_id',10); title=required('title',180); kind=required('kind',10)
            if not one('SELECT id FROM courses WHERE id=? AND deleted=0',(cid,)): abort(400,'Curso inválido.')
            content=''; filename=None; mime=None
            if kind=='file':
                file=request.files.get('file')
                if not file or not file.filename: abort(400,'Selecione um arquivo.')
                data=file.read(); ext=Path(file.filename).suffix.lower()
                checks={'.pdf':(b'%PDF-','application/pdf'),'.png':(b'\x89PNG\r\n\x1a\n','image/png'),'.jpg':(b'\xff\xd8\xff','image/jpeg'),'.jpeg':(b'\xff\xd8\xff','image/jpeg')}
                if ext not in checks or not data.startswith(checks[ext][0]): abort(400,'Envie um arquivo PDF, PNG ou JPEG válido.')
                content=secrets.token_hex(24)+ext; filename=Path(file.filename).name; mime=checks[ext][1]
                files.put(content,data,mime)
            elif kind in ['link','text']:
                content=required('content',20000)
                if kind=='link' and (urlparse(content).scheme!='https' or not urlparse(content).netloc): abort(400,'Utilize um link HTTPS válido.')
            else: abort(400,'Tipo inválido.')
            change('INSERT INTO materials(course_id,title,kind,content,filename,mime) VALUES(?,?,?,?,?,?)',(cid,title,kind,content,filename,mime))
        elif action=='edit-material':
            item=one('SELECT * FROM materials WHERE id=?',(required('id',10),))
            if not item: abort(404)
            title=required('title',180); cid=required('course_id',10)
            if not one('SELECT id FROM courses WHERE id=? AND deleted=0',(cid,)): abort(400,'Curso inválido.')
            content=item['content'] if item['kind']=='file' else required('content',20000)
            if item['kind']=='link' and (urlparse(content).scheme!='https' or not urlparse(content).netloc): abort(400,'Utilize um link HTTPS válido.')
            change('UPDATE materials SET title=?,course_id=?,content=? WHERE id=?',(title,cid,content,item['id']))
        elif action=='delete-material':
            item=one('SELECT * FROM materials WHERE id=?',(required('id',10),))
            if not item: abort(404)
            change('DELETE FROM materials WHERE id=?',(item['id'],))
            if item['kind']=='file': files.delete(item['content'])
        else: abort(404)
        audit(action); flash('Alteração salva com sucesso.'); return redirect(url_for('admin'))

    @app.get('/sw.js')
    def worker(): return app.send_static_file('sw.js')
    @app.cli.command('init-db')
    def init_db():
        db().migrate(ROOT)
        click.echo('Banco atualizado com todas as migrações.')
    @app.cli.command('seed-demo')
    def seed():
        if not one('SELECT id FROM courses WHERE demo=1'):
            for title,cat,desc in [('Excel na prática','Tecnologia','DEMONSTRAÇÃO: organização de planilhas, fórmulas e análise de dados.'),('Comunicação profissional','Desenvolvimento','DEMONSTRAÇÃO: clareza na comunicação e nas relações de trabalho.'),('Gestão de pequenos negócios','Gestão','DEMONSTRAÇÃO: fundamentos de planejamento e organização financeira.')]:
                change('INSERT INTO courses(title,category,description,demo) VALUES(?,?,?,1)',(title,cat,desc))
        click.echo('Cursos demonstrativos criados. Nenhum usuário ou contato fictício foi criado.')
    @app.cli.command('import-local')
    @click.option('--source',required=True,type=click.Path(exists=True,dir_okay=False))
    @click.option('--uploads',required=True,type=click.Path(exists=True,file_okay=False))
    def transfer_local(source,uploads):
        from cloud_import import import_local
        try:
            records,objects=import_local(db(),files,source,uploads)
        except (ValueError,OSError) as error:
            raise click.ClickException(str(error))
        click.echo(f'Importação concluída: {records} registros e {objects} arquivos. Origem preservada.')
    @app.cli.command('create-admin')
    @click.option('--email',prompt=True)
    @click.option('--name',prompt=True)
    def create_admin(email,name):
        pw=getpass.getpass('Senha (mínimo 12 caracteres): ')
        if pw!=getpass.getpass('Confirme a senha: ') or len(pw)<12 or len(pw)>128 or '@' not in email: raise click.ClickException('Dados inválidos ou senhas diferentes.')
        try: change("INSERT INTO users(name,email,password,role) VALUES(?,?,?,'admin')",(name,email.strip().lower(),generate_password_hash(pw,method='scrypt')))
        except INTEGRITY_ERRORS: raise click.ClickException('E-mail já cadastrado.')
        click.echo('Administrador criado.')
    @app.cli.command('reset-password')
    @click.option('--email',prompt=True)
    def reset_password(email):
        u=one('SELECT id FROM users WHERE email=?',(email.strip().lower(),))
        if not u: raise click.ClickException('Usuário não encontrado.')
        pw=getpass.getpass('Nova senha: ')
        if len(pw)<12 or len(pw)>128 or pw!=getpass.getpass('Confirme: '): raise click.ClickException('Senha inválida.')
        change('UPDATE users SET password=? WHERE id=?',(generate_password_hash(pw,method='scrypt'),u['id']))
        click.echo('Senha redefinida localmente. Sessões anteriores serão invalidadas no próximo acesso.')
    app.config['DUMMY_HASH']=generate_password_hash(secrets.token_hex(24),method='scrypt')
    return app
