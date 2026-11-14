"""MySQL persistence for completed chat turns and successful image predictions."""
import hashlib
import json
import os
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pymysql
from dotenv import dotenv_values
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / '.env'
UPLOADS = ROOT / 'uploads' / 'recognition'


def configuration():
    values = {**dotenv_values(ENV_FILE, encoding='utf-8-sig'), **os.environ}
    enabled = str(values.get('MYSQL_ENABLED', 'false')).lower() in {'true', '1', 'yes'}
    try:
        port = int(values.get('MYSQL_PORT', '3306'))
        database = values.get('MYSQL_DATABASE', 'herb_platform')
        if not 1 <= port <= 65535 or not re.fullmatch(r'[a-zA-Z0-9_]{1,64}', database):
            raise ValueError()
    except (TypeError, ValueError):
        raise HTTPException(503, 'MySQL 配置无效，请检查后端 .env') from None
    return dict(enabled=enabled, host=values.get('MYSQL_HOST', '127.0.0.1'), port=port,
                user=values.get('MYSQL_USER', 'herb_app'), password=values.get('MYSQL_PASSWORD', ''),
                database=database)


def enabled():
    return configuration()['enabled']


def owner_hash(token):
    if not token or not re.fullmatch(r'[a-f0-9]{64}', token):
        raise HTTPException(401, '缺少有效的历史记录身份标识，请刷新页面后重试')
    return hashlib.sha256(token.encode()).hexdigest()


def connect():
    config = configuration()
    if not config.pop('enabled'):
        raise HTTPException(503, 'MySQL 历史记录尚未启用，请配置后端数据库')
    return pymysql.connect(**config, charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor,
                           connect_timeout=5, read_timeout=10, write_timeout=10, autocommit=False,
                           init_command="SET time_zone = '+00:00'")


@contextmanager
def connection(error_detail='无法保存或读取 MySQL 历史记录，请检查数据库服务'):
    database = None
    try:
        database = connect()
        yield database
        database.commit()
    except pymysql.MySQLError:
        if database:
            try:
                database.rollback()
            except pymysql.MySQLError:
                pass
        raise HTTPException(503, error_detail) from None
    except Exception:
        if database:
            try:
                database.rollback()
            except pymysql.MySQLError:
                pass
        raise
    finally:
        if database:
            try:
                database.close()
            except pymysql.MySQLError:
                pass


SCHEMA = [
    '''CREATE TABLE IF NOT EXISTS history_owners (
        owner_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
        user_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
        created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''',
    '''CREATE TABLE IF NOT EXISTS chat_conversations (
        id VARCHAR(80) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
        owner_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        herb_id VARCHAR(16), herb_name VARCHAR(120), identity_conflict BOOLEAN NOT NULL DEFAULT FALSE,
        title VARCHAR(255) NOT NULL DEFAULT '新对话',
        created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
        updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
        KEY idx_chat_owner_time (owner_hash, updated_at),
        FOREIGN KEY (owner_hash) REFERENCES history_owners(owner_hash)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''',
    '''CREATE TABLE IF NOT EXISTS chat_messages (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        conversation_id VARCHAR(80) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        sequence_no INT UNSIGNED NOT NULL, role ENUM('user','assistant') NOT NULL,
        content MEDIUMTEXT NOT NULL, model VARCHAR(100), references_json JSON,
        created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
        UNIQUE KEY uq_chat_sequence (conversation_id, sequence_no),
        FOREIGN KEY (conversation_id) REFERENCES chat_conversations(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''',
    '''CREATE TABLE IF NOT EXISTS recognition_records (
        id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
        owner_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        filename VARCHAR(255) NOT NULL, image_path VARCHAR(80) NOT NULL,
        mime_type VARCHAR(40) NOT NULL, image_sha256 CHAR(64) CHARACTER SET ascii NOT NULL,
        herb_id VARCHAR(16) NOT NULL, predicted_name VARCHAR(120) NOT NULL,
        confidence DOUBLE NOT NULL, result_json JSON NOT NULL,
        created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
        KEY idx_recognition_owner_time (owner_hash, created_at),
        FOREIGN KEY (owner_hash) REFERENCES history_owners(owner_hash)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''',
]


