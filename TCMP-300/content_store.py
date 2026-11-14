"""MySQL plant catalogue and article content, retaining full original source fields."""
import csv
import hashlib
import json
import threading
import time
from pathlib import Path

from fastapi import HTTPException

import history_store
import publication_policy as publication
import curated_content

ROOT = Path(__file__).resolve().parent
PLANT_SOURCE = ROOT / 'data/author_tcmp_300/tcmp-info-20250329.csv'
ARTICLE_SOURCE = ROOT / 'data/knowledge/articles.seed.json'
ARTICLE_COVERS = ROOT / 'assets/articles'
_cache = {}
_cache_lock = threading.Lock()

SCHEMA = [
    '''CREATE TABLE IF NOT EXISTS plant_catalog (
        id VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
        class_id SMALLINT UNSIGNED NOT NULL UNIQUE,
        chinese_name VARCHAR(120) NOT NULL, latin_name VARCHAR(255) NOT NULL,
        family VARCHAR(120), genus VARCHAR(120),
        identity_status VARCHAR(255), review_status VARCHAR(120), cover_path TEXT,
        source_payload JSON NOT NULL, source_sha256 CHAR(64) CHARACTER SET ascii NOT NULL,
        created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
        updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
        KEY idx_plant_name (chinese_name), KEY idx_plant_family (family), KEY idx_plant_genus (genus)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''',
    '''CREATE TABLE IF NOT EXISTS science_articles (
        id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
        title VARCHAR(255) NOT NULL, category VARCHAR(64) NOT NULL,
        excerpt TEXT NOT NULL, body MEDIUMTEXT NOT NULL, cover_path VARCHAR(255),
        status ENUM('draft','published') NOT NULL DEFAULT 'draft',
        review_status VARCHAR(64) NOT NULL DEFAULT '未审核',
        source_kind VARCHAR(64) NOT NULL, source_note TEXT NOT NULL,
        legacy_read_label VARCHAR(64), read_count BIGINT UNSIGNED NOT NULL DEFAULT 0,
        display_order INT NOT NULL DEFAULT 0,
        row_version INT UNSIGNED NOT NULL DEFAULT 1, deleted_at DATETIME(3),
        created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
        updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
        KEY idx_article_status_order (status,display_order), KEY idx_article_category (category)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''',
    '''CREATE TABLE IF NOT EXISTS content_imports (
        dataset_key VARCHAR(32) CHARACTER SET ascii PRIMARY KEY,
        source_sha256 CHAR(64) CHARACTER SET ascii NOT NULL, row_count INT NOT NULL,
        imported_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''',
]


def source_plants():
    with PLANT_SOURCE.open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle))
    expected = {f'tcmp-{number:03d}' for number in range(1, 301)}
    if len(rows) != 300 or {row['植物ID'] for row in rows} != expected:
        raise ValueError('植物源文件必须包含 300 个稳定模型类别')
    if any(row['植物ID'] != f"tcmp-{int(row['No']):03d}" or None in row or None in row.values() for row in rows):
        raise ValueError('植物源文件类别或字段格式无效')
    return rows


def source_articles():
    seed = json.loads(ARTICLE_SOURCE.read_text(encoding='utf-8'))
    articles = seed['articles']
    if seed['version'] != 1 or len({article['id'] for article in articles}) != len(articles):
        raise ValueError('文章种子文件格式或 ID 无效')
    for article in articles:
        if not article['title'].strip() or not article['body'].strip() or article['status'] not in {'draft', 'published'}:
            raise ValueError('文章内容或发布状态无效')
    return articles


def initialize_tables(database):
    with database.cursor() as cursor:
        for statement in SCHEMA + curated_content.SCHEMA:
            cursor.execute(statement)


