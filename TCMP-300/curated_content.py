"""Licensed publications, kept separate from original model/source records."""
import hashlib
import json
import threading
import time
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit
import history_store
import publication_policy as policy

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'data/knowledge/editorial.collection.json'
PLANT_ASSETS = ROOT / 'assets/plants/editorial'
_cache = {}
_lock = threading.Lock()
SCHEMA = [
    '''CREATE TABLE IF NOT EXISTS plant_publications (
        plant_id VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
        publication_payload JSON NOT NULL, source_sha256 CHAR(64) CHARACTER SET ascii NOT NULL,
        created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
        updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
        CONSTRAINT fk_publication_plant FOREIGN KEY (plant_id) REFERENCES plant_catalog(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''',
    '''CREATE TABLE IF NOT EXISTS content_assets (
        asset_path VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
        license_payload JSON NOT NULL, source_sha256 CHAR(64) CHARACTER SET ascii NOT NULL,
        created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''',
]


@lru_cache(maxsize=1)
def _source(signature):
    return json.loads(SOURCE.read_text(encoding='utf-8'))


def source():
    stat = SOURCE.stat()
    return _source((stat.st_mtime_ns, stat.st_size))


def licensed_image(credit):
    if not isinstance(credit, dict):
        return False
    name = credit.get('license', '')
    allowed = name in {'CC0','CC BY 3.0 us'} or name in {f'CC {kind} {v}' for kind in ('BY', 'BY-SA') for v in ('2.0', '2.5', '3.0', '4.0')}
    return bool(allowed and credit.get('author') and credit.get('title') and credit.get('sha256')
                and policy.public_url(credit.get('sourceUrl', ''))
                and urlsplit(credit['sourceUrl']).hostname == 'commons.wikimedia.org'
                and policy.public_url(credit.get('licenseUrl', ''))
                and urlsplit(credit['licenseUrl']).hostname == 'creativecommons.org')


def validate_bundle(bundle):
    if bundle.get('version') != 1 or len(bundle['plants']) != 20 or len(bundle['articles']) != 5:
        raise ValueError('正式内容集必须包含 20 个植物条目和 5 篇文章')
    if len({p['id'] for p in bundle['plants']}) != 20 or len({a['id'] for a in bundle['articles']}) != 5:
        raise ValueError('正式内容 ID 不唯一')
    for path, credit in bundle['assets'].items():
        asset = (ROOT / path).resolve()
        if not asset.is_relative_to((ROOT / 'assets').resolve()) or not licensed_image(credit):
            raise ValueError('图片路径或许可无效')
        if hashlib.sha256(asset.read_bytes()).hexdigest() != credit['sha256']:
            raise ValueError('图片文件与授权清单的校验值不一致')
    for plant in bundle['plants']:
        text = ' '.join(plant[f] for f in ('name','description','completeIntroduction','observation','distribution','habitat'))
        text += json.dumps(plant['features'], ensure_ascii=False)
        if policy.UNRESOLVED.search(text) or not plant['sources'] or not licensed_image(plant['imageCredit']):
            raise ValueError('植物公开正文或图片署名不完整')
        if plant['imagePath'] not in bundle['assets'] or not all(policy.public_url(s['url']) for s in plant['sources']):
            raise ValueError('植物来源或图片索引无效')
    for article in bundle['articles']:
        if not policy.article_is_public(article) or len(article['body']) < 600:
            raise ValueError('正式文章不满足发布规则')
        if 'assets/articles/' + article['cover_path'] not in bundle['assets']:
            raise ValueError('文章缺少有署名的封面照片')


def seed(database):
    bundle = source()
    validate_bundle(bundle)
    digest = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    plants = assets = articles = 0
    with database.cursor() as cursor:
        for item in bundle['plants']:
            cursor.execute('INSERT IGNORE INTO plant_publications(plant_id,publication_payload,source_sha256) VALUES (%s,%s,%s)',
                           (item['id'], json.dumps(item, ensure_ascii=False), digest))
            plants += cursor.rowcount
        for path, credit in bundle['assets'].items():
            cursor.execute('INSERT IGNORE INTO content_assets(asset_path,license_payload,source_sha256) VALUES (%s,%s,%s)',
                           (path, json.dumps(credit, ensure_ascii=False), digest))
            assets += cursor.rowcount
        for item in bundle['articles']:
            fields = ['id','title','category','excerpt','body','cover_path','status','review_status','source_kind','source_note','display_order','legacy_read_label']
            cursor.execute('INSERT IGNORE INTO science_articles (' + ','.join(fields) + ') VALUES (' + ','.join(['%s'] * len(fields)) + ')',
                           tuple(item[f] for f in fields))
            articles += cursor.rowcount
        cursor.execute('INSERT IGNORE INTO content_imports(dataset_key,source_sha256,row_count) VALUES (%s,%s,%s)',
                       ('editorial-20261113', digest, len(bundle['plants']) + len(bundle['articles'])))
    clear_cache()
    return dict(inserted_publications=plants, inserted_licensed_assets=assets, inserted_editorial_articles=articles)


def clear_cache():
    with _lock:
        _cache.clear()


def publications():
    if not history_store.enabled():
        data = source()
        return {p['id']: p for p in data['plants']}, data['assets']
    config = history_store.configuration()
    key = (config['host'], config['port'], config['database'], config['user'])
    with _lock:
        cached = _cache.get(key)
        if cached and time.monotonic() < cached[0]:
            return cached[1]
        with history_store.connection(error_detail='无法读取植物公开资料与图片署名') as database, database.cursor() as cursor:
            cursor.execute('SELECT plant_id,publication_payload FROM plant_publications')
            plants = {r['plant_id']: json.loads(r['publication_payload']) for r in cursor.fetchall()}
            cursor.execute('SELECT asset_path,license_payload FROM content_assets')
            assets = {r['asset_path']: json.loads(r['license_payload']) for r in cursor.fetchall()}
        result = (plants, assets)
        _cache[key] = (time.monotonic() + 1, result)
        return result


def plant(plant_id, records=None):
    record = (publications()[0] if records is None else records).get(plant_id)
    return record if record and record.get('editorialStatus') == 'published' else None


def image_path(plant_id, records=None):
    record = plant(plant_id, records=records)
    if not record or not licensed_image(record.get('imageCredit')):
        return None
    path = (ROOT / record['imagePath']).resolve()
    if not path.is_relative_to(PLANT_ASSETS.resolve()) or path.suffix.lower() not in {'.jpg','.png','.webp'}:
        return None
    return path if path.is_file() else None


def asset_credit(path):
    value = publications()[1].get(path)
    return value if licensed_image(value) else None


def public_credit(credit):
    return {key: credit.get(key, '') for key in ('title','author','attribution','license','licenseUrl','sourceUrl','modifications')} if credit else None
