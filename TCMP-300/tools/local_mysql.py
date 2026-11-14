"""Manage an isolated local MySQL instance without changing Windows services."""
import argparse
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pymysql
from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT.parent / 'mysql-local'
STATE = LOCAL / 'instance.json'
ADMIN = LOCAL / '.admin.env'


def ascii_directory():
    # A junction leaves all actual database files inside the ignored project folder.
    # MySQL 8.4's Windows filesystem layer needs an ASCII path for its data directory.
    alias = Path(tempfile.gettempdir()) / ('herb-mysql-' + hashlib.sha256(str(LOCAL).encode()).hexdigest()[:12])
    if alias.exists():
        if alias.resolve() != LOCAL.resolve():
            raise RuntimeError('MySQL 路径别名已被其他目录使用。')
        return alias
    escaped_alias = str(alias).replace("'", "''")
    escaped_target = str(LOCAL).replace("'", "''")
    command = f"New-Item -ItemType Junction -Path '{escaped_alias}' -Target '{escaped_target}' | Out-Null"
    result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', command], capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode or alias.resolve() != LOCAL.resolve():
        raise RuntimeError('无法创建项目数据库的兼容路径。')
    return alias


def write_options(mysqld, port, alias):
    (LOCAL / 'my.ini').write_text('[mysqld]\n' + f'basedir="{Path(mysqld).parent.parent.as_posix()}"\n'
        + f'datadir="{(alias / "data").as_posix()}"\nport={port}\nbind-address=127.0.0.1\n'
        + f'log-error="{(alias / "mysql.err.log").as_posix()}"\n'
        + f'innodb-log-group-home-dir="{(alias / "data").as_posix()}"\n'
        + f'innodb-undo-directory="{(alias / "data").as_posix()}"\n'
        + "mysqlx=OFF\nskip-name-resolve\ncharacter-set-server=utf8mb4\ndefault-time-zone='+00:00'\n"
        + 'innodb-buffer-pool-size=128M\nmax-connections=40\n', encoding='utf-8')


def credentials():
    values = dotenv_values(ADMIN)
    return dict(host='127.0.0.1', port=int(values['MYSQL_PORT']), user='root',
                password=values['MYSQL_ROOT_PASSWORD'], charset='utf8mb4', autocommit=True,
                connect_timeout=2, read_timeout=5, write_timeout=5)


def read_state():
    state = json.loads(STATE.read_text(encoding='utf-8'))
    # Only ever manage this project's own option file and binary.
    if Path(state['option_file']).resolve() != (LOCAL / 'my.ini').resolve():
        raise RuntimeError('MySQL 状态路径不属于当前项目。')
    return state


def running():
    try:
        with pymysql.connect(**credentials()) as database, database.cursor() as cursor:
            cursor.execute('SELECT @@datadir')
            directory = cursor.fetchone()[0]
            if Path(directory).resolve() != (LOCAL / 'data').resolve():
                raise RuntimeError('端口上运行的是其他 MySQL 实例。')
        return True
    except pymysql.MySQLError:
        return False


def wait_ready(process):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('项目 MySQL 启动失败，请检查 mysql-local/mysql.err.log。')
        if running():
            return
        time.sleep(.5)
    raise RuntimeError('项目 MySQL 未及时就绪，请检查 mysql-local/mysql.err.log。')


