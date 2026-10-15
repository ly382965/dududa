"""First-run setup inside Docker; never reads the developer's runtime directory."""
from __future__ import annotations

import copy
import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path('/opt/dududa/repository')
DATA = Path('/AstrBot/data')
STATE = Path('/var/lib/dududa')
NAPCAT = Path('/app/napcat/config')
LOGIN = DATA / 'private/quickstart-login.json'
sys.path.insert(0, str(REPO / 'ops/cli'))
sys.path.insert(0, '/AstrBot')


def private_write(path: Path, text: str, *, uid: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    path.chmod(0o600)
    os.chown(path, uid, uid)


def write_json(path: Path, value: object, *, uid: int = 0) -> None:
    private_write(path, json.dumps(value, ensure_ascii=False, indent=2) + '\n', uid=uid)


def prepare() -> None:
    command_path = DATA / 'cmd_config.json'
    # Importing AstrBot may itself create its default config. Remember whether
    # the user already had one before importing, so first-run settings still apply.
    first_install = not command_path.exists()
    from astrbot.core.config.default import DEFAULT_CONFIG
    from astrbot.core.utils.auth_password import hash_dashboard_password, hash_md5_dashboard_password

    os.umask(0o077)
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / 'private').mkdir(mode=0o700, exist_ok=True)
    for relative in ('', 'api-keys', 'agent', 'secrets'):
        path = STATE / relative
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.chmod(0o700)
        os.chown(path, 1000, 1000)
    token_file = STATE / 'secrets/onebot_access_token'
    if not token_file.exists():
        private_write(token_file, secrets.token_hex(32), uid=1000)
    token = token_file.read_text(encoding='utf-8').strip()
    key_store = STATE / 'api-keys/api-keys.json'
    if not key_store.exists():
        write_json(key_store, {'schemaVersion': 1, 'revision': 1, 'pools': {}}, uid=1000)

    # Named volumes make the same ownership work on Linux and Docker Desktop.
    plugins = DATA / 'plugins'
    plugins.mkdir(exist_ok=True)
    for source in sorted(Path('/opt/dududa/bundled-plugins').iterdir()):
        target = plugins / source.name
        if source.is_dir() and not target.exists():
            shutil.copytree(source, target)
    for source in (REPO / 'services/mcp').iterdir():
        if source.is_dir() and source.name not in {'console', 'unified-worker'}:
            target = DATA / f'{source.name}-mcp'
            if not target.exists():
                target.symlink_to(source, target_is_directory=True)
            (DATA / f'{source.name}-cache').mkdir(exist_ok=True)
    mcp_config = DATA / 'mcp_server.json'
    if not mcp_config.exists():
        shutil.copyfile(REPO / 'configs/astrbot/mcp_server.json', mcp_config)
        mcp_config.chmod(0o600)

    login = json.loads(LOGIN.read_text(encoding='utf-8')) if LOGIN.exists() else {}
    if first_install:
        password = secrets.token_urlsafe(18)
        command = copy.deepcopy(DEFAULT_CONFIG)
        command['dashboard'].update(
            username='astrbot',
            password=hash_md5_dashboard_password(password),
            pbkdf2_password=hash_dashboard_password(password),
            password_storage_upgraded=True,
            password_change_required=False,
            jwt_secret=secrets.token_hex(32),
        )
        command['provider_settings']['default_personality'] = 'dududa'
        command['platform'] = [{
            'id': 'dududa-qq', 'type': 'aiocqhttp', 'enable': True,
            'ws_reverse_host': '0.0.0.0', 'ws_reverse_port': 6199,
            'ws_reverse_token': token,
        }]
        write_json(command_path, command)
        login.update(astrbot_username='astrbot', astrbot_password=password)

    NAPCAT.mkdir(parents=True, exist_ok=True)
    os.chown(NAPCAT, 1000, 1000)
    webui_path = NAPCAT / 'webui.json'
    if not webui_path.exists():
        webui_token = secrets.token_urlsafe(24)
        write_json(webui_path, {
            'host': '0.0.0.0', 'prefix': '', 'port': 6099,
            'token': webui_token, 'loginRate': 3,
        }, uid=1000)
        login['napcat_token'] = webui_token
    onebot = NAPCAT / 'onebot11.json'
    if not onebot.exists():
        clients = []
        for name, url, report_self in (
            ('astrbot', 'ws://astrbot:6199/ws', False),
            ('dududa-web', 'ws://web:8000/onebot/v11/ws', True),
        ):
            clients.append({
                'name': name, 'enable': True, 'url': url,
                'messagePostFormat': 'array', 'reportSelfMessage': report_self,
                'token': token, 'debug': False, 'heartInterval': 30000,
                'reconnectInterval': 5000,
            })
        write_json(onebot, {'network': {
            'httpServers': [], 'httpSseServers': [], 'httpClients': [],
            'websocketServers': [], 'websocketClients': clients, 'plugins': [],
        }, 'musicSignUrl': '', 'enableLocalFile2Url': False, 'parseMultMsg': False}, uid=1000)
    # The image entrypoint otherwise restores all default configs over our files.
    napcat_config = NAPCAT / 'napcat.json'
    if not napcat_config.exists():
        write_json(napcat_config, {}, uid=1000)
    write_json(LOGIN, login)
    print('Settings, plugins, OneBot connections and named volumes are ready.')


def finish() -> None:
    from seed_astrbot import load_persona, seed_persona
    metadata, prompt = load_persona(REPO / 'configs/personas/dududa.json')
    import sqlite3
    with sqlite3.connect(DATA / 'data_v4.db') as db:
        exists = db.execute('SELECT 1 FROM personas WHERE persona_id = ?', ('dududa',)).fetchone()
    if not exists:
        seed_persona(DATA / 'data_v4.db', metadata, prompt)
    token_file = STATE / 'secrets/astrbot_plugin_api_key'
    if not token_file.exists() or not token_file.stat().st_size:
        result = subprocess.run([
            sys.executable, str(REPO / 'ops/cli/provision_astrbot_plugin_key.py'),
            '--api-url', 'http://astrbot:6185/api/v1', '--wait-seconds', '90',
        ], check=True, capture_output=True, text=True)
        if not result.stdout.strip():
            raise RuntimeError('AstrBot returned an empty plugin API key')
        private_write(token_file, result.stdout.strip(), uid=1000)
    print('Dududa persona and Web workspace access are ready.')


def credentials() -> None:
    login = json.loads(LOGIN.read_text(encoding='utf-8'))
    print('Dududa initial login / 嘟嘟哒首次登录')
    print('Addresses below use the default ports; see quickstart.env if changed.')
    print('WebUI:  http://127.0.0.1:5173')
    print('AstrBot: http://127.0.0.1:6185')
    print('  Username:', login.get('astrbot_username', '(already configured)'))
    print('  Initial password:', login.get('astrbot_password', '(unchanged)'))
    print('NapCat: http://127.0.0.1:6099')
    print('  Initial token:', login.get('napcat_token', '(unchanged)'))
    print('These are initial credentials. After changing them, use your new values.')


if __name__ == '__main__':
    {'prepare': prepare, 'finish': finish, 'credentials': credentials}[sys.argv[1]]()
