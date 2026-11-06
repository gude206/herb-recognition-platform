"""Integration checks using the actual checkpoint; no mocked model outputs."""
import csv
import io
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
import torch

from api import MAX_UPLOAD_BYTES, ROOT, QUANTIZED_MODEL, PREPROCESS, app, allowed_frontend_origins
import herb_catalog


class RecognitionAPITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def test_real_held_out_image_matches_direct_inference(self):
        with (ROOT / 'data/author_tcmp_300/splits/test.csv').open(encoding='utf-8') as file:
            row = next(csv.DictReader(file))
        path = ROOT / 'data/author_tcmp_300/images/tcmp-300' / row['relative_path']
        content = path.read_bytes()
        response = self.client.post('/api/v1/predict', files={'file': ('plant.jpg', content, 'image/jpeg')})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['code'], 200)
        result = response.json()['result']
        with QUANTIZED_MODEL.open('rb') as model_file:
            direct_model = torch.jit.load(model_file, map_location='cpu').eval()
        with Image.open(io.BytesIO(content)) as image, torch.inference_mode():
            scores, indices = direct_model(PREPROCESS(image.convert('RGB')).unsqueeze(0)).softmax(1)[0].topk(5)
        expected_ids = [app.state.predictor.labels[index]['herb_id'] for index in indices.tolist()]
        self.assertEqual([x['herb_id'] for x in result['top_k']], expected_ids)
        for actual, expected in zip(result['top_k'], scores.tolist()):
            self.assertAlmostEqual(actual['confidence'], expected, places=6)
        self.assertEqual(len(result['top_k']), 5)
        self.assertEqual(len({item['herb_id'] for item in result['top_k']}), 5)
        scores = [item['confidence'] for item in result['top_k']]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertTrue(all(0 <= score <= 1 for score in scores))
        self.assertLessEqual(sum(scores), 1.000001)
        self.assertEqual(result['prediction'], result['top_k'][0])
        self.assertTrue(all(item['name'] and item['latin_name'] for item in result['top_k']))
        for item in result['top_k']:
            expected_identity = herb_catalog.identity_metadata(herb_catalog.rows()[item['herb_id']])
            for field, value in expected_identity.items():
                self.assertEqual(item[field], value)
        self.assertEqual(result['model']['optimization'], 'int8')
        self.assertEqual(result['model']['device'], 'cpu')
        self.assertNotIn('test_top5_accuracy', result['model'])
        self.assertGreater(result['timing_ms']['inference'], 0)
        self.assertGreaterEqual(result['timing_ms']['api'], result['timing_ms']['total'])

    def test_real_sample_image_can_be_uploaded(self):
        samples = self.client.get('/api/v1/recognition/samples').json()
        self.assertEqual(len(samples), 4)
        for sample in samples:
            image = self.client.get(sample['image_url'])
            self.assertEqual(image.status_code, 200)
            result = self.client.post('/api/v1/predict', files={'file': ('sample', image.content, image.headers['content-type'])})
            self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.client.get('/api/v1/recognition/samples/unknown/image').status_code, 404)

    def test_invalid_and_empty_uploads(self):
        for content in [b'', b'demo', b'not an image']:
            result = self.client.post('/api/v1/predict', files={'file': ('fake.jpg', content, 'image/jpeg')})
            self.assertEqual(result.status_code, 400)
            self.assertEqual(result.json()['code'], 400)
            self.assertIsNone(result.json()['result'])
            self.assertTrue(result.json()['msg'])
        self.assertEqual(self.client.post('/api/v1/predict').status_code, 422)

    def test_oversized_upload(self):
        result = self.client.post('/api/v1/predict', files={'file': ('large.jpg', b'x' * (MAX_UPLOAD_BYTES + 1), 'image/jpeg')})
        self.assertEqual(result.status_code, 413)

    def test_exact_file_limit_allows_normal_multipart_overhead(self):
        image = io.BytesIO()
        Image.new('RGB', (64, 64)).save(image, format='PNG')
        content = image.getvalue()
        content += b'\0' * (MAX_UPLOAD_BYTES - len(content))
        result = self.client.post('/api/v1/predict', files={'file': ('plant.png', content, 'image/png')})
        self.assertEqual(result.status_code, 200, result.text)

    def test_extra_files_and_form_fields_are_rejected(self):
        image = io.BytesIO()
        Image.new('RGB', (64, 64)).save(image, format='PNG')
        file = ('plant.png', image.getvalue(), 'image/png')
        for second_name in ('file', 'extra'):
            with self.subTest(second_name=second_name):
                result = self.client.post('/api/v1/predict', files=[('file', file), (second_name, file)])
                self.assertEqual(result.status_code, 400, result.text)
        result = self.client.post('/api/v1/predict', files={'file': file}, data={'extra': 'ignored metadata'})
        self.assertEqual(result.status_code, 400, result.text)

    def test_extreme_aspect_ratio_is_rejected_before_decode_and_resize(self):
        # All images are small in memory. Each dimension guard has a distinct trigger.
        for dimensions in ((1, 100_000), (10_001, 100), (100, 2_001), (100, 1_600)):
            with self.subTest(dimensions=dimensions):
                image = io.BytesIO()
                Image.new('RGB', dimensions).save(image, format='PNG')
                with patch('api.PREPROCESS', side_effect=AssertionError('Unsafe resize ran')), \
                     patch('api.ImageOps.exif_transpose', side_effect=AssertionError('Unsafe decode ran')):
                    result = self.client.post('/api/v1/predict', files={'file': ('long.png', image.getvalue(), 'image/png')})
                self.assertEqual(result.status_code, 413, result.text)

    def test_prediction_labels_preserve_identity_conflicts(self):
        by_id = {label['herb_id']: label for label in app.state.predictor.labels}
        conflict = by_id['tcmp-051']
        row = herb_catalog.rows()['tcmp-051']
        self.assertEqual(conflict['class_id'], 51)
        self.assertEqual(conflict['latin_name'], row['Latin Name'])
        self.assertEqual(conflict['original_latin_name'], row['Latin Name'])
        self.assertTrue(conflict['identity_conflict'])
        self.assertEqual(conflict['accepted_latin_name'], '')
        self.assertEqual(conflict['identity_status'], row['身份核对状态'])
        self.assertEqual(conflict['review_status'], row['人工审核状态'])
        self.assertEqual(len(by_id), 300)

    def test_optional_frontend_origin_only_accepts_local_http_ports(self):
        with patch.dict('os.environ', {'TCMP_FRONTEND_ORIGIN': 'http://127.0.0.1:5273'}):
            self.assertIn('http://127.0.0.1:5273', allowed_frontend_origins())
            self.assertIn('http://localhost:5173', allowed_frontend_origins())
        for origin in ('https://example.com:5273', 'http://localhost:65536', 'http://localhost:0',
                       'http://localhost:5273/extra', 'http://localhost:5273@evil.example'):
            with self.subTest(origin=origin), patch.dict('os.environ', {'TCMP_FRONTEND_ORIGIN': origin}):
                with self.assertRaises(ValueError):
                    allowed_frontend_origins()

    def test_grayscale_png_and_transparent_png(self):
        for mode in ['L', 'RGBA']:
            image = io.BytesIO()
            Image.new(mode, (64, 64)).save(image, format='PNG')
            result = self.client.post('/api/v1/predict', files={'file': ('plant.png', image.getvalue(), 'image/png')})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(len(result.json()['result']['top_k']), 5)

    def test_unsupported_format(self):
        image = io.BytesIO()
        Image.new('RGB', (64, 64)).save(image, format='GIF')
        result = self.client.post('/api/v1/predict', files={'file': ('plant.gif', image.getvalue(), 'image/gif')})
        self.assertEqual(result.status_code, 415)

    def test_health_and_browser_cors(self):
        self.assertEqual(self.client.get('/api/v1/health').json()['model']['classes'], 300)
        result = self.client.options('/api/v1/predict', headers={
            'Origin': 'http://127.0.0.1:5173', 'Access-Control-Request-Method': 'POST'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers['access-control-allow-origin'], 'http://127.0.0.1:5173')


if __name__ == '__main__':
    unittest.main(verbosity=2)
