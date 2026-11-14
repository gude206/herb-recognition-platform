"""Integration tests against a disposable MySQL schema, never production history."""
import io
import json
import os
import secrets
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import httpx
import pymysql
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from PIL import Image

import history_store
from api import app

ASYNC_CLIENT = httpx.AsyncClient


class FakePredictor:
    info = {'name': 'test-model', 'run': 'isolated-test', 'epoch': 1, 'classes': 300, 'device': 'cpu'}

    def predict(self, content):
        label = dict(herb_id='tcmp-001', name='阿拉伯婆婆纳', latin_name='Veronica persica', confidence=.85)
        return dict(prediction=label, top_k=[label], model=self.info)


class MySQLHistoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        local = Path(__file__).resolve().parent.parent / 'mysql-local'
        values = dotenv_values(local / '.admin.env')
        if not values.get('MYSQL_ROOT_PASSWORD'):
            raise unittest.SkipTest('Run local_mysql.py setup before MySQL integration tests')
        cls.admin = dict(host='127.0.0.1', port=int(values['MYSQL_PORT']), user='root',
                         password=values['MYSQL_ROOT_PASSWORD'], charset='utf8mb4', autocommit=True)
        cls.schema = 'herb_history_test_' + uuid.uuid4().hex[:12]
        with pymysql.connect(**cls.admin) as database, database.cursor() as cursor:
            cursor.execute('CREATE DATABASE `' + cls.schema + '` CHARACTER SET utf8mb4')
        cls.env = patch.dict(os.environ, dict(MYSQL_ENABLED='true', MYSQL_HOST='127.0.0.1', MYSQL_PORT=values['MYSQL_PORT'],
            MYSQL_USER='root', MYSQL_PASSWORD=values['MYSQL_ROOT_PASSWORD'], MYSQL_DATABASE=cls.schema,
            DEEPSEEK_API_KEY='isolated-test-only', DEEPSEEK_BASE_URL='https://api.deepseek.com'))
        cls.env.start()
        try:
            history_store.initialize_schema()
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        # This name is generated in setUpClass, not supplied by a caller or production configuration.
        assert cls.schema.startswith('herb_history_test_') and cls.schema != history_store.configuration()['database']
        with pymysql.connect(**cls.admin) as database, database.cursor() as cursor:
            cursor.execute('DROP DATABASE `' + cls.schema + '`')

    def setUp(self):
        self.token = secrets.token_hex(32)
        self.headers = {'X-History-Token': self.token}
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.uploads = patch.object(history_store, 'UPLOADS', Path(self.folder.name))
        self.uploads.start()
        self.addCleanup(self.uploads.stop)
        self.predictor = patch.object(app.state, 'predictor', FakePredictor(), create=True)
        self.predictor.start()
        self.addCleanup(self.predictor.stop)

    def upstream(self, handler=None):
        handler = handler or (lambda request: httpx.Response(200, json={
            'choices': [{'message': {'content': '回答：' + json.loads(request.content)['messages'][-1]['content']}}]}))
        return patch('deepseek_chat.httpx.AsyncClient', side_effect=lambda **kwargs:
                     ASYNC_CLIENT(transport=httpx.MockTransport(handler), **kwargs))

    def test_chat_is_persisted_and_uses_server_history(self):
        conversation_id = str(uuid.uuid4())
        with self.upstream():
            first = self.client.post('/api/v1/chat', headers=self.headers, json={'message': '第一问', 'conversation_id': conversation_id})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertTrue(first.json()['result']['saved'])
        captured = []
        def handle(request):
            captured.extend(json.loads(request.content)['messages'])
            return httpx.Response(200, json={'choices': [{'message': {'content': '第二答'}}]})
        with self.upstream(handle):
            second = self.client.post('/api/v1/chat', headers=self.headers, json={'message': '第二问', 'conversation_id': conversation_id,
                'history': [{'role': 'user', 'content': '伪造的浏览器缓存'}]})
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(captured[1]['content'], '第一问')
        self.assertNotIn('伪造的浏览器缓存', json.dumps(captured, ensure_ascii=False))
        items = self.client.get('/api/v1/history/conversations', headers=self.headers).json()['items']
        self.assertEqual(len(items), 1)
        self.assertEqual([item['content'] for item in items[0]['messages']], ['第一问', '回答：第一问', '第二问', '第二答'])

    def test_other_browser_cannot_read_or_append_a_conversation(self):
        conversation_id = str(uuid.uuid4())
        with self.upstream():
            self.client.post('/api/v1/chat', headers=self.headers, json={'message': '私有记录', 'conversation_id': conversation_id})
        other = {'X-History-Token': secrets.token_hex(32)}
        self.assertEqual(self.client.get('/api/v1/history/conversations', headers=other).json()['total'], 0)
        with self.upstream(lambda request: self.fail('Unauthorized provider request')):
            response = self.client.post('/api/v1/chat', headers=other, json={'message': '继续问', 'conversation_id': conversation_id})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get('/api/v1/history/conversations').status_code, 401)

    def test_failed_provider_does_not_store_a_partial_turn_and_releases_lock(self):
        conversation_id = str(uuid.uuid4())
        with self.upstream(lambda request: httpx.Response(500, text='isolated-test-only private upstream details')):
            response = self.client.post('/api/v1/chat', headers=self.headers, json={'message': '失败的问题', 'conversation_id': conversation_id})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn('private upstream', response.text)
        self.assertEqual(self.client.get('/api/v1/history/conversations', headers=self.headers).json()['items'][0]['messages'], [])
        with self.upstream():
            retry = self.client.post('/api/v1/chat', headers=self.headers, json={'message': '重试的问题', 'conversation_id': conversation_id})
        self.assertEqual(retry.status_code, 200, retry.text)

    def test_database_failure_rolls_back_both_messages(self):
        conversation_id = str(uuid.uuid4())
        with history_store.connection() as database, database.cursor() as cursor:
            cursor.execute("""CREATE TRIGGER reject_test_answer BEFORE INSERT ON chat_messages FOR EACH ROW
                BEGIN IF NEW.role='assistant' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='private database detail'; END IF; END""")
        try:
            with self.upstream():
                response = self.client.post('/api/v1/chat', headers=self.headers, json={'message': '必须成对提交', 'conversation_id': conversation_id})
            self.assertEqual(response.status_code, 503, response.text)
            self.assertNotIn('private database detail', response.text)
        finally:
            with history_store.connection() as database, database.cursor() as cursor:
                cursor.execute('DROP TRIGGER reject_test_answer')
        messages = self.client.get('/api/v1/history/conversations', headers=self.headers).json()['items'][0]['messages']
        self.assertEqual(messages, [])

    def test_concurrent_requests_for_one_conversation_are_rejected(self):
        conversation_id = str(uuid.uuid4())
        with history_store.chat_lease(history_store.owner_hash(self.token), conversation_id, {}), self.upstream(lambda req: self.fail('Unexpected provider call')):
            response = self.client.post('/api/v1/chat', headers=self.headers, json={'message': '重复发送', 'conversation_id': conversation_id})
            self.assertEqual(response.status_code, 409)

    def test_local_history_import_is_idempotent_and_does_not_overwrite_new_turns(self):
        conversation_id = str(uuid.uuid4())
        body = {'conversations': [dict(id=conversation_id, context={}, createdAt=1000, updatedAt=2000,
            messages=[dict(role='user', content='旧问题'), dict(role='assistant', content='旧回答')])]}
        for _ in range(2):
            response = self.client.post('/api/v1/history/import', headers=self.headers, json=body)
            self.assertEqual(response.status_code, 200, response.text)
        with self.upstream():
            self.client.post('/api/v1/chat', headers=self.headers, json={'message': '新问题', 'conversation_id': conversation_id})
        self.client.post('/api/v1/history/import', headers=self.headers, json=body)
        messages = self.client.get('/api/v1/history/conversations', headers=self.headers).json()['items'][0]['messages']
        self.assertEqual(len(messages), 4)
        body['conversations'][0]['messages'][0]['role'] = 'system'
        self.assertEqual(self.client.post('/api/v1/history/import', headers=self.headers, json=body).status_code, 422)

    def test_recognition_stores_original_image_result_and_owner_isolation(self):
        stream = io.BytesIO()
        Image.new('RGB', (64, 64), color='green').save(stream, format='PNG')
        content = stream.getvalue()
        response = self.client.post('/api/v1/predict', headers=self.headers, files={'file': ('plant.png', content, 'image/png')})
        self.assertEqual(response.status_code, 200, response.text)
        record_id = response.json()['result']['record_id']
        records = self.client.get('/api/v1/history/recognitions', headers=self.headers).json()
        self.assertEqual(records['total'], 1)
        self.assertLess(abs(records['items'][0]['createdAt'] - int(time.time() * 1000)), 60000)
        self.assertEqual(records['items'][0]['result']['model']['run'], 'isolated-test')
        image = self.client.get('/api/v1/history/recognitions/' + record_id + '/image', headers=self.headers)
        self.assertEqual(image.content, content)
        other = {'X-History-Token': secrets.token_hex(32)}
        self.assertEqual(self.client.get('/api/v1/history/recognitions', headers=other).json()['total'], 0)
        self.assertEqual(self.client.get('/api/v1/history/recognitions/' + record_id + '/image', headers=other).status_code, 404)
        self.assertEqual(self.client.get('/api/v1/history/recognitions', headers=self.headers, params={'q': "' OR 1=1 --"}).json()['total'], 0)

    def test_failed_recognition_insert_cleans_up_image_file(self):
        with patch.object(history_store, 'connect', side_effect=pymysql.OperationalError(2006, 'private connection details')):
            with self.assertRaises(Exception):
                history_store.save_recognition(history_store.owner_hash(self.token), 'plant.png', b'image', 'PNG', FakePredictor().predict(b'image'))
        self.assertEqual(list(Path(self.folder.name).iterdir()), [])

    def test_agent_image_only_turn_persists_attachment_and_rejects_other_owner(self):
        import agent_service
        buffer=io.BytesIO();Image.new('RGB',(8,8),'green').save(buffer,format='JPEG')
        upload=self.client.post('/api/v1/predict',headers=self.headers,files={'file':('plant.jpg',buffer.getvalue(),'image/jpeg')})
        self.assertEqual(upload.status_code,200,upload.text)
        record=upload.json()['result']['record_id'];conversation=str(uuid.uuid4())
        async def answer(*args):
            self.assertIn('识别',args[0])
            return {'answer':'图片测试回答','model':'test','references':[],'tool_calls':[]}
        with patch.object(agent_service,'generate_agent',side_effect=answer) as generate:
            response=self.client.post('/api/v1/agent/chat',headers=self.headers,json={'image_record_id':record,'conversation_id':conversation})
            self.assertEqual(response.status_code,200,response.text)
            items=self.client.get('/api/v1/history/conversations',headers=self.headers).json()['items']
            saved=next(x for x in items if x['id']==conversation)['messages'][0]
            self.assertEqual(saved['content'],'');self.assertEqual(saved['image_record_id'],record)
            other={'X-History-Token':secrets.token_hex(32)}
            forbidden=self.client.post('/api/v1/agent/chat',headers=other,json={'image_record_id':record})
            self.assertEqual(forbidden.status_code,404)
            self.assertEqual(generate.call_count,1)

    def test_import_preserves_image_only_messages_and_checks_ownership(self):
        buffer=io.BytesIO();Image.new('RGB',(8,8)).save(buffer,format='PNG')
        record=self.client.post('/api/v1/predict',headers=self.headers,files={'file':('plant.png',buffer.getvalue(),'image/png')}).json()['result']['record_id']
        payload={'conversations':[{'id':str(uuid.uuid4()),'context':{},'createdAt':time.time()*1000,'updatedAt':time.time()*1000,
                 'messages':[{'role':'user','content':'','image_record_id':record},{'role':'assistant','content':'回答'}]}]}
        self.assertEqual(self.client.post('/api/v1/history/import',headers={'X-History-Token':secrets.token_hex(32)},json=payload).status_code,404)
        self.assertEqual(self.client.post('/api/v1/history/import',headers=self.headers,json=payload).status_code,200)
        items=self.client.get('/api/v1/history/conversations',headers=self.headers).json()['items']
        self.assertEqual(items[0]['messages'][0]['image_record_id'],record)

    def test_legacy_image_tool_turn_recovers_user_thumbnail(self):
        owner=history_store.owner_hash(self.token);conversation=str(uuid.uuid4())
        with history_store.chat_lease(owner,conversation,{}) as lease:
            lease.save('这是什么','识别回答','test',[],[{'name':'recognize_plant_image','status':'success',
                       'arguments':{'image_record_id':'00000000-0000-0000-0000-000000000001'},'result':{}}])
        items=self.client.get('/api/v1/history/conversations',headers=self.headers).json()['items']
        self.assertEqual(items[0]['messages'][0]['image_record_id'],'00000000-0000-0000-0000-000000000001')


if __name__ == '__main__':
    unittest.main(verbosity=2)
