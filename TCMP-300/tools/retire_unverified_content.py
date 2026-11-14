"""Withdraw non-publishable articles without deleting their text or user history."""
import argparse
import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import history_store
import publication_policy


def counts(cursor):
    result = {}
    for table in ('plant_catalog', 'chat_conversations', 'chat_messages', 'recognition_records', 'app_users'):
        cursor.execute('SELECT COUNT(*) AS total FROM ' + table)
        result[table] = cursor.fetchone()['total']
    return result


def retire(apply=False):
    with history_store.connection() as database, database.cursor() as cursor:
        before = counts(cursor)
        cursor.execute("SELECT * FROM science_articles WHERE status='published' AND deleted_at IS NULL FOR UPDATE")
        articles = [row for row in cursor.fetchall() if not publication_policy.article_is_public(row)]
        if not apply:
            print(json.dumps(dict(pending=len(articles), articles=[row['id'] for row in articles]), ensure_ascii=False))
            return
        if not articles:
            print('没有需要下架的文章；原始资料和账号历史保持不变。')
            return
        report = dict(operation='withdraw_unverified_content',
            created_at=datetime.now(timezone.utc).isoformat(), originals=articles, before=before,
            original_sha256=hashlib.sha256(json.dumps(articles, ensure_ascii=False, default=str, sort_keys=True).encode()).hexdigest())
        folder = ROOT.parent / 'mysql-local/content-retirement'
        folder.mkdir(parents=True, exist_ok=True)
        file = folder / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:8] + '.json')
        file.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        for row in articles:
            cursor.execute("UPDATE science_articles SET status='draft',row_version=row_version+1 WHERE id=%s AND row_version=%s",
                           (row['id'], row['row_version']))
            if cursor.rowcount != 1:
                raise RuntimeError('文章版本已改变，未提交本次下架操作。')
        after = counts(cursor)
        if before != after:
            raise RuntimeError('检测到资料或历史数量变化，未提交本次操作。')
        database.commit()
        print('已下架 ' + str(len(articles)) + ' 篇文章，正文保留为草稿；原始快照：' + str(file))
        print('植物、账号、对话及识别历史数量保持不变。')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        retire(args.apply)
    except Exception as error:
        print(str(error) if isinstance(error, RuntimeError) else '内容下架失败；未输出数据库凭据。', file=sys.stderr)
        raise SystemExit(1)
