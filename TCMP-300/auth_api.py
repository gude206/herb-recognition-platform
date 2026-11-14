"""JSON account login and HttpOnly-cookie sessions with CSRF and role checks."""
import hmac
from typing import Literal
import re
import io
import warnings

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field, field_validator
from PIL import Image, ImageOps, UnidentifiedImageError

import auth_store
import history_store

router = APIRouter(prefix='/api/v1/auth', tags=['用户与管理员认证'])


def check_origin(request):
    origin = request.headers.get('origin')
    if not origin:
        return
    allowed = {'http://localhost:5173', 'http://127.0.0.1:5173', 'http://localhost:4173', 'http://127.0.0.1:4173',
               str(request.base_url).rstrip('/')}
    configured = auth_store.settings().get('TCMP_FRONTEND_ORIGIN', '')
    if configured:
        allowed.add(configured)
    if origin not in allowed:
        raise HTTPException(403, '请求来源不被允许')


def optional_user(request: Request, strict=True):
    token = request.cookies.get(auth_store.COOKIE_NAME)
    if not token:
        return None
    user = auth_store.session_user(token)
    if not user and strict:
        raise HTTPException(401, '登录已过期，请重新登录')
    return user


def check_csrf(request, user):
    if not user or request.method in {'GET', 'HEAD', 'OPTIONS'}:
        return
    check_origin(request)
    supplied = request.headers.get('x-csrf-token', '')
    expected = auth_store.csrf_token(request.cookies.get(auth_store.COOKIE_NAME, ''))
    if not re.fullmatch(r'[a-f0-9]{64}', supplied) or not hmac.compare_digest(supplied, expected):
        raise HTTPException(403, '登录请求校验失败，请刷新页面后重试')


def current_user(request: Request):
    user = optional_user(request)
    if not user:
        raise HTTPException(401, '请先登录')
    check_csrf(request, user)
    return user


def administrator(user=Depends(current_user)):
    if user['role'] != 'admin':
        raise HTTPException(403, '该操作仅限管理员')
    return user


def request_history_owner(request: Request, x_history_token: str | None = Header(default=None)):
    user = optional_user(request)
    if user:
        check_csrf(request, user)
        return user['history_owner_hash']
    owner = history_store.owner_hash(x_history_token)
    with history_store.connection() as database, database.cursor() as cursor:
        cursor.execute('SELECT user_id FROM history_owners WHERE owner_hash=%s', (owner,))
        row = cursor.fetchone()
        if row and row['user_id']:
            raise HTTPException(401, '这份历史已关联账号，请登录对应账号查看')
    return owner


def set_session(response, token, duration):
    secure = str(auth_store.settings().get('AUTH_COOKIE_SECURE', 'false')).lower() in {'true', '1', 'yes'}
    response.set_cookie(auth_store.COOKIE_NAME, token, max_age=duration, httponly=True, secure=secure, samesite='lax', path='/')
    response.headers['Cache-Control'] = 'no-store'


class Registration(BaseModel):
    model_config = ConfigDict(extra='forbid')
    account: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=12, max_length=128)
    name: str = Field(default='', max_length=80)
    claim_guest_history: bool = True


class Login(BaseModel):
    model_config = ConfigDict(extra='forbid')
    account: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=1, max_length=128)
    role: Literal['user', 'admin'] = 'user'
    remember: bool = False
    claim_guest_history: bool = True


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=80)
    bio: str = Field(default='', max_length=300)

    @field_validator('name', 'bio')
    @classmethod
    def clean_text(cls, value, info):
        value = value.strip()
        if info.field_name == 'name' and not value:
            raise ValueError('昵称不能为空')
        if any(ord(char) < 32 and char not in '\n\t' for char in value):
            raise ValueError('资料包含无效字符')
        return value


