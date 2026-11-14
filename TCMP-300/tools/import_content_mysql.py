"""Add plant and science article content to the configured project MySQL database."""
import json
import sys
from pathlib import Path

import pymysql
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import content_store
import history_store


def migrate():
    config = history_store.configuration()
    config.pop('enabled')
    admin = dotenv_values(ROOT.parent / 'mysql-local/.admin.env')
    if not admin.get('MYSQL_ROOT_PASSWORD') or int(admin.get('MYSQL_PORT', '0')) != config['port'] or config['host'] != '127.0.0.1':
        raise RuntimeError('本脚本使用项目独立实例的本机管理凭据；其他实例请由管理员执行表结构和导入。')
    config.update(user='root', password=admin['MYSQL_ROOT_PASSWORD'], charset='utf8mb4',
                  cursorclass=pymysql.cursors.DictCursor, autocommit=False,
                  init_command="SET time_zone = '+00:00'")
    with pymysql.connect(**config) as database:
        with database.cursor() as cursor:
            before = {}
            for table in ['chat_conversations', 'chat_messages', 'recognition_records']:
                cursor.execute('SELECT COUNT(*) AS n FROM ' + table)
                before[table] = cursor.fetchone()['n']
        content_store.initialize_tables(database)
        try:
            report = content_store.seed_content(database)
            database.commit()
        except Exception:
            database.rollback()
            raise
    with pymysql.connect(**config) as database, database.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) AS n FROM plant_catalog')
        report['stored_plants'] = cursor.fetchone()['n']
        cursor.execute('SELECT COUNT(*) AS n FROM science_articles')
        report['stored_articles'] = cursor.fetchone()['n']
        after = {}
        for table in before:
            cursor.execute('SELECT COUNT(*) AS n FROM ' + table)
            after[table] = cursor.fetchone()['n']
        if before != after:
            raise RuntimeError('迁移期间历史记录数量发生变化，请检查并发写入。')
        if report['stored_plants'] != 300:
            raise RuntimeError('植物图鉴导入后未包含 300 类资料。')
    report['history_counts_preserved'] = after
    destination = ROOT.parent / 'mysql-local/content-import-report.json'
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        migrate()
    except Exception as error:
        print(str(error) if isinstance(error, RuntimeError) else '内容导入失败，请检查数据库与源资料；未输出连接凭据。', file=sys.stderr)
        raise SystemExit(1)
