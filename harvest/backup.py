"""Daily, bounded R2 snapshots for the single-instance production service.

Credentials stay in environment variables. No HTTP endpoint can trigger an upload.
"""
import datetime as dt
import fcntl
import gzip
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import threading
import time
from contextlib import closing
from urllib.parse import urlsplit

REQUIRED = ('R2_BUCKET', 'R2_ENDPOINT_URL', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY')
MAX_BUCKET_BYTES = 4_000_000_000
MAX_FILE_BYTES = 200_000_000
MAX_DATABASE_BYTES = 250_000_000
MAX_MONTH_BYTES = 2_000_000_000
MAX_MONTH_REQUESTS = 500
REQUEST_RESERVATION = 6


class BackupBlocked(Exception):
    pass


def configured(env):
    return env.get('HARVEST_BACKUP_ENABLED') != '0' and all(env.get(k) for k in REQUIRED)


def state_path(database):
    return Path(str(database) + '.backup-status.json')


def read_state(database):
    path = state_path(database)
    if not path.exists():
        return {}
    state = json.loads(path.read_text())
    if not isinstance(state, dict):
        raise ValueError('Invalid backup accounting')
    for key in ('month_bytes', 'month_requests', 'last_attempt', 'last_success'):
        if key in state and (not isinstance(state[key], (int, float)) or state[key] < 0):
            raise ValueError('Invalid backup accounting')
    return state


def write_state(database, state):
    path = state_path(database)
    temp = path.with_suffix('.tmp')
    with open(temp, 'w') as out:
        os.chmod(temp, 0o600)
        json.dump(state, out)
        out.flush()
        os.fsync(out.fileno())
    os.replace(temp, path)


def public_status(database, env=None):
    env = os.environ if env is None else env
    try:
        state = read_state(database)
    except (OSError, ValueError):
        return {'status': 'failed', 'message': '备份状态无法读取，请检查服务器日志。'}
    result = {k: state.get(k) for k in ('status', 'message', 'last_attempt', 'last_success', 'key', 'size', 'bucket_bytes', 'month_bytes')}
    result.update(interval='每天一次', retention='7 天', bucket_limit=MAX_BUCKET_BYTES,
                  file_limit=MAX_FILE_BYTES, month_limit=MAX_MONTH_BYTES)
    if not configured(env):
        result.update(status='disabled', message='自动备份未启用；需要在正式服务配置完整的 R2 连接信息。')
    elif not state:
        result.update(status='pending', message='连接信息已配置，等待正式服务执行首次备份。')
    elif state.get('last_attempt') and time.time() - state['last_attempt'] > 36 * 3600:
        result.update(status='stale', message='超过 36 小时没有执行备份，请检查服务和日志。')
    elif state.get('status') == 'running' and time.time() - state.get('last_attempt', 0) > 3600:
        result.update(status='failed', message='备份执行中断或超时；请检查日志，下一次将在次日尝试。')
    return result


def client_from_env(env):
    endpoint = urlsplit(env['R2_ENDPOINT_URL'])
    if (endpoint.scheme != 'https' or not re.fullmatch(r'[a-f0-9]{32}(?:\.(?:eu|fedramp))?\.r2\.cloudflarestorage\.com', endpoint.hostname or '')
            or endpoint.username or endpoint.password or endpoint.port or endpoint.path not in ('', '/') or endpoint.query or endpoint.fragment):
        raise BackupBlocked('R2 endpoint 无效，请使用 Cloudflare 提供的 HTTPS S3 地址，不加桶名。')
    import boto3
    from botocore.config import Config
    return boto3.client('s3', endpoint_url=env['R2_ENDPOINT_URL'].rstrip('/'), region_name='auto',
                       aws_access_key_id=env['R2_ACCESS_KEY_ID'], aws_secret_access_key=env['R2_SECRET_ACCESS_KEY'],
                       config=Config(signature_version='s3v4', retries={'total_max_attempts': 1},
                                     connect_timeout=10, read_timeout=120,
                                     request_checksum_calculation='when_required', response_checksum_validation='when_required',
                                     s3={'addressing_style': 'path'}))


def snapshot(database, directory):
    raw = Path(directory) / 'snapshot.sqlite3'
    packed = Path(directory) / 'snapshot.sqlite3.gz'
    deadline = time.monotonic() + 120
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)) as source:
        pages = source.execute('PRAGMA page_count').fetchone()[0]
        size = pages * source.execute('PRAGMA page_size').fetchone()[0]
        if size > MAX_DATABASE_BYTES:
            raise BackupBlocked('数据库超过 250 MB 保守上限，暂停备份，请评估容量后调整方案。')
        if shutil.disk_usage(directory).free < size * 3 + 50_000_000:
            raise BackupBlocked('服务器临时空间不足，未生成备份。')
        def progress(status, remaining, total):
            if time.monotonic() > deadline or raw.stat().st_size > MAX_DATABASE_BYTES:
                raise BackupBlocked('生成数据库快照超时或超过大小限制。')
        with closing(sqlite3.connect(raw)) as target:
            source.backup(target, pages=256, progress=progress)
            if target.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise BackupBlocked('数据库完整性检查未通过，未上传备份。')
    with open(raw, 'rb') as source, gzip.open(packed, 'wb', compresslevel=6) as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    if packed.stat().st_size > MAX_FILE_BYTES:
        raise BackupBlocked('压缩备份超过 200 MB 上限，暂停上传。')
    with open(packed, 'rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    return packed, digest


def run_once(database, env=None, client=None, now=None):
    """One attempt per local date, including across restarts; lock covers all I/O."""
    env = os.environ if env is None else env
    if not configured(env):
        return 'disabled'
    now = now or dt.datetime.now().astimezone()
    day, month = now.date().isoformat(), now.strftime('%Y-%m')
    # Sidecar files are stored beside the database on the persistent disk.
    with open(str(database) + '.backup.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 'busy'
        state = read_state(database)  # Corrupt accounting fails closed, never resets silently.
        if state.get('day') == day:
            return 'already_attempted'
        if state and now.hour < 3:
            return 'not_due'
        if state.get('month') != month:
            state.update(month=month, month_bytes=0, month_requests=0)
        state.update(day=day, last_attempt=now.timestamp(), status='running', message='正在生成并验证异地备份。')
        write_state(database, state)
        try:
            if state['month_requests'] + REQUEST_RESERVATION > MAX_MONTH_REQUESTS:
                raise BackupBlocked('达到本月备份请求保护上限，下月自动恢复尝试。')
            state['month_requests'] += REQUEST_RESERVATION
            write_state(database, state)
            client = client or client_from_env(env)
            bucket = env['R2_BUCKET']
            # Check the whole bucket, not just our prefix; refuse incomplete listings.
            response = client.list_objects_v2(Bucket=bucket, MaxKeys=1000)
            if response.get('IsTruncated'):
                raise BackupBlocked('桶内对象超过检查上限，无法确认总容量，暂停上传。')
            objects = response.get('Contents', [])
            total = sum(o['Size'] for o in objects)
            state['bucket_bytes'] = total
            if any(o.get('StorageClass', 'STANDARD') != 'STANDARD' for o in objects):
                raise BackupBlocked('发现非 Standard 存储对象，请检查 R2 存储类型。')
            multipart = client.list_multipart_uploads(Bucket=bucket, MaxUploads=1)
            if multipart.get('Uploads') or multipart.get('IsTruncated'):
                raise BackupBlocked('发现未完成的分段上传，无法确认占用，暂停备份。')
            key = f'daily/harvest-{day}.sqlite3.gz'
            if any(o['Key'] == key for o in objects):
                raise BackupBlocked('今天的备份对象已存在，不覆盖；请核验后等待次日备份。')
            with tempfile.TemporaryDirectory(prefix='harvest-backup-') as directory:
                packed, digest = snapshot(database, directory)
                size = packed.stat().st_size
                if total + size > MAX_BUCKET_BYTES:
                    raise BackupBlocked('R2 存储将超过 4 GB 保护上限；等待旧备份清理，次日自动检查。')
                if state['month_bytes'] + size > MAX_MONTH_BYTES:
                    raise BackupBlocked('达到本月 2 GB 上传保护上限，下月自动恢复尝试。')
                # Reserve bytes before upload: failed/ambiguous transfers count too.
                state['month_bytes'] += size
                write_state(database, state)
                with open(packed, 'rb') as source:
                    client.put_object(Bucket=bucket, Key=key, Body=source, ContentLength=size,
                                      ContentType='application/gzip', StorageClass='STANDARD', Metadata={'sha256': digest})
                remote = client.get_object(Bucket=bucket, Key=key)
                with closing(remote['Body']) as body:
                    downloaded = 0
                    checksum = hashlib.sha256()
                    while chunk := body.read(1024 * 1024):
                        downloaded += len(chunk)
                        if downloaded > size:
                            raise BackupBlocked('远端备份大小异常，校验失败。')
                        checksum.update(chunk)
                if downloaded != size or checksum.hexdigest() != digest:
                    raise BackupBlocked('远端备份校验失败，请检查日志和存储桶。')
                state.update(status='ok', message='备份上传成功，回读校验通过。', last_success=now.timestamp(),
                             key=key, size=size, bucket_bytes=total + size)
        except BackupBlocked as error:
            state.update(status='blocked', message=str(error))
        except Exception:
            # Never expose SDK exceptions that could include request URLs or credentials.
            state.update(status='failed', message='备份失败，请检查 R2 凭据、权限或网络；次日自动重试。')
        write_state(database, state)
        logging.warning('R2 backup [%s]: %s', state['status'], state['message'])
        return state['status']


def start(database):
    if not configured(os.environ):
        logging.warning('R2 backup disabled: complete R2 configuration is required.')
        return None
    def worker():
        while True:
            try:
                run_once(database)
            except Exception:
                logging.error('R2 backup could not read/write its local accounting state; upload stopped.')
            time.sleep(3600)
    thread = threading.Thread(target=worker, name='r2-daily-backup', daemon=True)
    thread.start()
    return thread


if __name__ == '__main__':
    result = run_once(os.environ.get('HARVEST_DB', '/var/data/harvest.sqlite3'))
    print('R2 backup:', result)
    raise SystemExit(0 if result in ('ok', 'already_attempted', 'not_due') else 1)