def profile_data(user):
    with history_store.connection() as database, database.cursor() as cursor:
        cursor.execute('SELECT bio FROM user_profiles WHERE user_id=%s', (user['id'],))
        profile = cursor.fetchone() or {}
        cursor.execute('SELECT created_at FROM app_users WHERE id=%s', (user['id'],))
        created = cursor.fetchone()['created_at']
        cursor.execute('SELECT COUNT(*) AS n FROM chat_conversations WHERE owner_hash=%s', (user['history_owner_hash'],))
        chats = cursor.fetchone()['n']
        cursor.execute('SELECT COUNT(*) AS n FROM recognition_records WHERE owner_hash=%s', (user['history_owner_hash'],))
        recognitions = cursor.fetchone()['n']
    return dict(user=auth_store.public_user(user), bio=profile.get('bio', ''),
                created_at=created.isoformat() + 'Z', stats=dict(conversations=chats, recognitions=recognitions))


@router.get('/me/profile')
def get_profile(response: Response, user=Depends(current_user)):
    response.headers['Cache-Control'] = 'private, no-store'
    return profile_data(user)


@router.patch('/me/profile')
def update_profile(payload: ProfileUpdate, response: Response, user=Depends(current_user)):
    with history_store.connection() as database, database.cursor() as cursor:
        cursor.execute('UPDATE app_users SET display_name=%s WHERE id=%s', (payload.name, user['id']))
        cursor.execute('''INSERT INTO user_profiles(user_id,bio) VALUES (%s,%s)
            ON DUPLICATE KEY UPDATE bio=%s''', (user['id'], payload.bio, payload.bio))
    response.headers['Cache-Control'] = 'private, no-store'
    return profile_data({**user, 'display_name': payload.name})


def normalized_avatar(content):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as source:
                if source.format not in {'JPEG', 'PNG', 'WEBP'}:
                    raise HTTPException(422, '头像仅支持 JPG、PNG、WEBP 图片')
                if min(source.size) < 1 or max(source.size) > 4096 or source.width * source.height > 8_000_000:
                    raise HTTPException(413, '头像分辨率过大，请缩小后上传')
                image = ImageOps.exif_transpose(source).convert('RGBA')
                image = ImageOps.fit(image, (256, 256), method=Image.Resampling.LANCZOS)
                output = io.BytesIO()
                image.save(output, format='WEBP', quality=88)
                return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise HTTPException(422, '无法读取头像，请选择有效的图片') from None


@router.put('/me/avatar')
def upload_avatar(response: Response, file: UploadFile = File(...), user=Depends(current_user)):
    content = file.file.read(2 * 1024 * 1024 + 1)
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(413, '头像不能超过 2MB')
    encoded = normalized_avatar(content)
    with history_store.connection() as database, database.cursor() as cursor:
        cursor.execute('''INSERT INTO user_profiles(user_id,avatar,avatar_version) VALUES (%s,%s,1)
            ON DUPLICATE KEY UPDATE avatar=%s,avatar_version=avatar_version+1''', (user['id'], encoded, encoded))
        cursor.execute('SELECT avatar_version FROM user_profiles WHERE user_id=%s', (user['id'],))
        version = cursor.fetchone()['avatar_version']
    response.headers['Cache-Control'] = 'private, no-store'
    return dict(user=auth_store.public_user({**user, 'avatar_version': version}))