def seed_content(database, plants=None, articles=None):
    """Insert missing seeds only; edits and all history tables remain untouched."""
    include_editorial = articles is None
    plants = source_plants() if plants is None else plants
    articles = source_articles() if articles is None else articles
    plant_hash = hashlib.sha256(PLANT_SOURCE.read_bytes()).hexdigest()
    article_hash = hashlib.sha256(ARTICLE_SOURCE.read_bytes()).hexdigest()
    inserted_plants = inserted_articles = 0
    with database.cursor() as cursor:
        cursor.execute('SELECT id,class_id,latin_name FROM plant_catalog')
        existing = {row['id']: row for row in cursor.fetchall()}
        expected = {row['植物ID']: row for row in plants}
        for herb_id, saved in existing.items():
            source = expected.get(herb_id)
            if not source or saved['class_id'] != int(source['No']) or saved['latin_name'] != source['Latin Name'].strip():
                raise ValueError('数据库的原始植物类别字段与源文件不匹配；未覆盖现有资料')
        for row in plants:
            if row['植物ID'] in existing:
                continue
            cursor.execute('''INSERT INTO plant_catalog
                (id,class_id,chinese_name,latin_name,family,genus,identity_status,review_status,cover_path,source_payload,source_sha256)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (row['植物ID'], int(row['No']), row['Chinese Name'].strip(), row['Latin Name'].strip(),
                 row['规范科名'] or row['Family'], row['属名'], row['身份核对状态'], row['人工审核状态'],
                 row['封面图候选'], json.dumps(row, ensure_ascii=False), plant_hash))
            inserted_plants += 1
        cursor.execute('SELECT id FROM science_articles')
        existing_articles = {row['id'] for row in cursor.fetchall()}
        for article in articles:
            if article['id'] in existing_articles:
                continue
            article = {**article, 'status': article['status'] if publication.article_is_public(article) else 'draft'}
            cursor.execute('''INSERT INTO science_articles
                (id,title,category,excerpt,body,cover_path,status,review_status,source_kind,source_note,legacy_read_label,display_order)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                tuple(article.get(field, '') for field in ['id', 'title', 'category', 'excerpt', 'body', 'cover_path',
                    'status', 'review_status', 'source_kind', 'source_note', 'legacy_read_label', 'display_order']))
            inserted_articles += 1
        for key, source_hash, count in [('plants', plant_hash, len(plants)), ('articles', article_hash, len(articles))]:
            cursor.execute('INSERT IGNORE INTO content_imports(dataset_key,source_sha256,row_count) VALUES (%s,%s,%s)', (key, source_hash, count))
    editorial = curated_content.seed(database) if include_editorial else {}
    clear_cache()
    return dict(**editorial, inserted_plants=inserted_plants, inserted_articles=inserted_articles,
                source_plant_count=len(plants), source_article_count=len(articles),
                plant_source_sha256=plant_hash, article_source_sha256=article_hash)


def clear_cache():
    with _cache_lock:
        _cache.clear()
    curated_content.clear_cache()


def plant_rows():
    config = history_store.configuration()
    key = (config['host'], config['port'], config['database'], config['user'])
    with _cache_lock:
        cached = _cache.get(key)
        if cached and time.monotonic() < cached[0]:
            return cached[1]
        with history_store.connection(error_detail='无法读取 MySQL 植物图鉴，请检查数据库和资料导入状态') as database, database.cursor() as cursor:
            cursor.execute('SELECT id,class_id,source_payload FROM plant_catalog ORDER BY class_id')
            records = cursor.fetchall()
        if len(records) != 300 or {row['id'] for row in records} != {f'tcmp-{number:03d}' for number in range(1, 301)}:
            raise HTTPException(503, 'MySQL 植物图鉴未完整导入 300 类资料')
        result = {}
        for record in records:
            row = json.loads(record['source_payload'])
            try:
                valid = isinstance(row, dict) and row.get('植物ID') == record['id'] and int(row.get('No', 0)) == record['class_id']
            except (TypeError, ValueError):
                valid = False
            if not valid:
                raise HTTPException(503, 'MySQL 图鉴的原始模型类别字段不一致')
            result[record['id']] = row
        _cache[key] = (time.monotonic() + 1, result)
        return result


