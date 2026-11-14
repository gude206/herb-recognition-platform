"""Public read-only science article endpoints."""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

import content_store

router = APIRouter(prefix='/api/v1/articles', tags=['科普文章'])


@router.get('')
def articles(q: str = Query('', max_length=200), category: str = Query('', max_length=64)):
    return content_store.list_articles(q.strip(), category.strip())


@router.get('/{article_id}/cover')
def cover(article_id: str):
    path = content_store.article_cover(article_id)
    if path is None:
        raise HTTPException(404, '该文章暂无可用封面')
    return FileResponse(path, headers={'Cache-Control': 'public, max-age=3600'})


@router.get('/{article_id}')
def detail(article_id: str):
    article = content_store.article_detail(article_id)
    if article is None:
        raise HTTPException(404, '未找到已发布的科普文章')
    return article