@router.get('/me/avatar')
def get_avatar(user=Depends(current_user)):
    with history_store.connection() as database, database.cursor() as cursor:
        cursor.execute('SELECT avatar FROM user_profiles WHERE user_id=%s', (user['id'],))
        row = cursor.fetchone()
    if not row or not row['avatar']:
        raise HTTPException(404, '尚未设置头像')
    return Response(bytes(row['avatar']), media_type='image/webp',
                    headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@router.delete('/me/avatar')
def delete_avatar(response: Response, user=Depends(current_user)):
    with history_store.connection() as database, database.cursor() as cursor:
        cursor.execute('UPDATE user_profiles SET avatar=NULL,avatar_version=avatar_version+1 WHERE user_id=%s', (user['id'],))
    response.headers['Cache-Control'] = 'private, no-store'
    return dict(user=auth_store.public_user({**user, 'avatar_version': 0}))


@router.get('/me')
def me(request: Request, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    user = optional_user(request, strict=False)
    if not user:
        if request.cookies.get(auth_store.COOKIE_NAME):
            response.delete_cookie(auth_store.COOKIE_NAME, path='/')
        return dict(authenticated=False, user=None, csrf_token=None)
    return dict(authenticated=True, user=auth_store.public_user(user), csrf_token=auth_store.csrf_token(request.cookies[auth_store.COOKIE_NAME]))


@router.post('/register', status_code=201)
def register(payload: Registration, request: Request, response: Response, x_history_token: str | None = Header(default=None)):
    check_origin(request)
    auth_store.csrf_token('configuration-check')
    existing = optional_user(request, strict=False)
    if existing:
        check_csrf(request, existing)
        raise HTTPException(409, '请先退出当前账号，再注册新账号')
    account, account_key = auth_store.normalize_account(payload.account)
    reserved = auth_store.settings().get('AUTH_ADMIN_ACCOUNT', 'admin').casefold()
    if account_key == reserved:
        raise HTTPException(409, '该用户名保留给本机管理员')
    auth_store.reserve_attempt(account_key, request.client.host if request.client else 'local', kind='signup')
    with history_store.connection() as database:
        locks = []
        try:
            user = auth_store.create_user(database, account, payload.password, payload.name)
            claimed = auth_store.claim_guest_history(database, user, x_history_token, locks) if payload.claim_guest_history else dict(claimed=False, conversations=0, recognitions=0)
            token, duration = auth_store.create_session(database, user)
            database.commit()
        finally:
            auth_store.release_claim_locks(database, locks)
    set_session(response, token, duration)
    return dict(authenticated=True, user=auth_store.public_user(user), csrf_token=auth_store.csrf_token(token), claimed=claimed)


@router.post('/login')
def login(payload: Login, request: Request, response: Response, x_history_token: str | None = Header(default=None)):
    check_origin(request)
    auth_store.csrf_token('configuration-check')
    existing = optional_user(request, strict=False)
    check_csrf(request, existing)
    _, account_key = auth_store.normalize_account(payload.account)
    auth_store.reserve_attempt(account_key, request.client.host if request.client else 'local')
    with history_store.connection() as database, database.cursor() as cursor:
        cursor.execute('''SELECT u.*,CASE WHEN p.avatar IS NULL THEN 0 ELSE p.avatar_version END AS avatar_version
            FROM app_users u LEFT JOIN user_profiles p ON p.user_id=u.id WHERE u.account_key=%s''', (account_key,))
        user = cursor.fetchone()
        if not auth_store.verify_password(user['password_hash'] if user else auth_store.DUMMY_HASH, payload.password) or not user or not user['active']:
            raise HTTPException(401, '用户名或密码错误')
        if user['role'] != payload.role:
            raise HTTPException(403, '请使用与账号身份对应的登录入口')
        if auth_store.PASSWORDS.check_needs_rehash(user['password_hash']):
            cursor.execute('UPDATE app_users SET password_hash=%s WHERE id=%s', (auth_store.PASSWORDS.hash(payload.password), user['id']))
        locks = []
        try:
            claimed = auth_store.claim_guest_history(database, user, x_history_token, locks) if payload.claim_guest_history else dict(claimed=False, conversations=0, recognitions=0)
            if request.cookies.get(auth_store.COOKIE_NAME):
                cursor.execute('UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP(3) WHERE token_hash=%s', (auth_store.hash_token(request.cookies[auth_store.COOKIE_NAME]),))
            token, duration = auth_store.create_session(database, user, payload.remember)
            auth_store.clear_account_attempts(database, account_key)
            database.commit()
        finally:
            auth_store.release_claim_locks(database, locks)
    set_session(response, token, duration)
    return dict(authenticated=True, user=auth_store.public_user(user), csrf_token=auth_store.csrf_token(token), claimed=claimed)


@router.post('/logout')
def logout(request: Request, response: Response):
    user = optional_user(request, strict=False)
    if user:
        check_csrf(request, user)
        auth_store.revoke_session(request.cookies.get(auth_store.COOKIE_NAME))
    response.delete_cookie(auth_store.COOKIE_NAME, path='/')
    response.headers['Cache-Control'] = 'no-store'
    return dict(authenticated=False, user=None, csrf_token=None)
