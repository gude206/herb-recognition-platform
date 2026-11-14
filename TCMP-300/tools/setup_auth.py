"""Initialize auth and seed an administrator with a private local random password."""
import argparse
import os
import secrets
import subprocess
import sys
from pathlib import Path

import pymysql
from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import auth_store
import admin_articles
import history_store
from tools.local_mysql import credentials


def initialize_database(database):
    auth_store.initialize_schema(database)
    admin_articles.initialize_schema(database)


def protect_credentials(file):
    if os.name != 'nt':
        file.chmod(0o600)
        return
    # Remove inherited access; only the current Windows account and SYSTEM may read it.
    escaped = str(file.resolve()).replace("'", "''")
    command = f"""$ErrorActionPreference = 'Stop'
$credentialFile = '{escaped}'
$credentialSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
& icacls.exe $credentialFile /inheritance:r /grant:r "*${{credentialSid}}:(F)" '*S-1-5-18:(F)' | Out-Null
if ($LASTEXITCODE -ne 0) {{ throw 'Cannot protect credential file' }}
foreach ($existingRule in [System.IO.File]::GetAccessControl($credentialFile).Access) {{
    $existingSid = $existingRule.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
    if ($existingSid -notin @($credentialSid, 'S-1-5-18')) {{
        & icacls.exe $credentialFile /remove "*$existingSid" | Out-Null
        if ($LASTEXITCODE -ne 0) {{ throw 'Cannot remove credential access' }}
    }}
}}
"""
    result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', command], capture_output=True,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError('管理员凭据文件权限设置失败，请限制 mysql-local/admin-login.env 的读取权限。')


def setup(account='admin'):
    config = history_store.configuration()
    if config['host'] != '127.0.0.1' or config['port'] != credentials()['port']:
        raise RuntimeError('本机初始化工具仅用于本项目独立 MySQL 实例。')
    values = dotenv_values(ROOT / '.env')
    if not values.get('AUTH_CSRF_SECRET'):
        set_key(ROOT / '.env', 'AUTH_CSRF_SECRET', secrets.token_hex(32), quote_mode='always')
    if not values.get('AUTH_COOKIE_SECURE'):
        set_key(ROOT / '.env', 'AUTH_COOKIE_SECURE', 'false', quote_mode='always')
    account, key = auth_store.normalize_account(account)
    with pymysql.connect(**{**credentials(), 'database': config['database'], 'autocommit': False,
                            'cursorclass': pymysql.cursors.DictCursor}) as database:
        initialize_database(database)
        with database.cursor() as cursor:
            cursor.execute('SELECT role FROM app_users WHERE account_key=%s', (key,))
            existing = cursor.fetchone()
        if existing:
            if existing['role'] != 'admin':
                raise RuntimeError('指定用户名已是普通用户，未自动提升权限。请选择其他管理员用户名。')
            print('认证表已升级，已有管理员密码保持不变。')
        else:
            password = secrets.token_urlsafe(24)
            auth_store.create_user(database, account, password, '管理员', role='admin')
            database.commit()
            file = ROOT.parent / 'mysql-local/admin-login.env'
            file.write_text('ADMIN_ACCOUNT=' + account + '\nADMIN_PASSWORD=' + password + '\n', encoding='utf-8')
            print('管理员已创建，初始登录信息仅保存在 mysql-local/admin-login.env。')
    saved_credentials = ROOT.parent / 'mysql-local/admin-login.env'
    if saved_credentials.exists():
        protect_credentials(saved_credentials)
    set_key(ROOT / '.env', 'AUTH_ADMIN_ACCOUNT', account, quote_mode='always')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--account', default='admin')
    arguments = parser.parse_args()
    try:
        setup(arguments.account)
    except Exception as error:
        print(str(error) if isinstance(error, RuntimeError) else '认证初始化失败；未输出密码或数据库凭据。', file=sys.stderr)
        raise SystemExit(1)
