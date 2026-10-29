"""Translate the application's bounded SQL vocabulary to native Firestore operations.

No SQL is sent to Firebase and no local database is used. The existing Flask
authorization and password/session flows are shared by both database backends.
Only server-authored queries are accepted; form values always remain parameters.
"""
import hashlib
import re
import sqlite3
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from firebase_backend import configured_clients


DEFAULTS = {
    'users': dict(active=1), 'courses': dict(active=1, demo=0, deleted=0),
    'enrollments': {}, 'materials': dict(filename=None, mime=None),
    'leads': dict(status='novo', email=None, message=None), 'settings': {},
    'audit': {}, 'attempts': {}, 'course_photos': dict(sort_order=0),
    'announcements': dict(description='', link='', active=1, sort_order=0),
}
ID_FIELDS = {'id', 'user_id', 'course_id', 'actor'}


class Result:
    def __init__(self, rows=(), rowcount=0):
        self.rows, self.rowcount = list(rows), rowcount

    def fetchall(self): return self.rows
    def fetchone(self): return self.rows[0] if self.rows else None


def value(token, arguments):
    if token == '?': return next(arguments)
    if re.fullmatch(r'-?\d+', token): return int(token)
    if re.fullmatch(r"'[^']*'", token): return token[1:-1]
    raise NotImplementedError('Unsupported query literal')


def conditions(text, arguments):
    result = []
    for term in text.split(' AND ') if text else []:
        term = term.replace(' ', '')
        match = re.fullmatch(r'(\w+)(=|<>|<)(\?|\d+|\x27[^\x27]*\x27)', term)
        if not match: raise NotImplementedError('Unsupported query condition')
        field, operator, literal = match.groups()
        item = value(literal, arguments)
        if field in ID_FIELDS and item is not None: item = int(item)
        result.append((field, operator, item))
    return result


def matches(row, filters):
    for field, operator, expected in filters:
        actual = row.get(field)
        if operator == '=' and actual != expected: return False
        if operator == '<>' and actual == expected: return False
        if operator == '<' and (actual is None or actual >= expected): return False
    return True