def serialize_article(row, detail=False):
    credit = curated_content.asset_credit('assets/articles/' + (row.get('cover_path') or ''))
    updated = row.get('updated_at')
    return dict(id=row['id'], title=row['title'], category=row['category'], excerpt=row['excerpt'],
                body=row['body'] if detail else '', image=f"/api/v1/articles/{row['id']}/cover?v={row.get('row_version', 1)}" if row['cover_path'] else '',
                reads=str(row.get('read_count', 0)), readCount=row.get('read_count', 0), reviewStatus=row['review_status'],
                sourceKind=row['source_kind'], sourceNote=row['source_note'], status=row['status'],
                imageCredit=curated_content.public_credit(credit),
                storageSource='mysql' if history_store.enabled() else 'seed',
                updatedAt=updated.isoformat(timespec='milliseconds') + 'Z' if updated else '2026-11-13', version=row.get('row_version', 1))


def list_articles(query='', category=''):
    if not history_store.enabled():
        return [serialize_article(row) for row in curated_content.source()['articles'] + source_articles() if publication.article_is_public(row)
            and (not category or row['category'] == category or category == '草药背景' and row['category'] == '植物知识')
            and (not query or query.casefold() in ' '.join(row[field] for field in ['title', 'excerpt', 'body']).casefold())]
    conditions, parameters = ["status='published'", 'deleted_at IS NULL'], []
    if query:
        pattern = '%' + query.replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%'
        conditions.append("(title LIKE %s ESCAPE '!' OR excerpt LIKE %s ESCAPE '!' OR body LIKE %s ESCAPE '!')")
        parameters.extend([pattern] * 3)
    if category:
        if category == '草药背景':
            conditions.append('category IN (%s,%s)')
            parameters.extend(['草药背景', '植物知识'])
        else:
            conditions.append('category=%s')
            parameters.append(category)
    with history_store.connection(error_detail='无法读取 MySQL 科普文章，请检查数据库服务') as database, database.cursor() as cursor:
        cursor.execute('SELECT * FROM science_articles WHERE ' + ' AND '.join(conditions) + ' ORDER BY display_order,id', parameters)
        return [serialize_article(row) for row in cursor.fetchall() if publication.article_is_public(row)]


def article_record(article_id):
    if not history_store.enabled():
        return next((row for row in curated_content.source()['articles'] + source_articles() if row['id'] == article_id and publication.article_is_public(row)), None)
    with history_store.connection(error_detail='无法读取 MySQL 科普文章，请检查数据库服务') as database, database.cursor() as cursor:
        cursor.execute("SELECT * FROM science_articles WHERE id=%s AND status='published' AND deleted_at IS NULL", (article_id,))
        row = cursor.fetchone()
        return row if row and publication.article_is_public(row) else None


def article_detail(article_id):
    record = article_record(article_id)
    if record is None:
        return None
    if history_store.enabled():
        return serialize_article(record, detail=True)
    return {**next(article for article in list_articles() if article['id'] == article_id), 'body': record['body']}


def article_cover(article_id):
    record = article_record(article_id)
    if not record or not record['cover_path']:
        return None
    path = (ARTICLE_COVERS / record['cover_path']).resolve()
    if not path.is_relative_to(ARTICLE_COVERS.resolve()) or path.suffix.lower() not in {'.svg', '.png', '.jpg', '.jpeg', '.webp'}:
        return None
    return path if path.is_file() else None


def health():
    if not history_store.enabled():
        return dict(source='files', status='ready')
    try:
        with history_store.connection() as database, database.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) AS n FROM plant_catalog')
            plants = cursor.fetchone()['n']
            cursor.execute("SELECT * FROM science_articles WHERE status='published' AND deleted_at IS NULL")
            articles = sum(publication.article_is_public(row) for row in cursor.fetchall())
            cursor.execute('SELECT COUNT(*) AS n FROM plant_publications')
            curated = cursor.fetchone()['n']
            cursor.execute('SELECT COUNT(*) AS n FROM content_assets')
            assets = cursor.fetchone()['n']
        return dict(source='mysql', status='ready' if plants == 300 else 'unavailable', plants=plants, articles=articles,
                    curatedPlants=curated, licensedAssets=assets)
    except HTTPException:
        return dict(source='mysql', status='unavailable')
