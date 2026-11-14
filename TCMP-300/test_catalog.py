"""Public atlas coverage and source boundaries; original model records stay intact."""
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from fastapi.testclient import TestClient
from api import app
import herb_catalog as catalog


class CatalogueTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env=patch.dict(os.environ, MYSQL_ENABLED='false')
        cls.env.start()
        cls.client=TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.env.stop()

    def test_all_pages_cover_only_public_records_without_changing_model_classes(self):
        ids=[]
        for page in range(1,14):
            response=self.client.get('/api/v1/herbs',params={'page':page})
            self.assertEqual(response.status_code,200)
            data=response.json()
            self.assertEqual(data['total'],299)
            self.assertEqual(data['collectionTotal'],299)
            ids.extend(h['id'] for h in data['items'])
        self.assertEqual(ids,[f'tcmp-{n:03}' for n in range(1,301) if n!=51])
        self.assertEqual(len(catalog.rows()),300)
        self.assertEqual(self.client.get('/api/v1/herbs',params={'page':999}).json()['page'],13)

    def test_search_and_combined_filters_use_public_fields(self):
        detail=self.client.get('/api/v1/herbs/tcmp-004').json()
        for name in ('菝葜','Smilax china','金刚藤'):
            result=self.client.get('/api/v1/herbs',params={'q':name}).json()
            self.assertIn('tcmp-004',[h['id'] for h in result['items']])
        result=self.client.get('/api/v1/herbs',params={'family':detail['family'],'genus':detail['genus'],'region':'广东'}).json()
        self.assertIn('tcmp-004',[h['id'] for h in result['items']])
        self.assertTrue(all(h['family']==detail['family'] and h['genus']==detail['genus'] for h in result['items']))
        self.assertEqual(self.client.get('/api/v1/herbs',params={'q':'nonexistent-plant-987'}).json()['total'],0)

    def test_pending_medical_data_and_conflicted_details_are_not_public(self):
        detail=self.client.get('/api/v1/herbs/tcmp-004').json()
        self.assertTrue(detail['sources'])
        self.assertTrue(detail['features'])
        self.assertEqual(detail['materials'],[])
        self.assertEqual(detail['toxicity'],'')
        self.assertEqual(detail['confusion'],'')
        self.assertEqual(detail['notes'],'')
        self.assertEqual(self.client.get('/api/v1/herbs/tcmp-051').status_code,404)
        self.assertTrue(catalog.rows()['tcmp-004']['药材记录JSON'])

    def test_withdrawn_medical_terms_do_not_leak_into_search(self):
        for query in ({'q':'清热解毒'},{'effect':'清热解毒'},{'part':'根茎'},{'property':'温'}):
            result=self.client.get('/api/v1/herbs',params=query).json()
            self.assertEqual(result['total'],0)

    def test_only_approved_licensed_images_are_served_and_paths_are_bounded(self):
        self.assertIsNone(catalog.reference_image('tcmp-004'))
        self.assertEqual(self.client.get('/api/v1/herbs/tcmp-004/reference-image').status_code,404)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'approved.jpg'
            Image.new('RGB',(8,8)).save(path)
            row={**catalog.rows()['tcmp-004'],'封面图':str(path),'图片审核状态':'已审核','图片授权状态':'开放许可'}
            with patch.object(catalog,'TRAIN_IMAGES',Path(folder)),patch.object(catalog,'rows',return_value={'tcmp-004':row}):
                response=self.client.get('/api/v1/herbs/tcmp-004/reference-image')
                self.assertEqual(response.status_code,200)
                self.assertEqual(hashlib.sha256(response.content).digest(),hashlib.sha256(path.read_bytes()).digest())
                row['封面图']=str(catalog.ROOT/'api.py')
                self.assertIsNone(catalog.reference_image('tcmp-004'))

    def test_validation_filters_and_recent_order(self):
        self.assertEqual(self.client.get('/api/v1/herbs/unknown').status_code,404)
        for params in ({'page':0},{'page_size':0},{'page_size':61}):
            self.assertEqual(self.client.get('/api/v1/herbs',params=params).status_code,422)
        data=self.client.get('/api/v1/herbs/filters').json()
        self.assertEqual(data['total'],299)
        self.assertEqual(data['distributionCount'],282)
        self.assertEqual(data['curatedCount'],20)
        self.assertEqual(data['parts'],[])
        self.assertEqual(data['effects'],[])
        self.assertFalse(catalog.region_matches(catalog.serialize(catalog.rows()['tcmp-004'])['distribution'],'海南'))
        result=self.client.get('/api/v1/herbs',params={'sort':'recent','recent_ids':'tcmp-051,tcmp-300,tcmp-004'}).json()
        self.assertEqual([h['id'] for h in result['items'][:2]],['tcmp-300','tcmp-004'])

    def test_list_and_filters_share_publications_and_do_not_reparse_config_per_plant(self):
        import curated_content
        import history_store
        for read in (lambda:catalog.list_herbs(sort='featured',page_size=20),catalog.filters):
            with self.subTest(read=read), \
                    patch.object(curated_content,'publications',wraps=curated_content.publications) as publications, \
                    patch.object(history_store,'configuration',wraps=history_store.configuration) as configuration, \
                    patch.object(catalog.publication,'botanical_evidence',wraps=catalog.publication.botanical_evidence) as evidence:
                data=read()
                self.assertEqual(data['total'],299)
                self.assertEqual(publications.call_count,1)
                self.assertLessEqual(configuration.call_count,4)
                self.assertEqual(evidence.call_count,300)


if __name__=='__main__':
    unittest.main(verbosity=2)
