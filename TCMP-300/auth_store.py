"""Account passwords, revocable sessions, and one-time visitor-history claims."""
import hashlib
import hmac
import os
import re
import secrets
import unicodedata
import uuid
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from dotenv import dotenv_values
from fastapi import HTTPException
import pymysql

import history_store

COOKIE_NAME = 'herb_session'
PASSWORDS = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
DUMMY_HASH = PASSWORDS.hash('unused-account-password-verification')

SCHEMA = [
    '''CREATE TABLE IF NOT EXISTS app_users (
        id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
        account VARCHAR(40) NOT NULL, account_key VARCHAR(80) NOT NULL UNIQUE,
        display_name VARCHAR(80) NOT NULL, password_hash VARCHAR(255) NOT NULL,
        role ENUM('user','admin') NOT NULL DEFAULT 'user', active BOOLEAN NOT NULL DEFAULT TRUE,
        history_owner_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
        created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
        FOREIGN KEY (history_owner_hash) REFERENCES history_owners(owner_hash)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_cs''',
    '''CREATE TABLE IF NOT EXISTS auth_sessions (
        token_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
        user_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
        expires_at DATETIME(3) NOT NULL, revoked_at DATETIME(3),
        KEY idx_session_user (user_id), KEY idx_session_expiry (expires_at),
        FOREIGN KEY (user_id) REFERENCES app_users(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''',
    '''CREATE TABLE IF NOT EXISTS auth_attempts (
        attempt_key VARCHAR(80) CHARACTER SET ascii PRIMARY KEY,
        window_start DATETIME(3) NOT NULL, attempts INT UNSIGNED NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''',
    '''CREATE TABLE IF NOT EXISTS user_profiles (
        user_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
        bio VARCHAR(300) NOT NULL DEFAULT '', avatar MEDIUMBLOB,
        avatar_version BIGINT UNSIGNED NOT NULL DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES app_users(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''',
]


def settings():
    return {**dotenv_values(history_store.ENV_FILE, encoding='utf-8-sig'), **os.environ}


def normalize_account(account):
    account = unicodedata.normalize('NFKC', account).strip()
    if not re.fullmatch(r'[A-Za-z0-9_\-\u4e00-\u9fff]{3,40}', account):
        raise HTTPException(422, '用户名须为 3—40 位中文、字母、数字、下划线或短横线')
    return account, account.casefold()


def initialize_schema(database):
    with database.cursor() as cursor:
        cursor.execute('SHOW COLUMNS FROM history_owners LIKE %s', ('user_id',))
        if not cursor.fetchone():
            cursor.execute('ALTER TABLE history_owners ADD COLUMN user_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL')
        for statement in SCHEMA:
            cursor.execute(statement)


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token(token):
    secret = settings().get('AUTH_CSRF_SECRET', '')
    if len(secret) < 32:
        raise HTTPException(503, '认证配置尚未初始化，请运行本机认证初始化工具')
    return hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()


