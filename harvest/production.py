"""Render entry point: production WSGI transport with the existing application rules."""
import io
import logging
import os
import sqlite3
import time
from contextlib import closing
from email.message import Message
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from . import core
from .server import Handler


class WSGIRequest(Handler):
    """Reuse routes without using BaseHTTPRequestHandler's socket/HTTP parser."""
    def __init__(self, environ, config):
        self.server = config
        self.path = environ.get('PATH_INFO', '/')
        if environ.get('QUERY_STRING'):
            self.path += '?' + environ['QUERY_STRING']
        self.headers = Message()
        for key, value in environ.items():
            if key.startswith('HTTP_'):
                self.headers[key[5:].replace('_', '-')] = value
        for key, name in [('CONTENT_TYPE', 'Content-Type'), ('CONTENT_LENGTH', 'Content-Length')]:
            if environ.get(key):
                self.headers[name] = environ[key]
        self.rfile = environ['wsgi.input']
        self.wfile = io.BytesIO()
        self.client_address = (environ.get('REMOTE_ADDR', 'unknown'), 0)
        self.response_headers = []
        self.status = 500

    def send_response(self, code, message=None):
        self.status = code
        self.response_headers = []

    def send_header(self, name, value):
        self.response_headers.append((name, str(value)))

    def end_headers(self):
        pass


def application(config):
    def app(environ, start_response):
        request = WSGIRequest(environ, config)
        method = environ.get('REQUEST_METHOD', 'GET')
        try:
            if method in ('GET', 'HEAD') and environ.get('PATH_INFO') == '/healthz':
                with closing(core.connect(config.database)) as db:
                    db.execute('SELECT id FROM users LIMIT 1').fetchone()
                request.send(200, {'ok': True})
            elif method in ('GET', 'HEAD'):
                request.do_GET()
            elif method == 'POST' and environ.get('PATH_INFO', '').startswith('/api/'):
                request.do_POST()
            else:
                request.send(405, {'error': '不支持此请求方式'})
        except Exception:
            logging.exception('Request failed')
            request.wfile = io.BytesIO()
            request.send(503, {'error': '服务暂时不可用，请稍后重试'})
        start_response(f'{request.status} {HTTPStatus(request.status).phrase}', request.response_headers)
        return [b'' if method == 'HEAD' else request.wfile.getvalue()]
    return app


def prepare(env=None):
    env = os.environ if env is None else env
    origin = env.get('HARVEST_ORIGIN') or env.get('RENDER_EXTERNAL_URL', '')
    parsed = urlsplit(origin)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise ValueError('请设置 HARVEST_ORIGIN 为正式 HTTPS 网站地址；Render 默认网址可自动读取。')
    origin = origin.rstrip('/')
    timezone = env.get('TZ')
    if not timezone:
        raise ValueError('请设置 TZ 为工厂业务时区，例如 America/Toronto。')
    from zoneinfo import ZoneInfo
    ZoneInfo(timezone)
    os.environ['TZ'] = timezone
    if hasattr(time, 'tzset'):
        time.tzset()
    path = Path(env.get('HARVEST_DB', '/var/data/harvest.sqlite3')).resolve()
    ephemeral = env.get('HARVEST_ALLOW_EPHEMERAL') == '1'
    if env.get('RENDER') and not ephemeral:
        mount = Path('/var/data')
        if not mount.is_mount() or not path.is_relative_to(mount):
            raise ValueError('正式部署需要挂载 /var/data 持久化磁盘，并将 HARVEST_DB 放在其中。')
    core.initialize(path)
    with closing(core.connect(path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
            password = env.get('HARVEST_ADMIN_PASSWORD', '')
            if not password:
                raise ValueError('首次启动请设置 HARVEST_ADMIN_PASSWORD，创建管理员后可删除此环境变量。')
            db.execute('INSERT INTO users(username,name,role,rate,password) VALUES(?,?,?,?,?)',
                       ('admin', '管理员', 'manager', 0, core.password_hash(password)))
    if ephemeral:
        logging.warning('临时试用存储：重启或重新部署可能丢失全部数据，不可用于正式业务。')
    return SimpleNamespace(database=str(path), demo=False, secure=True, origin=origin)


def main():
    from waitress import serve
    config = prepare()
    serve(application(config), host='0.0.0.0', port=int(os.environ.get('PORT', '10000')),
          threads=4, max_request_body_size=100000, channel_timeout=60,
          expose_tracebacks=False, clear_untrusted_proxy_headers=True)


if __name__ == '__main__':
    main()
