"""Real MySQL tests in an isolated schema; do not modify production content."""
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import pymysql
from dotenv import dotenv_values
from fastapi.testclient import TestClient

import content_store
import herb_catalog
import history_store
from api import app
from deepseek_chat import plant_context


class MySQLContentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        values = dotenv_values(Path(__file__).resolve().parent.parent / 'mysql-local/.admin.env')
        if not values.get('MYSQL_ROOT_PASSWORD'):
            raise unittest.SkipTest('Start the project MySQL before running content tests')
        cls.admin = dict(host='127.0.0.1', port=int(values['MYSQL_PORT']), user='root',
            password=values['MYSQL_ROOT_PASSWORD'], charset='utf8mb4', autocommit=True)
        cls.schema = 'herb_content_test_' + uuid.uuid4().hex[:12]
        with pymysql.connect(**cls.admin) as database, database.cursor() as cursor:
            cursor.execute('CREATE DATABASE `' + cls.schema + '` CHARACTER SET utf8mb4')
        cls.env = patch.dict(os.environ, dict(MYSQL_ENABLED='true', MYSQL_HOST='127.0.0.1',
            MYSQL_PORT=values['MYSQL_PORT'], MYSQL_USER='root', MYSQL_PASSWORD=values['MYSQL_ROOT_PASSWORD'], MYSQL_DATABASE=cls.schema))
        cls.env.start()
        cls.plants = {row['植物ID']: row for row in content_store.source_plants()}
        cls.articles = {article['id']: {**article, 'review_status':'已审核', 'source_kind':'editorial', 'source_note':'测试来源 https://www.iplant.cn/'} for article in content_store.source_articles()}
        try:
            history_store.initialize_schema()
            with history_store.connection() as database:
                content_store.initialize_tables(database)
                content_store.seed_content(database, articles=list(cls.articles.values()))
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        content_store.clear_cache()
        assert cls.schema.startswith('herb_content_test_') and cls.schema != history_store.configuration()['database']
        with pymysql.connect(**cls.admin) as database, database.cursor() as cursor:
            cursor.execute('DROP DATABASE `' + cls.schema + '`')

    def setUp(self):
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        content_store.clear_cache()

    def update(self, statement, arguments=()):
        with history_store.connection() as database, database.cursor() as cursor:
            cursor.execute(statement, arguments)
        content_store.clear_cache()

    def test_all_original_plant_fields_are_preserved(self):
        with history_store.connection() as database, database.cursor() as cursor:
            cursor.execute('SELECT id,class_id,source_payload FROM plant_catalog ORDER BY class_id')
            records = cursor.fetchall()
        self.assertEqual(len(records), 300)
        for record in records:
            self.assertEqual(json.loads(record['source_payload']), self.plants[record['id']])
            self.assertEqual(record['class_id'], int(self.plants[record['id']]['No']))
        self.assertEqual(content_store.health()['plants'], 300)

    def test_atlas_routes_work_without_csv_and_preserve_identity_warnings(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(herb_catalog, 'CSV_PATH', Path(folder) / 'missing.csv'), \
                patch.object(content_store, 'PLANT_SOURCE', Path(folder) / 'missing.csv'):
            ids = []
            for page in range(1, 14):
                response = self.client.get('/api/v1/herbs', params={'page': page})
                self.assertEqual(response.status_code, 200, response.text)
                ids.extend(row['id'] for row in response.json()['items'])
            self.assertEqual(ids, [f'tcmp-{number:03d}' for number in range(1, 301) if number != 51])
            detail = self.client.get('/api/v1/herbs/tcmp-004').json()
            self.assertEqual(detail['distribution'], herb_catalog.serialize(self.plants['tcmp-004'])['distribution'])
            self.assertEqual(detail['materials'], [])
            self.assertTrue(detail['sources'])
            self.assertEqual(self.client.get('/api/v1/herbs/tcmp-051').status_code, 404)
            filters = self.client.get('/api/v1/herbs/filters').json()
            self.assertEqual(filters['distributionCount'], 278)

    def test_database_edits_reach_detail_and_ai_context(self):
        original = self.plants['tcmp-003']
        changed = {**original}
        evidence = json.loads(original['字段证据JSON'])
        current = json.loads(original['字段来源JSON'])
        for item in evidence:
            if item['evidence_id'] in current.get('规范中文名', []): item['value'] = '数据库测试植物'
            if item['evidence_id'] in current.get('生长形态', []): item['value'] = '这是数据库中的修改内容。'
        changed['字段证据JSON'] = json.dumps(evidence, ensure_ascii=False)
        try:
            self.update('UPDATE plant_catalog SET source_payload=%s WHERE id=%s', (json.dumps(changed, ensure_ascii=False), 'tcmp-003'))
            response = self.client.get('/api/v1/herbs/tcmp-003')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['name'], '数据库测试植物')
            self.assertEqual(plant_context('tcmp-003')['description'], '这是数据库中的修改内容。')
            self.assertNotEqual(original['简短介绍'], '这是数据库中的修改内容。')
        finally:
            self.update('UPDATE plant_catalog SET source_payload=%s WHERE id=%s', (json.dumps(original, ensure_ascii=False), 'tcmp-003'))

    def test_articles_are_loaded_from_mysql_and_demo_metrics_are_not_real_counts(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(content_store, 'ARTICLE_SOURCE', Path(folder) / 'missing.json'):
            response = self.client.get('/api/v1/articles')
            self.assertEqual(response.status_code, 200, response.text)
            items = response.json()
            self.assertEqual(len(items), 7)
            self.assertTrue(all(item['storageSource'] == 'mysql' and item['readCount'] == 0 for item in items))
            self.assertTrue(all(item['sourceKind'] == 'editorial' and item['reviewStatus'] == '已审核' for item in items))
            detail = self.client.get('/api/v1/articles/a1').json()
            self.assertEqual(detail['body'], self.articles['a1']['body'])
            self.assertNotEqual(detail['reads'], self.articles['a1']['legacy_read_label'])
            cover = self.client.get(detail['image'])
            self.assertEqual(cover.status_code, 200)
            self.assertIn('image/svg+xml', cover.headers['content-type'])
        self.assertEqual(self.client.get('/api/v1/articles/unknown').status_code, 404)

    def test_article_search_and_unpublished_content(self):
        self.assertEqual(len(self.client.get('/api/v1/articles', params={'category': '草药背景'}).json()), 2)
        self.assertEqual([article['id'] for article in self.client.get('/api/v1/articles', params={'q': '金银花'}).json()], ['a1'])
        self.assertEqual(self.client.get('/api/v1/articles', params={'q': "' OR 1=1 --"}).json(), [])
        self.assertEqual(self.client.get('/api/v1/articles', params={'q': 'x' * 201}).status_code, 422)
        try:
            self.update("UPDATE science_articles SET status='draft' WHERE id='a6'")
            self.assertEqual(self.client.get('/api/v1/articles/a6').status_code, 404)
            self.assertEqual(self.client.get('/api/v1/articles/a6/cover').status_code, 404)
            self.assertEqual(len(self.client.get('/api/v1/articles').json()), 6)
        finally:
            self.update("UPDATE science_articles SET status='published' WHERE id='a6'")

    def test_seeding_is_idempotent_and_preserves_edited_content(self):
        try:
            self.update('UPDATE science_articles SET body=%s WHERE id=%s', ('数据库编辑后的正文', 'a2'))
            with history_store.connection() as database:
                report = content_store.seed_content(database)
            self.assertEqual(report['inserted_plants'], 0)
            self.assertEqual(report['inserted_articles'], 0)
            self.assertEqual(self.client.get('/api/v1/articles/a2').json()['body'], '数据库编辑后的正文')
            with history_store.connection() as database, database.cursor() as cursor:
                cursor.execute('SELECT COUNT(*) AS n FROM chat_messages')
                self.assertEqual(cursor.fetchone()['n'], 0)
        finally:
            self.update('UPDATE science_articles SET body=%s WHERE id=%s', (self.articles['a2']['body'], 'a2'))

    def test_incomplete_database_fails_explicitly_instead_of_using_csv(self):
        try:
            self.update("DELETE FROM plant_catalog WHERE id='tcmp-300'")
            self.assertEqual(content_store.health()['status'], 'unavailable')
            response = self.client.get('/api/v1/herbs')
            self.assertEqual(response.status_code, 503)
            self.assertIn('300', response.json()['detail'])
        finally:
            with history_store.connection() as database:
                content_store.seed_content(database)
            content_store.clear_cache()

    def test_z_editorial_publications_are_persisted_and_reimport_preserves_database_edits(self):
        import curated_content
        with history_store.connection() as database:
            content_store.seed_content(database)
        original=curated_content.plant('tcmp-298')
        self.assertEqual(len(curated_content.publications()[0]),20)
        self.assertEqual(len(curated_content.publications()[1]),25)
        self.assertTrue(all(row['imageCredit'] for row in self.client.get('/api/v1/articles').json() if row['id'].startswith('editorial-')))
        changed={**original,'description':'这是数据库中维护的植物公开介绍。'}
        try:
            self.update('UPDATE plant_publications SET publication_payload=%s WHERE plant_id=%s',
                (json.dumps(changed,ensure_ascii=False),'tcmp-298'))
            self.assertEqual(self.client.get('/api/v1/herbs/tcmp-298').json()['description'],changed['description'])
            with history_store.connection() as database:
                report=content_store.seed_content(database)
            self.assertEqual(report['inserted_publications'],0)
            self.assertEqual(report['inserted_editorial_articles'],0)
            self.assertEqual(self.client.get('/api/v1/herbs/tcmp-298').json()['description'],changed['description'])
        finally:
            self.update('UPDATE plant_publications SET publication_payload=%s WHERE plant_id=%s',
                (json.dumps(original,ensure_ascii=False),'tcmp-298'))

    def test_missing_database_and_unsafe_cover_do_not_leak_or_read_files(self):
        with patch.object(history_store, 'connect', side_effect=pymysql.OperationalError(2006, 'private connection password')):
            response = self.client.get('/api/v1/articles')
            self.assertEqual(response.status_code, 503)
            self.assertNotIn('private connection password', response.text)
        try:
            self.update("UPDATE science_articles SET cover_path='../../.env' WHERE id='a1'")
            self.assertEqual(self.client.get('/api/v1/articles/a1/cover').status_code, 404)
        finally:
            self.update('UPDATE science_articles SET cover_path=%s WHERE id=%s', (self.articles['a1']['cover_path'], 'a1'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