def initialize_schema():
    with connection() as database, database.cursor() as cursor:
        for statement in SCHEMA:
            cursor.execute(statement)


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def timestamp(value):
    return int(value.replace(tzinfo=timezone.utc).timestamp() * 1000)


def ensure_owner(cursor, owner):
    cursor.execute('INSERT IGNORE INTO history_owners(owner_hash) VALUES (%s)', (owner,))


def ensure_conversation(cursor, owner, conversation_id, context, title='新对话', created_at=None, updated_at=None):
    cursor.execute('SELECT * FROM chat_conversations WHERE id=%s', (conversation_id,))
    existing = cursor.fetchone()
    if existing:
        if existing['owner_hash'] != owner:
            raise HTTPException(404, '未找到该对话')
        if (existing['herb_id'] or None) != context.get('herbId'):
            raise HTTPException(409, '历史对话的植物参考不能更改，请开始新对话')
        return existing
    ensure_owner(cursor, owner)
    created_at = created_at or now()
    cursor.execute('''INSERT INTO chat_conversations
        (id,owner_hash,herb_id,herb_name,identity_conflict,title,created_at,updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''',
        (conversation_id, owner, context.get('herbId'), context.get('name'), bool(context.get('identityConflict')),
         title[:255], created_at, updated_at or created_at))
    return None


def create_conversation(owner, conversation_id, context):
    with connection() as database, database.cursor() as cursor:
        ensure_owner(cursor, owner)
        ensure_conversation(cursor, owner, conversation_id, context)


def list_conversations(owner, page=1, page_size=100, query=''):
    condition = 'c.owner_hash=%s'
    arguments = [owner]
    if query:
        pattern = '%' + query.replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%'
        condition += " AND (c.title LIKE %s ESCAPE '!' OR EXISTS (SELECT 1 FROM chat_messages m WHERE m.conversation_id=c.id AND m.content LIKE %s ESCAPE '!'))"
        arguments.extend([pattern, pattern])
    with connection() as database, database.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) AS total FROM chat_conversations c WHERE ' + condition, arguments)
        total = cursor.fetchone()['total']
        cursor.execute('SELECT c.* FROM chat_conversations c WHERE ' + condition +
            ' ORDER BY c.updated_at DESC,c.id LIMIT %s OFFSET %s', [*arguments, page_size, (page - 1) * page_size])
        rows = cursor.fetchall()
        messages = {}
        if rows:
            ids = [row['id'] for row in rows]
            cursor.execute('SELECT conversation_id,role,content,references_json FROM chat_messages WHERE conversation_id IN ('
                           + ','.join(['%s'] * len(ids)) + ') ORDER BY conversation_id,sequence_no', ids)
            for message in cursor.fetchall():
                value=dict(role=message['role'],content=message['content'])
                metadata=json.loads(message['references_json']) if message['references_json'] else None
                if isinstance(metadata,dict):
                    if message['role']=='user' and metadata.get('image_record_id'):value['image_record_id']=metadata['image_record_id']
                    if message['role']=='assistant':
                        value['tool_calls']=metadata.get('tool_calls',[])
                        # Recover attachments for older turns that only stored the image tool call.
                        previous=messages.get(message['conversation_id'],[])
                        for call in value['tool_calls']:
                            image_id=call.get('arguments',{}).get('image_record_id') if call.get('name')=='recognize_plant_image' and call.get('status')=='success' else None
                            if image_id and previous and previous[-1]['role']=='user' and not previous[-1].get('image_record_id'):
                                previous[-1]['image_record_id']=image_id
                messages.setdefault(message['conversation_id'], []).append(value)
        items = [dict(id=row['id'], context={key: value for key, value in dict(herbId=row['herb_id'], name=row['herb_name'],
                identityConflict=bool(row['identity_conflict'])).items() if value is not None}, messages=messages.get(row['id'], []),
                createdAt=timestamp(row['created_at']), updatedAt=timestamp(row['updated_at'])) for row in rows]
        return dict(items=items, total=total, page=page, page_size=page_size)