def launch(state, init_file=None):
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', state['port']))
        except OSError:
            raise RuntimeError('MySQL 端口已占用，未启动或停止其他实例。') from None
    alias = ascii_directory()
    write_options(state['mysqld'], state['port'], alias)
    command = [state['mysqld'], '--defaults-file=' + str(alias / 'my.ini')]
    if init_file:
        command.append('--init-file=' + str(alias / 'bootstrap.sql'))
    output = (LOCAL / 'process.log').open('ab')
    try:
        process = subprocess.Popen(command, cwd=alias, stdout=output, stderr=output,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    finally:
        output.close()
    wait_ready(process)
    state['pid'] = process.pid
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')


def start():
    state = read_state()
    if running():
        print('项目 MySQL 已运行：127.0.0.1:' + str(state['port']))
        return
    launch(state)
    print('项目 MySQL 已就绪：127.0.0.1:' + str(state['port']))


def stop():
    read_state()
    if not running():
        print('项目 MySQL 已停止。')
        return
    database = pymysql.connect(**credentials())
    try:
        with database.cursor() as cursor:
            cursor.execute('SHUTDOWN')
    finally:
        database.close()
    print('项目 MySQL 已安全关闭，数据保留。')


def setup(mysqld, port):
    if STATE.exists():
        if (LOCAL / 'bootstrap.sql').exists():
            import re
            matches = re.findall(r"'herb_app'@'127.0.0.1'.*? BY '([^']+)'", (LOCAL / 'bootstrap.sql').read_text(encoding='utf-8'))
            if len(matches) != 1:
                raise RuntimeError('现有初始化记录不完整，未更改数据。')
            finish_setup(read_state(), matches[0])
            return
        start()
        return
    if (LOCAL / 'data').exists():
        # A previous initialization can be resumed only with this project's bootstrap files.
        if not ADMIN.exists() or not (LOCAL / 'bootstrap.sql').exists() or not (LOCAL / 'my.ini').exists():
            raise RuntimeError('已存在 MySQL 数据目录但没有实例状态，请先检查；未覆盖现有数据。')
        import re
        saved = dotenv_values(ADMIN)
        matches = re.findall(r"'herb_app'@'127.0.0.1'.*? BY '([^']+)'", (LOCAL / 'bootstrap.sql').read_text(encoding='utf-8'))
        if int(saved.get('MYSQL_PORT', '0')) != port or len(matches) != 1:
            raise RuntimeError('现有初始化记录不匹配，未更改数据。')
        state = dict(mysqld=str(Path(mysqld).resolve()), option_file=str(LOCAL / 'my.ini'), port=port)
        finish_setup(state, matches[0])
        return
    mysqld = Path(mysqld).resolve()
    if not mysqld.is_file():
        raise RuntimeError('请指定已安装的 MySQL mysqld.exe 路径。')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))
    LOCAL.mkdir(parents=True, exist_ok=True)
    root_password, app_password = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    ADMIN.write_text(f'MYSQL_PORT={port}\nMYSQL_ROOT_PASSWORD={root_password}\n', encoding='utf-8')
    option_file = LOCAL / 'my.ini'
    alias = ascii_directory()
    write_options(mysqld, port, alias)
    with (LOCAL / 'initialize.log').open('wb') as log:
        # Initialization does not open a network listener. The init file sets credentials before normal startup.
        result = subprocess.run([str(mysqld), '--no-defaults', '--initialize-insecure',
            '--basedir=' + str(mysqld.parent.parent), '--datadir=' + str(alias / 'data')], stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode:
        raise RuntimeError('MySQL 初始化失败，请检查 mysql-local/initialize.log。')
    init_file = LOCAL / 'bootstrap.sql'
    init_file.write_text(f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{root_password}';\n"
        + f"CREATE USER IF NOT EXISTS 'root'@'127.0.0.1' IDENTIFIED WITH caching_sha2_password BY '{root_password}';\n"
        + "GRANT ALL PRIVILEGES ON *.* TO 'root'@'127.0.0.1' WITH GRANT OPTION;\n"
        + "CREATE DATABASE IF NOT EXISTS herb_platform CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;\n"
        + f"CREATE USER IF NOT EXISTS 'herb_app'@'127.0.0.1' IDENTIFIED BY '{app_password}';\n"
        + "GRANT SELECT,INSERT,UPDATE ON herb_platform.* TO 'herb_app'@'127.0.0.1';\n", encoding='utf-8')
    state = dict(mysqld=str(mysqld), option_file=str(option_file), port=port)
    finish_setup(state, app_password)


def finish_setup(state, app_password):
    init_file = LOCAL / 'bootstrap.sql'
    if not running():
        launch(state, init_file)
    try:
        admin_config = {**credentials(), 'database': 'herb_platform', 'autocommit': False,
                        'cursorclass': pymysql.cursors.DictCursor, 'init_command': "SET time_zone = '+00:00'"}
        sys.path.insert(0, str(ROOT))
        import history_store
        import content_store
        with pymysql.connect(**admin_config) as database, database.cursor() as cursor:
            for statement in history_store.SCHEMA:
                cursor.execute(statement)
            content_store.initialize_tables(database)
            content_store.seed_content(database)
            database.commit()
        for key, value in dict(MYSQL_ENABLED='true', MYSQL_HOST='127.0.0.1', MYSQL_PORT=str(state['port']),
            MYSQL_USER='herb_app', MYSQL_PASSWORD=app_password, MYSQL_DATABASE='herb_platform', MYSQL_MANAGED_LOCAL='true').items():
            set_key(ROOT / '.env', key, value, quote_mode='always')
    finally:
        init_file.unlink(missing_ok=True)
    print('独立 MySQL 实例、历史表和内容资料已创建；数据库凭据仅写入本地忽略文件。')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['setup', 'start', 'stop', 'status'])
    parser.add_argument('--mysqld', default=r'D:\MySQL\MySQL Server 8.4\bin\mysqld.exe')
    parser.add_argument('--port', type=int, default=3307)
    arguments = parser.parse_args()
    try:
        if arguments.action == 'setup':
            setup(arguments.mysqld, arguments.port)
            sys.path.insert(0, str(ROOT))
            from tools.setup_auth import setup as setup_accounts
            setup_accounts(dotenv_values(ROOT / '.env').get('AUTH_ADMIN_ACCOUNT') or 'admin')
        elif arguments.action == 'start':
            start()
        elif arguments.action == 'stop':
            stop()
        else:
            print('ready' if STATE.exists() and running() else 'stopped')
    except Exception as error:
        # Do not print driver messages or connection details: they may contain credentials.
        print(str(error) if isinstance(error, RuntimeError) else 'MySQL 管理操作失败，请检查本地配置和日志。', file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
