"""Source-backed public projection and release boundaries, without network calls."""
import copy
import json
import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
import content_store
import herb_catalog
import publication_policy as policy
from admin_articles import ArticleInput
from api import app
from deepseek_chat import plant_context


class PublicationPolicyTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, MYSQL_ENABLED='false')
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_raw_mapping_is_preserved_but_conflicted_record_is_not_public(self):
        self.assertEqual(len(herb_catalog.rows()), 300)
        result = herb_catalog.list_herbs(page_size=60)
        self.assertEqual(result['collectionTotal'], 299)
        self.assertEqual(self.client.get('/api/v1/herbs/tcmp-051').status_code, 404)
        with self.assertRaises(HTTPException):
            plant_context('tcmp-051')
        self.assertIn('冲突', herb_catalog.rows()['tcmp-051']['身份核对状态'])

    def test_public_details_and_ai_do_not_expose_pending_medical_or_image_content(self):
        for row in herb_catalog.rows().values():
            value = herb_catalog.serialize(row, True)
            if value is None:
                continue
            self.assertTrue(value['sources'])
            self.assertFalse(policy.UNRESOLVED.search(json.dumps(value, ensure_ascii=False)))
            for field in ('materials', 'effects', 'medicinalPart', 'traditionalUses', 'precautions'):
                self.assertEqual(value[field], [])
            if value['image']:
                self.assertTrue(value['curated'])
                self.assertTrue(value['imageCredit']['author'])
                self.assertTrue(policy.public_url(value['imageCredit']['licenseUrl']))
                self.assertIn('creativecommons.org/',value['imageCredit']['licenseUrl'])
            for field in ('toxicity', 'confusion', 'differences', 'notes'):
                self.assertEqual(value[field], '')
        context = plant_context('tcmp-004')
        self.assertEqual(context['traditionalUses'], [])
        self.assertEqual(context['toxicity'], '')
        self.assertEqual(self.client.get('/api/v1/herbs/tcmp-004/reference-image').status_code, 404)

    def test_only_current_evidence_is_used_unsourced_edits_do_not_become_facts(self):
        original = herb_catalog.rows()['tcmp-004']
        changed = copy.deepcopy(original)
        changed['生长形态'] = '没有来源的断言'
        changed['简短介绍'] = '内容待核实'
        detail = herb_catalog.serialize(changed, True)
        self.assertNotIn('没有来源的断言', json.dumps(detail, ensure_ascii=False))
        self.assertNotIn('内容待核实', json.dumps(detail, ensure_ascii=False))
        mapping = json.loads(changed['字段来源JSON'])
        mapping['生长形态'] = ['不存在的证据']
        changed['字段来源JSON'] = json.dumps(mapping)
        self.assertEqual(herb_catalog.serialize(changed)['growthForm'], '')

    def test_seed_articles_are_archived_and_cannot_be_read_even_by_id_or_cover(self):
        self.assertEqual(len(content_store.source_articles()), 7)
        self.assertEqual(len(content_store.list_articles()), 5)
        self.assertTrue(all(article['id'].startswith('editorial-') for article in content_store.list_articles()))
        for row in content_store.source_articles():
            self.assertEqual(self.client.get('/api/v1/articles/' + row['id']).status_code, 404)
            self.assertEqual(self.client.get('/api/v1/articles/' + row['id'] + '/cover').status_code, 404)

    def test_article_publication_requires_editorial_review_sources_and_clean_body(self):
        valid = dict(title='植物观察', category='植物知识', body='观察叶片和花朵。', status='published',
                     reviewStatus='已审核', sourceKind='editorial', sourceNote='来源：https://www.iplant.cn/info/薄荷?t=z')
        self.assertEqual(ArticleInput(**valid).status, 'published')
        for change in [dict(reviewStatus='未审核'), dict(sourceKind='course_example'), dict(sourceNote=''),
                       dict(sourceNote='http://127.0.0.1/private'), dict(body='这部分内容待核实'),
                       dict(body='这部分内容待审核'), dict(body='内容未经过专业审校')]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                ArticleInput(**{**valid, **change})
        self.assertEqual(ArticleInput(**{**valid, 'status':'draft', 'reviewStatus':'未审核'}).status, 'draft')


if __name__ == '__main__':
    unittest.main()