def import_conversations(owner, conversations):
    imported = 0
    with connection() as database, database.cursor() as cursor:
        # The owner row lock serializes idempotent imports from StrictMode or two tabs.
        ensure_owner(cursor, owner)
        for conversation in conversations:
            cursor.execute('SELECT owner_hash FROM chat_conversations WHERE id=%s', (conversation['id'],))
            existing = cursor.fetchone()
            if existing:
                if existing['owner_hash'] != owner:
                    raise HTTPException(404, '无法导入该对话')
                # Server records are authoritative; never overwrite a later completed turn.
                continue
            messages = conversation['messages']
            title = (messages[0]['content'] or '图片识别') if messages else '新对话'
            ensure_conversation(cursor, owner, conversation['id'], conversation['context'], title,
                datetime.fromtimestamp(conversation['createdAt'] / 1000, timezone.utc).replace(tzinfo=None),
                datetime.fromtimestamp(conversation['updatedAt'] / 1000, timezone.utc).replace(tzinfo=None))
            for index, message in enumerate(messages):
                cursor.execute('''INSERT INTO chat_messages(conversation_id,sequence_no,role,content,references_json)
                    VALUES (%s,%s,%s,%s,%s)''', (conversation['id'], index + 1, message['role'], message['content'],
                    json.dumps({'image_record_id':message['image_record_id']}) if message.get('image_record_id') else None))
            imported += 1
    return imported


class ChatLease:
    """A MySQL advisory lock prevents two answers from using the same stale history."""
    def __init__(self, database, conversation_id, herb_id, history):
        self.database, self.conversation_id, self.herb_id, self.history = database, conversation_id, herb_id, history

    def save(self, question, answer, model, references, tool_calls=None, image_record_id=None):
        with self.database.cursor() as cursor:
            cursor.execute('SELECT COALESCE(MAX(sequence_no),0) AS last FROM chat_messages WHERE conversation_id=%s', (self.conversation_id,))
            sequence = cursor.fetchone()['last']
            for offset, role, content in [(1, 'user', question), (2, 'assistant', answer)]:
                cursor.execute('''INSERT INTO chat_messages
                    (conversation_id,sequence_no,role,content,model,references_json) VALUES (%s,%s,%s,%s,%s,%s)''',
                    (self.conversation_id, sequence + offset, role, content, model,
                     json.dumps(dict(references=references,tool_calls=tool_calls) if tool_calls is not None else references,
                                ensure_ascii=False) if role == 'assistant' else (json.dumps({'image_record_id':image_record_id}) if image_record_id else None)))
            if not sequence:
                cursor.execute('UPDATE chat_conversations SET title=%s WHERE id=%s', (question[:255] or '图片识别', self.conversation_id))
            cursor.execute('UPDATE chat_conversations SET updated_at=%s WHERE id=%s', (now(), self.conversation_id))
        self.database.commit()


@contextmanager
def chat_lease(owner, conversation_id, context):
    lock_name = chat_lock_name(owner, conversation_id)
    with connection() as database:
        locked = False
        try:
            with database.cursor() as cursor:
                cursor.execute('SELECT GET_LOCK(%s,0) AS acquired', (lock_name,))
                locked = cursor.fetchone()['acquired'] == 1
                if not locked:
                    raise HTTPException(409, '该对话正在回答，请等待完成后再发送')
                ensure_conversation(cursor, owner, conversation_id, context)
                database.commit()
                cursor.execute('''SELECT role,content,references_json FROM chat_messages WHERE conversation_id=%s
                    ORDER BY sequence_no DESC LIMIT 12''', (conversation_id,))
                history = list(reversed(cursor.fetchall()))
                database.commit()
            yield ChatLease(database, conversation_id, context.get('herbId'), history)
        finally:
            if locked:
                with database.cursor() as cursor:
                    cursor.execute('SELECT RELEASE_LOCK(%s)', (lock_name,))