def verify_password(encoded, password):
    try:
        return PASSWORDS.verify(encoded, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def public_user(user):
    version = user.get('avatar_version', 0) or 0
    return dict(id=user['id'], account=user['account'], name=user['display_name'], role=user['role'],
                avatar_url=f"/api/v1/auth/me/avatar?v={version}&u={user['id']}" if version else None)


def session_user(token):
    if not token or not re.fullmatch(r'[a-f0-9]{64}', token):
        return None
    with history_store.connection(error_detail='无法读取登录状态，请检查 MySQL 服务') as database, database.cursor() as cursor:
        cursor.execute('''SELECT u.*,CASE WHEN p.avatar IS NULL THEN 0 ELSE p.avatar_version END AS avatar_version
            FROM auth_sessions s JOIN app_users u ON u.id=s.user_id
            LEFT JOIN user_profiles p ON p.user_id=u.id
            WHERE s.token_hash=%s AND s.revoked_at IS NULL AND s.expires_at>UTC_TIMESTAMP(3) AND u.active=TRUE''', (hash_token(token),))
        return cursor.fetchone()


def create_user(database, account, password, display_name='', role='user'):
    account, account_key = normalize_account(account)
    with database.cursor() as cursor:
        cursor.execute('SELECT id FROM app_users WHERE account_key=%s', (account_key,))
        if cursor.fetchone():
            raise HTTPException(409, '该用户名已注册，请使用登录入口')
        user_id, owner = str(uuid.uuid4()), secrets.token_hex(32)
        history_store.ensure_owner(cursor, owner)
        cursor.execute('UPDATE history_owners SET user_id=%s WHERE owner_hash=%s', (user_id, owner))
        encoded = PASSWORDS.hash(password)
        try:
            cursor.execute('''INSERT INTO app_users(id,account,account_key,display_name,password_hash,role,history_owner_hash)
                VALUES (%s,%s,%s,%s,%s,%s,%s)''',
                (user_id, account, account_key, display_name.strip() or account, encoded, role, owner))
        except pymysql.IntegrityError as error:
            if error.args[0] == 1062:
                raise HTTPException(409, '该用户名已注册，请使用登录入口') from None
            raise
        return dict(id=user_id, account=account, account_key=account_key, display_name=display_name.strip() or account,
                    password_hash=encoded, role=role, history_owner_hash=owner)


def create_session(database, user, remember=False):
    token = secrets.token_hex(32)
    duration = 30 * 86400 if remember and user['role'] == 'user' else 8 * 3600
    with database.cursor() as cursor:
        cursor.execute('INSERT INTO auth_sessions(token_hash,user_id,expires_at) VALUES (%s,%s,%s)',
                       (hash_token(token), user['id'], history_store.now() + timedelta(seconds=duration)))
    return token, duration


def revoke_session(token):
    if not token:
        return
    with history_store.connection() as database, database.cursor() as cursor:
        cursor.execute('UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP(3) WHERE token_hash=%s', (hash_token(token),))


def claim_guest_history(database, user, guest_token, locks):
    result = dict(conversations=0, recognitions=0, claimed=False)
    if not guest_token:
        return result
    guest = history_store.owner_hash(guest_token)
    with database.cursor() as cursor:
        cursor.execute('SELECT * FROM history_owners WHERE owner_hash=%s FOR UPDATE', (guest,))
        previous = cursor.fetchone()
        if not previous or previous['user_id']:
            # A claimed browser token must never be reused to access another account.
            return result
        cursor.execute('SELECT id FROM chat_conversations WHERE owner_hash=%s ORDER BY id', (guest,))
        for conversation in cursor.fetchall():
            lock = history_store.chat_lock_name(guest, conversation['id'])
            cursor.execute('SELECT GET_LOCK(%s,0) AS acquired', (lock,))
            if cursor.fetchone()['acquired'] != 1:
                raise HTTPException(409, '访客对话仍在回答，请等待完成后关联历史，或取消关联选项后登录')
            locks.append(lock)
        cursor.execute('UPDATE chat_conversations SET owner_hash=%s WHERE owner_hash=%s', (user['history_owner_hash'], guest))
        result['conversations'] = cursor.rowcount
        cursor.execute('UPDATE recognition_records SET owner_hash=%s WHERE owner_hash=%s', (user['history_owner_hash'], guest))
        result['recognitions'] = cursor.rowcount
        cursor.execute('UPDATE history_owners SET user_id=%s WHERE owner_hash=%s', (user['id'], guest))
        result['claimed'] = True
    return result


def release_claim_locks(database, locks):
    with database.cursor() as cursor:
        for lock in reversed(locks):
            cursor.execute('SELECT RELEASE_LOCK(%s)', (lock,))


def reserve_attempt(account_key, ip, kind='login'):
    current = history_store.now()
    keys = [('ip:' + hash_token(ip), 30), ('account:' + hash_token(account_key), 5)] if kind == 'login' else [('signup:' + hash_token(ip), 20)]
    blocked = False
    with history_store.connection() as database, database.cursor() as cursor:
        for key, limit in keys:
            cursor.execute('''INSERT INTO auth_attempts(attempt_key,window_start,attempts) VALUES (%s,%s,1)
                ON DUPLICATE KEY UPDATE attempts=IF(window_start<%s,1,attempts+1),window_start=IF(window_start<%s,%s,window_start)''',
                (key, current, current - timedelta(minutes=15), current - timedelta(minutes=15), current))
            cursor.execute('SELECT attempts FROM auth_attempts WHERE attempt_key=%s', (key,))
            blocked = blocked or cursor.fetchone()['attempts'] > limit
    if blocked:
        raise HTTPException(429, '尝试次数过多，请在 15 分钟后重试')


def clear_account_attempts(database, account_key):
    with database.cursor() as cursor:
        cursor.execute('UPDATE auth_attempts SET attempts=0 WHERE attempt_key=%s', ('account:' + hash_token(account_key),))
