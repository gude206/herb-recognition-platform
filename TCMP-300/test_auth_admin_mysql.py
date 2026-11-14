"""Account, history isolation, CSRF and article maintenance in a disposable MySQL schema."""
import io
import os
import secrets
import tempfile
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pymysql
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from PIL import Image

import auth_store
import admin_articles
import content_store
import history_store
from api import app

PASSWORD = 'Member-test-passphrase-42'
ADMIN_PASSWORD = 'Administrator-test-passphrase-42'


@contextmanager
def lightweight_client():
    # Cookie isolation does not require starting the real model in the temporary auth schema.
    client = TestClient(app)
    try:
        yield client
    finally:
        client.close()


class FakePredictor:
    info = {'name': 'test', 'run': 'isolated', 'epoch': 1, 'classes': 300, 'device': 'cpu'}
    def predict(self, content):
        label = dict(herb_id='tcmp-001', name='阿拉伯婆婆纳', latin_name='Veronica persica', confidence=.8)
        return dict(prediction=label, top_k=[label], model=self.info)


class AuthAdminTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        values = dotenv_values(Path(__file__).resolve().parent.parent / 'mysql-local/.admin.env')
        if not values.get('MYSQL_ROOT_PASSWORD'):
            raise unittest.SkipTest('Start project MySQL before authentication integration tests')
        cls.admin_config = dict(host='127.0.0.1', port=int(values['MYSQL_PORT']), user='root',
            password=values['MYSQL_ROOT_PASSWORD'], charset='utf8mb4', autocommit=True)
        cls.schema = 'herb_auth_test_' + uuid.uuid4().hex[:12]
        with pymysql.connect(**cls.admin_config) as database, database.cursor() as cursor:
            cursor.execute('CREATE DATABASE `' + cls.schema + '` CHARACTER SET utf8mb4')
        cls.env = patch.dict(os.environ, dict(MYSQL_ENABLED='true', MYSQL_HOST='127.0.0.1', MYSQL_PORT=values['MYSQL_PORT'],
            MYSQL_USER='root', MYSQL_PASSWORD=values['MYSQL_ROOT_PASSWORD'], MYSQL_DATABASE=cls.schema,
            AUTH_CSRF_SECRET='c' * 64, AUTH_COOKIE_SECURE='false', AUTH_ADMIN_ACCOUNT='admin'))
        cls.env.start()
        try:
            history_store.initialize_schema()
            with history_store.connection() as database:
                content_store.initialize_tables(database)
                content_store.seed_content(database, plants=[])
                auth_store.initialize_schema(database)
                admin_articles.initialize_schema(database)
                auth_store.create_user(database, 'admin', ADMIN_PASSWORD, role='admin')
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        assert cls.schema.startswith('herb_auth_test_') and cls.schema != history_store.configuration()['database']
        with pymysql.connect(**cls.admin_config) as database, database.cursor() as cursor:
            cursor.execute('DROP DATABASE `' + cls.schema + '`')

    def setUp(self):
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.username = 'member-' + uuid.uuid4().hex[:12]
        self.origin = {'Origin': 'http://localhost:5173'}
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.patch_uploads = patch.object(history_store, 'UPLOADS', Path(self.folder.name) / 'uploads')
        self.patch_uploads.start(); self.addCleanup(self.patch_uploads.stop)
        self.patch_covers = patch.object(content_store, 'ARTICLE_COVERS', Path(self.folder.name) / 'covers')
        self.patch_covers.start(); self.addCleanup(self.patch_covers.stop)
        self.predictor = patch.object(app.state, 'predictor', FakePredictor(), create=True)
        self.predictor.start(); self.addCleanup(self.predictor.stop)
        with history_store.connection() as database, database.cursor() as cursor:
            cursor.execute('UPDATE auth_attempts SET attempts=0,window_start=UTC_TIMESTAMP(3)')

    def registration(self, client=None, account=None, **extra):
        return (client or self.client).post('/api/v1/auth/register', headers=self.origin,
            json={**dict(account=account or self.username, password=PASSWORD, claim_guest_history=False), **extra})

    def csrf(self, client=None):
        data = (client or self.client).get('/api/v1/auth/me').json()
        return {**self.origin, 'X-CSRF-Token': data['csrf_token']}

    def admin_login(self):
        response = self.client.post('/api/v1/auth/login', headers=self.origin,
            json=dict(account='admin', password=ADMIN_PASSWORD, role='admin', claim_guest_history=False))
        self.assertEqual(response.status_code, 200, response.text)
        return self.csrf()

    @staticmethod
    def png():
        image = io.BytesIO(); Image.new('RGB', (64, 64), 'green').save(image, format='PNG')
        return image.getvalue()

    def test_registration_hash_session_cookie_and_duplicate_account(self):
        response = self.registration()
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['user']['role'], 'user')
        cookie = response.headers['set-cookie'].lower()
        self.assertIn('httponly', cookie); self.assertIn('samesite=lax', cookie)
        token = self.client.cookies.get(auth_store.COOKIE_NAME)
        self.assertNotIn(token, response.text); self.assertNotIn(PASSWORD, response.text)
        self.assertTrue(self.client.get('/api/v1/auth/me').json()['authenticated'])
        with history_store.connection() as database, database.cursor() as cursor:
            cursor.execute('SELECT password_hash FROM app_users WHERE account_key=%s', (self.username,))
            encoded = cursor.fetchone()['password_hash']
            self.assertTrue(encoded.startswith('$argon2id$')); self.assertNotEqual(encoded, PASSWORD)
            cursor.execute('SELECT token_hash FROM auth_sessions WHERE user_id=%s', (response.json()['user']['id'],))
            self.assertEqual(cursor.fetchone()['token_hash'], auth_store.hash_token(token))
        with lightweight_client() as fresh:
            duplicate = self.registration(fresh, account=self.username.upper())
            self.assertEqual(duplicate.status_code, 409, duplicate.text)

    def test_profile_persists_and_rejects_role_or_other_account_changes(self):
        response = self.registration(name='初始昵称')
        user = response.json()['user']
        initial = self.client.get('/api/v1/auth/me/profile')
        self.assertEqual(initial.status_code, 200, initial.text)
        self.assertEqual(initial.json()['stats'], dict(conversations=0, recognitions=0))
        self.assertEqual(initial.json()['bio'], '')
        self.assertTrue(initial.json()['created_at'].endswith('Z'))
        endpoint = '/api/v1/auth/me/profile'
        payload = dict(name='  本草爱好者  ', bio='观察植物，记录四季。')
        self.assertEqual(self.client.patch(endpoint, json=payload).status_code, 403)
        self.assertEqual(self.client.patch(endpoint, headers=self.csrf(), json={**payload, 'role': 'admin'}).status_code, 422)
        self.assertEqual(self.client.patch(endpoint, headers=self.csrf(), json={**payload, 'user_id': 'someone-else'}).status_code, 422)
        self.assertEqual(self.client.patch(endpoint, headers=self.csrf(), json={**payload, 'name': '   '}).status_code, 422)
        self.assertEqual(self.client.patch(endpoint, headers=self.csrf(), json={**payload, 'bio': '字' * 301}).status_code, 422)
        updated = self.client.patch(endpoint, headers=self.csrf(), json=payload)
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()['user']['name'], '本草爱好者')
        self.assertEqual(updated.json()['user']['role'], 'user')
        me = self.client.get('/api/v1/auth/me').json()['user']
        self.assertEqual(me['name'], '本草爱好者')
        self.assertNotIn('password_hash', str(updated.json()))
        with lightweight_client() as stranger:
            self.assertEqual(stranger.get(endpoint).status_code, 401)
            self.registration(stranger, account='other-' + uuid.uuid4().hex[:12])
            self.assertEqual(stranger.get(endpoint).json()['bio'], '')
            self.assertNotEqual(stranger.get(endpoint).json()['user']['id'], user['id'])
        self.assertEqual(self.client.get(endpoint).json()['bio'], payload['bio'])

    def test_avatar_validation_private_storage_and_restore_default(self):
        self.registration()
        endpoint = '/api/v1/auth/me/avatar'
        self.assertIsNone(self.client.get('/api/v1/auth/me').json()['user']['avatar_url'])
        self.assertEqual(self.client.put(endpoint, files={'file': ('pic.png', self.png(), 'image/png')}).status_code, 403)
        self.assertEqual(self.client.put(endpoint, headers=self.csrf(), files={'file': ('x.png', b'<svg/>', 'image/png')}).status_code, 422)
        self.assertEqual(self.client.put(endpoint, headers=self.csrf(), files={'file': ('huge.png', b'x' * (2 * 1024 * 1024 + 1), 'image/png')}).status_code, 413)
        large = io.BytesIO(); Image.new('RGB', (4097, 1), 'green').save(large, format='PNG')
        self.assertEqual(self.client.put(endpoint, headers=self.csrf(), files={'file': ('large.png', large.getvalue(), 'image/png')}).status_code, 413)
        gif = io.BytesIO(); Image.new('RGB', (32, 32), 'green').save(gif, format='GIF')
        self.assertEqual(self.client.put(endpoint, headers=self.csrf(), files={'file': ('fake.png', gif.getvalue(), 'image/png')}).status_code, 422)
        uploaded = self.client.put(endpoint, headers=self.csrf(), files={'file': ('avatar.png', self.png(), 'image/png')})
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        url = uploaded.json()['user']['avatar_url']
        self.assertEqual(self.client.get('/api/v1/auth/me').json()['user']['avatar_url'], url)
        image = self.client.get(url)
        self.assertEqual(image.status_code, 200)
        self.assertIn('no-store', image.headers['cache-control'])
        self.assertEqual(image.headers['content-type'], 'image/webp')
        with Image.open(io.BytesIO(image.content)) as decoded:
            self.assertEqual(decoded.size, (256, 256))
            self.assertFalse(decoded.getexif())
        with lightweight_client() as stranger:
            self.assertEqual(stranger.get(url).status_code, 401)
            self.registration(stranger, account='avatar-other-' + uuid.uuid4().hex[:10])
            self.assertEqual(stranger.get(url).status_code, 404)
        self.assertEqual(self.client.delete(endpoint).status_code, 403)
        self.assertEqual(self.client.delete(endpoint, headers=self.csrf()).status_code, 200)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertIsNone(self.client.get('/api/v1/auth/me').json()['user']['avatar_url'])
        again = self.client.put(endpoint, headers=self.csrf(), files={'file': ('new.png', self.png(), 'image/png')})
        self.assertNotEqual(again.json()['user']['avatar_url'], url)

    def test_personal_history_search_counts_pagination_and_account_isolation(self):
        self.registration()
        token = self.client.cookies.get(auth_store.COOKIE_NAME)
        owner = auth_store.session_user(token)['history_owner_hash']
        now = history_store.timestamp(history_store.now())
        rows = [dict(id='profile-' + uuid.uuid4().hex, context={}, createdAt=now, updatedAt=now,
                     messages=[dict(role='user', content=f'第 {index} 次认识植物'),
                               dict(role='assistant', content='紫苏的形态特征' if index == 0 else '观察叶片形态')]) for index in range(10)]
        history_store.import_conversations(owner, rows)
        self.assertEqual(self.client.get('/api/v1/auth/me/profile').json()['stats']['conversations'], 10)
        first = self.client.get('/api/v1/history/conversations?page_size=8').json()
        second = self.client.get('/api/v1/history/conversations?page_size=8&page=2').json()
        self.assertEqual(first['total'], 10)
        self.assertEqual(len(first['items']), 8); self.assertEqual(len(second['items']), 2)
        matches = self.client.get('/api/v1/history/conversations', params={'q': '紫苏'}).json()
        self.assertEqual(matches['total'], 1)
        self.assertEqual(matches['items'][0]['messages'][1]['content'], '紫苏的形态特征')
        self.assertEqual(self.client.get('/api/v1/history/conversations', params={'q': '%'}).json()['total'], 0)
        image = self.client.post('/api/v1/predict', headers=self.csrf(), files={'file': ('plant.png', self.png(), 'image/png')})
        self.assertEqual(image.status_code, 200, image.text)
        self.assertEqual(self.client.get('/api/v1/auth/me/profile').json()['stats']['recognitions'], 1)
        self.assertEqual(self.client.get('/api/v1/history/recognitions').json()['total'], 1)
        with lightweight_client() as stranger:
            self.registration(stranger, account='history-other-' + uuid.uuid4().hex[:10])
            self.assertEqual(stranger.get('/api/v1/auth/me/profile').json()['stats'], dict(conversations=0, recognitions=0))
            self.assertEqual(stranger.get('/api/v1/history/conversations', params={'q': '紫苏'}).json()['total'], 0)
            self.assertEqual(stranger.get('/api/v1/history/recognitions').json()['total'], 0)

    def test_public_registration_cannot_create_admin_or_echo_password(self):
        response = self.registration(role='admin')
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(PASSWORD, response.text)
        self.assertEqual(self.registration(account='ADMIN').status_code, 409)
        short = self.registration(password='short-key')
        self.assertEqual(short.status_code, 422)
        self.assertNotIn('short-key', short.text)

    def test_admin_and_user_login_entries_validate_server_role(self):
        self.registration()
        with lightweight_client() as fresh:
            wrong = fresh.post('/api/v1/auth/login', headers=self.origin,
                json=dict(account=self.username, password=PASSWORD, role='admin', claim_guest_history=False))
            self.assertEqual(wrong.status_code, 403)
            self.assertFalse(fresh.get('/api/v1/auth/me').json()['authenticated'])
            right = fresh.post('/api/v1/auth/login', headers=self.origin,
                json=dict(account=self.username, password=PASSWORD, role='user', remember=True, claim_guest_history=False))
            self.assertEqual(right.status_code, 200)
            self.assertIn('Max-Age=2592000', right.headers['set-cookie'])

    def test_csrf_origin_logout_and_revoked_session(self):
        self.registration(); token = self.client.cookies.get(auth_store.COOKIE_NAME)
        self.assertEqual(self.client.post('/api/v1/auth/logout').status_code, 403)
        self.assertEqual(self.client.post('/api/v1/auth/logout', headers={**self.csrf(), 'Origin':'https://evil.invalid'}).status_code, 403)
        self.assertEqual(self.client.post('/api/v1/auth/logout', headers={**self.origin,'X-CSRF-Token':'invalid'}).status_code, 403)
        self.assertEqual(self.client.post('/api/v1/auth/logout', headers=self.csrf()).status_code, 200)
        self.assertFalse(self.client.get('/api/v1/auth/me').json()['authenticated'])
        with lightweight_client() as copied:
            copied.cookies.set(auth_store.COOKIE_NAME, token)
            self.assertFalse(copied.get('/api/v1/auth/me').json()['authenticated'])

    def test_failed_login_throttling_and_request_body_bound(self):
        self.registration()
        with lightweight_client() as fresh:
            for _ in range(5):
                response = fresh.post('/api/v1/auth/login', headers=self.origin,
                    json=dict(account=self.username, password='wrong password', role='user', claim_guest_history=False))
                self.assertEqual(response.status_code, 401)
            self.assertEqual(fresh.post('/api/v1/auth/login', headers=self.origin,
                json=dict(account=self.username, password=PASSWORD, role='user', claim_guest_history=False)).status_code, 429)
        self.assertEqual(self.client.post('/api/v1/auth/register', content=b'x' * 70000,
            headers={'Content-Type':'application/json'}).status_code, 413)

    def test_visitor_claim_moves_chat_and_recognition_to_account_and_blocks_old_token(self):
        visitor = secrets.token_hex(32); header = {'X-History-Token': visitor}
        owner = history_store.owner_hash(visitor); conversation = str(uuid.uuid4())
        with history_store.chat_lease(owner, conversation, {}) as lease:
            lease.save('访客问题', '访客回答', 'test', [])
        image = self.client.post('/api/v1/predict', headers=header, files={'file':('plant.png',self.png(),'image/png')})
        self.assertEqual(image.status_code, 200, image.text)
        registered = self.client.post('/api/v1/auth/register', headers={**self.origin,**header},
            json=dict(account=self.username,password=PASSWORD,claim_guest_history=True))
        self.assertEqual(registered.status_code, 201, registered.text)
        self.assertEqual(registered.json()['claimed']['conversations'], 1)
        self.assertEqual(registered.json()['claimed']['recognitions'], 1)
        self.assertEqual(self.client.get('/api/v1/history/conversations').json()['total'], 1)
        self.assertEqual(self.client.get('/api/v1/history/recognitions').json()['total'], 1)
        with lightweight_client() as fresh:
            self.assertEqual(fresh.get('/api/v1/history/conversations',headers=header).status_code, 401)
            login = fresh.post('/api/v1/auth/login', headers=self.origin,
                json=dict(account=self.username,password=PASSWORD,role='user',claim_guest_history=False))
            self.assertEqual(login.status_code, 200)
            self.assertEqual(fresh.get('/api/v1/history/conversations').json()['items'][0]['messages'][0]['content'], '访客问题')
            self.assertEqual(fresh.get('/api/v1/history/recognitions/'+image.json()['result']['record_id']+'/image').content, self.png())

    def test_other_account_cannot_claim_bound_history_or_use_its_ids(self):
        visitor = secrets.token_hex(32); owner = history_store.owner_hash(visitor); conversation = str(uuid.uuid4())
        with history_store.chat_lease(owner, conversation, {}) as lease:
            lease.save('私有问题', '私有回答', 'test', [])
        first = self.client.post('/api/v1/auth/register', headers={**self.origin,'X-History-Token':visitor},
            json=dict(account=self.username,password=PASSWORD,claim_guest_history=True))
        self.assertEqual(first.status_code, 201)
        with lightweight_client() as other:
            registered = other.post('/api/v1/auth/register', headers={**self.origin,'X-History-Token':visitor},
                json=dict(account='other-'+uuid.uuid4().hex[:12],password=PASSWORD,claim_guest_history=True))
            self.assertEqual(registered.status_code, 201)
            self.assertFalse(registered.json()['claimed']['claimed'])
            self.assertEqual(other.get('/api/v1/history/conversations').json()['total'], 0)
            denied = other.post('/api/v1/history/conversations', headers=self.csrf(other), json=dict(id=conversation,context={}))
            self.assertEqual(denied.status_code, 404)

    def test_history_claim_during_pending_answer_is_atomic_and_retryable(self):
        visitor = secrets.token_hex(32); conversation = str(uuid.uuid4())
        with history_store.chat_lease(history_store.owner_hash(visitor), conversation, {}):
            response = self.client.post('/api/v1/auth/register', headers={**self.origin,'X-History-Token':visitor},
                json=dict(account=self.username,password=PASSWORD,claim_guest_history=True))
            self.assertEqual(response.status_code, 409, response.text)
        retry = self.client.post('/api/v1/auth/register', headers={**self.origin,'X-History-Token':visitor},
            json=dict(account=self.username,password=PASSWORD,claim_guest_history=True))
        self.assertEqual(retry.status_code, 201, retry.text)

    def test_administrator_permissions_are_not_controlled_by_client_role_headers(self):
        self.assertEqual(self.client.get('/api/v1/admin/articles').status_code, 401)
        self.registration()
        self.assertEqual(self.client.get('/api/v1/admin/articles', headers={'X-Role':'admin'}).status_code, 403)
        denied = self.client.post('/api/v1/admin/articles', headers=self.csrf(), json=dict(title='越权',category='植物知识',body='文本'))
        self.assertEqual(denied.status_code, 403)

    def test_admin_article_create_publish_conflict_cover_delete_restore_audit(self):
        headers = self.admin_login()
        form = dict(title='临时维护测试',category='植物知识',excerpt='摘要',body='正文',status='draft',sourceKind='editorial',sourceNote='测试来源')
        self.assertEqual(self.client.post('/api/v1/admin/articles',json=form).status_code, 403)
        created = self.client.post('/api/v1/admin/articles',headers=headers,json=form)
        self.assertEqual(created.status_code, 201, created.text)
        article = created.json(); article_id = article['id']
        self.assertEqual(self.client.get('/api/v1/articles/'+article_id).status_code, 404)
        updated = self.client.put('/api/v1/admin/articles/'+article_id,headers=headers,
            json={**form,'body':'已修改正文','status':'published','reviewStatus':'已审核','sourceNote':'https://www.iplant.cn/','expectedVersion':article['version']})
        self.assertEqual(updated.status_code, 200, updated.text); article = updated.json()
        self.assertEqual(self.client.get('/api/v1/articles/'+article_id).json()['body'], '已修改正文')
        conflict = self.client.put('/api/v1/admin/articles/'+article_id,headers=headers,json={**form,'expectedVersion':1})
        self.assertEqual(conflict.status_code, 409)
        cover = self.client.post('/api/v1/admin/articles/'+article_id+'/cover',headers=headers,
            params={'expectedVersion':article['version']},files={'file':('cover.png',self.png(),'image/png')})
        self.assertEqual(cover.status_code, 200, cover.text); article = cover.json()
        self.assertEqual(self.client.get(article['image']).status_code, 200)
        removed = self.client.request('DELETE','/api/v1/admin/articles/'+article_id,headers=headers,json={'expectedVersion':article['version']})
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(self.client.get('/api/v1/articles/'+article_id).status_code, 404)
        deleted = self.client.get('/api/v1/admin/articles/'+article_id).json()
        restored = self.client.post('/api/v1/admin/articles/'+article_id+'/restore',headers=headers,json={'expectedVersion':deleted['version']})
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.json()['status'], 'draft')
        self.assertEqual(self.client.get('/api/v1/articles/'+article_id).status_code, 404)
        with history_store.connection() as database,database.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) AS n FROM article_audit_log WHERE article_id=%s',(article_id,))
            self.assertEqual(cursor.fetchone()['n'], 5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