def chat_lock_name(owner, conversation_id):
    return 'chat:' + hashlib.sha256((owner + conversation_id).encode()).hexdigest()[:59]


def save_recognition(owner, filename, content, image_format, result):
    record_id = str(uuid.uuid4())
    suffix, mime = {'JPEG': ('.jpg', 'image/jpeg'), 'PNG': ('.png', 'image/png'), 'WEBP': ('.webp', 'image/webp')}[image_format]
    UPLOADS.mkdir(parents=True, exist_ok=True)
    path = UPLOADS / (record_id + suffix)
    try:
        path.write_bytes(content)
        with connection() as database, database.cursor() as cursor:
            ensure_owner(cursor, owner)
            # A prediction may finish after its visitor history has been claimed.
            cursor.execute('SELECT user_id FROM history_owners WHERE owner_hash=%s', (owner,))
            linked_user = cursor.fetchone()['user_id']
            if linked_user:
                cursor.execute('SELECT history_owner_hash FROM app_users WHERE id=%s', (linked_user,))
                account_owner = cursor.fetchone()
                if account_owner:
                    owner = account_owner['history_owner_hash']
            prediction = result['prediction']
            cursor.execute('''INSERT INTO recognition_records
                (id,owner_hash,filename,image_path,mime_type,image_sha256,herb_id,predicted_name,confidence,result_json)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (record_id, owner, Path((filename or 'plant').replace('\\', '/')).name[:255], path.name, mime,
                 hashlib.sha256(content).hexdigest(), prediction['herb_id'], prediction['name'],
                 prediction['confidence'], json.dumps(result, ensure_ascii=False)))
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return record_id


def list_recognitions(owner, query='', page=1, page_size=20):
    condition = 'owner_hash=%s'
    arguments = [owner]
    if query:
        # Escape wildcard characters so searches use the literal keyword.
        pattern = '%' + query.replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%'
        condition += " AND (predicted_name LIKE %s ESCAPE '!' OR filename LIKE %s ESCAPE '!')"
        arguments.extend([pattern, pattern])
    with connection() as database, database.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) AS total FROM recognition_records WHERE ' + condition, arguments)
        total = cursor.fetchone()['total']
        cursor.execute('SELECT id,filename,herb_id,predicted_name,confidence,result_json,created_at FROM recognition_records WHERE '
            + condition + ' ORDER BY created_at DESC,id LIMIT %s OFFSET %s', [*arguments, page_size, (page - 1) * page_size])
        items = [dict(id=row['id'], filename=row['filename'], createdAt=timestamp(row['created_at']),
                      result={**json.loads(row['result_json']), 'record_id': row['id'], 'saved': True}) for row in cursor.fetchall()]
        return dict(items=items, total=total, page=page, page_size=page_size)


def recognition_image(owner, record_id):
    with connection() as database, database.cursor() as cursor:
        cursor.execute('SELECT image_path,mime_type FROM recognition_records WHERE id=%s AND owner_hash=%s', (record_id, owner))
        row = cursor.fetchone()
    if not row:
        raise HTTPException(404, '未找到该识别记录')
    path = UPLOADS / row['image_path']
    if path.parent.resolve() != UPLOADS.resolve() or not path.is_file():
        raise HTTPException(404, '该识别记录的原图暂不可用')
    return path, row['mime_type']


def health():
    if not enabled():
        return dict(enabled=False, status='disabled')
    try:
        with connection() as database, database.cursor() as cursor:
            cursor.execute('SELECT 1 FROM history_owners LIMIT 1')
        return dict(enabled=True, status='ready')
    except HTTPException:
        return dict(enabled=True, status='unavailable')
