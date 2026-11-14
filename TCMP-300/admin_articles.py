"""Administrator-only article editing. Public atlas and model behavior are unchanged."""
import io
import json
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, model_validator

import content_store
import history_store
import publication_policy as publication
from auth_api import administrator

router = APIRouter(prefix='/api/v1/admin/articles', tags=['管理员文章维护'])

AUDIT_SCHEMA = '''CREATE TABLE IF NOT EXISTS article_audit_log (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    article_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    actor_user_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    action VARCHAR(32) NOT NULL, before_json JSON, after_json JSON,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    KEY idx_article_audit (article_id,created_at),
    FOREIGN KEY (article_id) REFERENCES science_articles(id),
    FOREIGN KEY (actor_user_id) REFERENCES app_users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'''


def initialize_schema(database):
    with database.cursor() as cursor:
        cursor.execute('SHOW COLUMNS FROM science_articles LIKE %s', ('row_version',))
        if not cursor.fetchone():
            cursor.execute('ALTER TABLE science_articles ADD COLUMN row_version INT UNSIGNED NOT NULL DEFAULT 1')
        cursor.execute('SHOW COLUMNS FROM science_articles LIKE %s', ('deleted_at',))
        if not cursor.fetchone():
            cursor.execute('ALTER TABLE science_articles ADD COLUMN deleted_at DATETIME(3) NULL')
        cursor.execute(AUDIT_SCHEMA)


def admin_article(row):
    return {**content_store.serialize_article(row, detail=True), 'displayOrder': row['display_order'],
            'deleted': row['deleted_at'] is not None, 'coverPath': row['cover_path'] or '',
            'image': f"/api/v1/admin/articles/{row['id']}/cover?v={row['row_version']}" if row['cover_path'] else ''}


def locked_article(cursor, article_id, version=None, deleted=False):
    cursor.execute('SELECT * FROM science_articles WHERE id=%s FOR UPDATE', (article_id,))
    row = cursor.fetchone()
    if not row or (row['deleted_at'] is not None) != deleted:
        raise HTTPException(404, '未找到该文章')
    if version is not None and row['row_version'] != version:
        raise HTTPException(409, '文章已被其他编辑更新，请重新载入后再保存')
    return row


def audit(cursor, user, article_id, action, before, after):
    def snapshot(row):
        return json.dumps(admin_article(row), ensure_ascii=False) if row else None
    cursor.execute('''INSERT INTO article_audit_log(article_id,actor_user_id,action,before_json,after_json)
        VALUES (%s,%s,%s,%s,%s)''', (article_id, user['id'], action, snapshot(before), snapshot(after)))


class ArticleInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=255)
    category: str = Field(min_length=1, max_length=64)
    excerpt: str = Field(default='', max_length=4000)
    body: str = Field(default='', max_length=80000)
    status: Literal['draft', 'published'] = 'draft'
    reviewStatus: str = Field(default='未审核', max_length=64)
    sourceKind: Literal['course_example', 'editorial'] = 'editorial'
    sourceNote: str = Field(default='', max_length=4000)
    displayOrder: int = Field(default=100, ge=0, le=100000)

    @model_validator(mode='after')
    def required_fields(self):
        if not self.title.strip() or not self.category.strip():
            raise ValueError('标题和分类不能为空')
        if self.status == 'published' and not self.body.strip():
            raise ValueError('发布文章前请填写正文')
        if self.status == 'published' and not publication.article_is_public(dict(status=self.status,
            review_status=self.reviewStatus,source_kind=self.sourceKind,source_note=self.sourceNote,
            title=self.title,excerpt=self.excerpt,body=self.body)):
            raise ValueError('仅可发布已审核的科普文章；请填写公开来源链接，并移除待核验内容和课程示例')
        return self


class ArticleUpdate(ArticleInput):
    expectedVersion: int = Field(ge=1)


class VersionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expectedVersion: int = Field(ge=1)


def values(payload):
    return (payload.title.strip(), payload.category.strip(), payload.excerpt, payload.body,
            payload.status, payload.reviewStatus, payload.sourceKind, payload.sourceNote, payload.displayOrder)


@router.get('')
def list_articles(user=Depends(administrator), q: str = Query('', max_length=200),
                  status: Literal['all', 'draft', 'published', 'deleted'] = 'all',
                  page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=60)):
    conditions = ['deleted_at IS NOT NULL' if status == 'deleted' else 'deleted_at IS NULL']
    parameters = []
    if status in {'draft', 'published'}:
        conditions.append('status=%s')
        parameters.append(status)
    if q.strip():
        pattern = '%' + q.strip().replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%'
        conditions.append("(title LIKE %s ESCAPE '!' OR category LIKE %s ESCAPE '!')")
        parameters.extend([pattern, pattern])
    where = ' AND '.join(conditions)
    with history_store.connection() as database, database.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) AS n FROM science_articles WHERE ' + where, parameters)
        total = cursor.fetchone()['n']
        cursor.execute('SELECT * FROM science_articles WHERE ' + where + ' ORDER BY display_order,id LIMIT %s OFFSET %s',
                       [*parameters, page_size, (page - 1) * page_size])
        return dict(items=[admin_article(row) for row in cursor.fetchall()], total=total, page=page, pageSize=page_size)


