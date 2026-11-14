"""Publication completeness, file/license integrity and isolation from raw model data."""
import copy
import hashlib
import json
import os
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from PIL import Image
from api import app
import curated_content as curated
import herb_catalog
import publication_policy


class CuratedContentTest(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ, MYSQL_ENABLED='false')
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client=TestClient(app)
        self.addCleanup(self.client.close)

    def test_collection_has_twenty_original_plant_records_and_five_complete_articles(self):
        data=curated.source()
        curated.validate_bundle(data)
        for record in data['plants']:
            self.assertEqual(herb_catalog.rows()[record['id']]['规范中文名'],record['name'])
            self.assertNotIn('封面图',record)
        self.assertEqual(len({p['imagePath'] for p in data['plants']}),20)
        for article in data['articles']:
            self.assertGreaterEqual(len(article['body']),600)
            self.assertTrue(publication_policy.article_is_public(article))
            self.assertNotIn('待核',article['body'])

    def test_featured_first_page_contains_exactly_twenty_licensed_photos(self):
        data=self.client.get('/api/v1/herbs',params={'sort':'featured','page_size':20}).json()
        self.assertEqual([p['id'] for p in data['items']],[p['id'] for p in curated.source()['plants']])
        for item in data['items']:
            self.assertTrue(item['curated'])
            detail=self.client.get('/api/v1/herbs/'+item['id']).json()
            self.assertTrue(detail['completeIntroduction'])
            self.assertTrue(detail['observation'])
            self.assertTrue(detail['sources'])
            photo=self.client.get(item['image'])
            self.assertEqual(photo.status_code,200)
            self.assertEqual(hashlib.sha256(photo.content).hexdigest(),curated.plant(item['id'])['imageCredit']['sha256'])

    def test_published_articles_include_matching_cover_attribution_and_full_body(self):
        articles=self.client.get('/api/v1/articles').json()
        self.assertEqual(len(articles),5)
        for item in articles:
            detail=self.client.get('/api/v1/articles/'+item['id']).json()
            self.assertGreaterEqual(len(detail['body']),600)
            self.assertTrue(detail['imageCredit']['author'])
            cover=self.client.get(item['image'])
            self.assertEqual(cover.status_code,200)
            source=next(a for a in curated.source()['articles'] if a['id']==item['id'])
            credit=curated.source()['assets']['assets/articles/'+source['cover_path']]
            self.assertEqual(hashlib.sha256(cover.content).hexdigest(),credit['sha256'])
        for path in curated.source()['assets']:
            with Image.open(curated.ROOT/path) as photo:
                self.assertEqual(photo.format,'JPEG')
                photo.verify()

    def test_missing_or_mismatched_license_and_escaping_image_path_are_blocked(self):
        original=copy.deepcopy(curated.source()['plants'][0])
        for change in ({'license':'All rights reserved'},{'author':''},{'licenseUrl':'https://example.com/license'}):
            record=copy.deepcopy(original)
            record['imageCredit'].update(change)
            with patch.object(curated,'plant',return_value=record):
                self.assertIsNone(curated.image_path(record['id']))
        original['imagePath']='api.py'
        with patch.object(curated,'plant',return_value=original):
            self.assertIsNone(curated.image_path(original['id']))


if __name__=='__main__':unittest.main()