class FirestoreDatabase:
    postgres = False
    firebase = True

    def __init__(self, config):
        self.client, _ = configured_clients(config)

    def collection(self, table):
        if table not in DEFAULTS: raise NotImplementedError('Unsupported collection')
        # Namespace avoids colliding with another application in the same project.
        return self.client.collection('sw_' + table)

    def get(self, table, id):
        if id is None: return None
        snapshot = self.collection(table).document(str(int(id))).get()
        return snapshot.to_dict() if snapshot.exists else None

    def select(self, table, filters=(), order='', limit=None):
        identity = next((v for k, op, v in filters if k == 'id' and op == '='), None)
        if identity is not None:
            row = self.get(table, identity)
            rows = [row] if row and matches(row, filters) else []
        else:
            query = self.collection(table)
            # One indexed predicate avoids requiring composite-index setup.
            # Remaining filters and display ordering apply only to these matches.
            if filters:
                field, operator, expected = filters[0]
                query = query.where(filter=FieldFilter(field, {'=':'==','<>':'!=','<':'<'}[operator], expected))
            rows = [s.to_dict() for s in query.stream()]
            rows = [row for row in rows if matches(row, filters)]
        if not order and rows and 'id' in rows[0]: order = 'id'
        for part in reversed(order.split(',') if order else []):
            field, *direction = part.strip().split()
            rows.sort(key=lambda r: r.get(field), reverse=direction == ['DESC'])
        return rows[:limit] if limit is not None else rows

    def execute(self, sql, args=()):
        sql = ' '.join(sql.split())
        arguments = iter(args)
        if ' JOIN ' in sql or '(SELECT id FROM course_photos' in sql:
            return Result(self.joined(sql, args))
        match = re.fullmatch(r'SELECT (.+?) FROM (\w+)(?: WHERE (.*?))?(?: ORDER BY (.*?))?(?: LIMIT (\d+))?', sql)
        if match:
            projection, table, where, order, limit = match.groups()
            rows = self.select(table, conditions(where, arguments), order or '', int(limit) if limit else None)
            if projection == 'COUNT(*) n': return Result([{'n': len(rows)}])
            if projection != '*': rows = [{k: row.get(k) for k in projection.split(',')} for row in rows]
            return Result(rows)
        match = re.fullmatch(r'INSERT INTO (\w+)(?:\(([^)]+)\))? VALUES\(([^)]+)\)(.*)', sql)
        if match:
            table, fields, literals, suffix = match.groups()
            if not fields:
                fields = {'attempts':'key,created','settings':'key,value','enrollments':'user_id,course_id'}.get(table)
            if not fields: raise NotImplementedError('Explicit insert columns required')
            row = {k: value(v, arguments) for k, v in zip(fields.split(','), literals.split(','), strict=True)}
            return Result(rowcount=self.insert(table, row, suffix))
        match = re.fullmatch(r'UPDATE (\w+) SET (.+?) WHERE (.+)', sql)
        if match:
            table, assignments, where = match.groups()
            updates = {}
            for assignment in assignments.split(','):
                field, literal = assignment.split('=')
                updates[field] = value(literal, arguments)
            filters = conditions(where, arguments)
            rows = self.select(table, filters)
            for row in rows: self.update(table, row, updates, filters)
            return Result(rowcount=len(rows))
        match = re.fullmatch(r'DELETE FROM (\w+)(?: WHERE (.+))?', sql)
        if match:
            table, where = match.groups()
            rows = self.select(table, conditions(where, arguments))
            for row in rows: self.collection(table).document(self.document_id(table, row)).delete()
            return Result(rowcount=len(rows))
        raise NotImplementedError('Query is not supported by the Firebase backend')

    @staticmethod
    def document_id(table, row):
        if table == 'settings': return row['key']
        if table == 'enrollments': return f"{row['user_id']}_{row['course_id']}"
        return str(row['id'])

    def email_ref(self, email):
        return self.client.collection('sw_unique_emails').document(hashlib.sha256(email.encode()).hexdigest())

    def insert(self, table, values, suffix=''):
        row = {**DEFAULTS[table], **values}
        for field in ID_FIELDS & row.keys():
            if row[field] is not None: row[field] = int(row[field])
        collection = self.collection(table)
        if table == 'attempts':
            ref = collection.document()
            ref.set({**row, 'id':ref.id})
            return 1
        if table == 'settings':
            if suffix != ' ON CONFLICT(key) DO UPDATE SET value=excluded.value':
                raise NotImplementedError('Settings require upsert')
            collection.document(row['key']).set(row)
            return 1
        if table == 'enrollments':
            if suffix != ' ON CONFLICT DO NOTHING': raise NotImplementedError('Enrollment requires upsert')
            collection.document(self.document_id(table, row)).set(row)
            return 1
        counter = self.client.collection('sw_counters').document(table)

        @firestore.transactional
        def write(transaction):
            count = counter.get(transaction=transaction).to_dict() or {}
            email_ref = self.email_ref(row['email']) if table == 'users' else None
            if email_ref and email_ref.get(transaction=transaction).exists:
                raise sqlite3.IntegrityError('E-mail já cadastrado.')
            id = count.get('value', 0) + 1
            transaction.set(counter, {'value':id})
            transaction.create(collection.document(str(id)), {**row, 'id':id})
            if email_ref: transaction.create(email_ref, {'user_id':id})
        write(self.client.transaction())
        return 1

    def update(self, table, old, updates, filters):
        updates = dict(updates)
        for field in ID_FIELDS & updates.keys():
            if updates[field] is not None: updates[field] = int(updates[field])
        ref = self.collection(table).document(self.document_id(table, old))

        @firestore.transactional
        def write(transaction):
            current = ref.get(transaction=transaction).to_dict()
            if not current or not matches(current, filters): return
            new_email = updates.get('email', current.get('email'))
            changed = table == 'users' and new_email != current['email']
            email_ref = self.email_ref(new_email) if changed else None
            if email_ref and email_ref.get(transaction=transaction).exists:
                raise sqlite3.IntegrityError('E-mail já cadastrado.')
            transaction.update(ref, updates)
            if changed:
                transaction.delete(self.email_ref(current['email']))
                transaction.create(email_ref, {'user_id':current['id']})
        write(self.client.transaction())

    def joined(self, sql, args):
        if '(SELECT id FROM course_photos' in sql:
            courses = self.select('courses', [('active','=',1),('deleted','=',0)])
            if 'title LIKE' in sql:
                needle = args[0][1:-1].lower()
                courses = [c for c in courses if needle in c['title'].lower() or needle in c['category'].lower()]
            if sql.endswith('LIMIT 3'): courses = courses[:3]
            for course in courses:
                photos = self.select('course_photos', [('course_id','=',course['id'])], 'sort_order,id', 1)
                course['photo_id'] = photos[0]['id'] if photos else None
            return courses
        if sql.startswith('SELECT 1 FROM enrollments'):
            course = self.get('courses', args[1])
            enrolled = self.collection('enrollments').document(f'{int(args[0])}_{int(args[1])}').get().exists
            return [{'1':1}] if enrolled and course and course['active'] and not course['deleted'] else []
        if sql.startswith('SELECT c.* FROM courses c JOIN enrollments'):
            items = [self.get('courses', e['course_id']) for e in self.select('enrollments', [('user_id','=',int(args[0]))])]
            return [c for c in items if c and c['active'] and not c['deleted']]
        if sql.startswith('SELECT p.*,c.active,c.deleted'):
            photo = self.get('course_photos', args[0])
            course = self.get('courses', photo['course_id']) if photo else None
            return [{**photo, 'active':course['active'], 'deleted':course['deleted']}] if course else []
        specs = {
            'SELECT p.*,c.title course_title FROM course_photos p JOIN courses c ON c.id=p.course_id WHERE c.deleted=0 ORDER BY p.course_id,p.sort_order,p.id': ('course_photos','course_title','course_id,sort_order,id'),
            'SELECT m.*,c.title course_title FROM materials m JOIN courses c ON c.id=m.course_id WHERE c.deleted=0': ('materials','course_title',''),
            'SELECT l.*,c.title FROM leads l LEFT JOIN courses c ON c.id=l.course_id ORDER BY l.id DESC': ('leads','title','id DESC'),
        }
        if sql in specs:
            table, title, order = specs[sql]
            result = []
            for row in self.select(table, order=order):
                course = self.get('courses', row['course_id'])
                if table != 'leads' and (not course or course['deleted']): continue
                result.append({**row, title: course['title'] if course else None})
            return result
        if sql == 'SELECT e.*,u.name,c.title FROM enrollments e JOIN users u ON u.id=e.user_id JOIN courses c ON c.id=e.course_id':
            result = []
            for row in self.select('enrollments'):
                user, course = self.get('users',row['user_id']), self.get('courses',row['course_id'])
                if user and course: result.append({**row, 'name':user['name'], 'title':course['title']})
            return result
        if sql == 'SELECT a.*,u.name FROM audit a LEFT JOIN users u ON u.id=a.actor ORDER BY a.id DESC LIMIT 50':
            return [{**a, 'name':(self.get('users',a['actor']) or {}).get('name')} for a in self.select('audit',order='id DESC',limit=50)]
        raise NotImplementedError('Unsupported Firebase join')

    def migrate(self, root):
        # Firestore is schemaless; verify access without creating sample records.
        self.client.collection('sw_counters').document('users').get()

    def commit(self): pass  # Every mutation above is committed atomically.
    def rollback(self): pass
    def close(self): pass  # Reuse pooled server clients across requests.