@router.get('/{article_id}')
def detail(article_id: str, user=Depends(administrator)):
    with history_store.connection() as database, database.cursor() as cursor:
        cursor.execute('SELECT * FROM science_articles WHERE id=%s', (article_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(404, '未找到该文章')
        return admin_article(row)


@router.get('/{article_id}/cover')
def private_cover(article_id: str, user=Depends(administrator)):
    with history_store.connection() as database, database.cursor() as cursor:
        cursor.execute('SELECT cover_path FROM science_articles WHERE id=%s', (article_id,))
        row = cursor.fetchone()
    if not row or not row['cover_path']:
        raise HTTPException(404, '暂无封面图片')
    path = (content_store.ARTICLE_COVERS / row['cover_path']).resolve()
    if not path.is_relative_to(content_store.ARTICLE_COVERS.resolve()) or not path.is_file() or path.suffix.lower() not in {'.jpg', '.jpeg', '.png', '.webp', '.svg'}:
        raise HTTPException(404, '暂无可用封面')
    return FileResponse(path, headers={'Cache-Control': 'private, no-store'})


@router.post('', status_code=201)
def create(payload: ArticleInput, user=Depends(administrator)):
    article_id = 'article-' + uuid.uuid4().hex[:20]
    with history_store.connection() as database, database.cursor() as cursor:
        cursor.execute('''INSERT INTO science_articles(id,title,category,excerpt,body,status,review_status,source_kind,source_note,display_order)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''', (article_id, *values(payload)))
        row = locked_article(cursor, article_id)
        audit(cursor, user, article_id, 'create', None, row)
        return admin_article(row)


@router.put('/{article_id}')
def update(article_id: str, payload: ArticleUpdate, user=Depends(administrator)):
    with history_store.connection() as database, database.cursor() as cursor:
        before = locked_article(cursor, article_id, payload.expectedVersion)
        cursor.execute('''UPDATE science_articles SET title=%s,category=%s,excerpt=%s,body=%s,status=%s,
            review_status=%s,source_kind=%s,source_note=%s,display_order=%s,row_version=row_version+1 WHERE id=%s''',
            (*values(payload), article_id))
        after = locked_article(cursor, article_id)
        audit(cursor, user, article_id, 'update', before, after)
        return admin_article(after)


@router.delete('/{article_id}')
def remove(article_id: str, payload: VersionInput, user=Depends(administrator)):
    with history_store.connection() as database, database.cursor() as cursor:
        before = locked_article(cursor, article_id, payload.expectedVersion)
        cursor.execute("UPDATE science_articles SET deleted_at=UTC_TIMESTAMP(3),status='draft',row_version=row_version+1 WHERE id=%s", (article_id,))
        after = locked_article(cursor, article_id, deleted=True)
        audit(cursor, user, article_id, 'delete', before, after)
        return dict(saved=True)


@router.post('/{article_id}/restore')
def restore(article_id: str, payload: VersionInput, user=Depends(administrator)):
    with history_store.connection() as database, database.cursor() as cursor:
        before = locked_article(cursor, article_id, payload.expectedVersion, deleted=True)
        cursor.execute("UPDATE science_articles SET deleted_at=NULL,status='draft',row_version=row_version+1 WHERE id=%s", (article_id,))
        after = locked_article(cursor, article_id)
        audit(cursor, user, article_id, 'restore', before, after)
        return admin_article(after)


@router.post('/{article_id}/cover')
async def upload_cover(article_id: str, expectedVersion: int = Query(ge=1), file: UploadFile = File(...), user=Depends(administrator)):
    try:
        content = await file.read(5 * 1024 * 1024 + 1)
    finally:
        await file.close()
    if not content or len(content) > 5 * 1024 * 1024:
        raise HTTPException(413, '封面图片不能为空且不得超过 5MB')
    try:
        with Image.open(io.BytesIO(content)) as original:
            if original.format not in {'JPEG', 'PNG', 'WEBP'}:
                raise HTTPException(415, '封面仅支持 JPG、PNG 或 WEBP')
            if original.width * original.height > 25000000 or max(original.size) > 10000:
                raise HTTPException(413, '封面分辨率过大，请缩小后上传')
            image = ImageOps.exif_transpose(original).convert('RGB')
            image.thumbnail((1600, 1600))
            output = io.BytesIO()
            image.save(output, format='JPEG', quality=90)
    except (UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(400, '无法读取封面图片') from None
    except Image.DecompressionBombError:
        raise HTTPException(413, '封面分辨率过大') from None
    path = content_store.ARTICLE_COVERS / (uuid.uuid4().hex + '.jpg')
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with history_store.connection() as database, database.cursor() as cursor:
            before = locked_article(cursor, article_id, expectedVersion)
            path.write_bytes(output.getvalue())
            cursor.execute('UPDATE science_articles SET cover_path=%s,row_version=row_version+1 WHERE id=%s', (path.name, article_id))
            after = locked_article(cursor, article_id)
            audit(cursor, user, article_id, 'cover', before, after)
        return admin_article(after)
    except Exception:
        path.unlink(missing_ok=True)
        raise
