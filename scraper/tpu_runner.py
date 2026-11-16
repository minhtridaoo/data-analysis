"""Batch orchestration, durable progress and a single-writer lock.

Uses the existing HTTP client and GPU parser; no browser-profile reuse.
"""
import json
import os
import random
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path


def stamp():
    return datetime.now(timezone(timedelta(hours=7))).isoformat(timespec='seconds')


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


class RunLock:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open('a+b')
        self.file.seek(0, 2)
        if self.file.tell() == 0:
            self.file.write(b'0')
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError('Một crawler khác đang chạy; không khởi động bản thứ hai.')
        return self

    def __exit__(self, *_):
        self.file.close()  # OS releases the lock, including after a crash.


def run(client, args, api):
    folder = api.DATA / 'runtime'
    with RunLock(folder / 'crawl.lock'):
        _run(client, args, api, folder)


def _run(client, args, api, folder):
    progress = folder / 'status.json'
    checkpoint = folder / 'checkpoint.json'
    state = dict(status='starting', started_at=stamp(), updated_at=stamp(), pid=os.getpid(),
                 attempted=0, saved=0, failed=0, requests=0, pending=0, current_url='',
                 batch=1, error='', parse_error='', next_action_at=None)
    guard = threading.Lock()
    stop = threading.Event()

    def publish(**values):
        with guard:
            state.update(values)
            state.update(updated_at=stamp(), requests=client.n_requests)
            atomic_json(progress, state)

    def heartbeat():
        while not stop.wait(5):
            publish()

    publish()
    worker = threading.Thread(target=heartbeat, daemon=True)
    worker.start()
    fr = api.Frontier()
    failed = {}
    cached = set()
    initialized = False

    def save():
        api.save_links(fr)
        atomic_json(checkpoint, dict(updated_at=stamp(), urls=fr.urls, failed=failed,
                                    pending=[k for k in fr.urls if k not in cached]))

    def parse():
        if any(api.CACHE_DIRS['c'].glob('*.html')):
            try:
                api.stage_parse(args)
                publish(last_parse_at=stamp(), parse_error='')
            except (Exception, SystemExit) as exc:
                publish(parse_error=str(exc))
                api.log.error('Không xuất được CSV: %s', exc)

    try:
        # Recover known public URLs even if a prior download failed.
        if checkpoint.exists():
            old = json.loads(checkpoint.read_text(encoding='utf-8'))
            for key, url in old.get('urls', {}).items():
                links = api.extract_links('<a href="' + str(url).replace('"', '%22') + '"></a>')
                if links == [(key, url)]:
                    fr.add_from('<a href="' + url + '"></a>')
        base = api.cached_get(client, api.BASE, api.BASE_CACHE)
        if base is None:
            raise RuntimeError('Không tải được trang danh sách.')
        fr.add_from(base)
        for directory in api.CACHE_DIRS.values():
            for p in sorted(directory.glob('*.html')):
                if p.stat().st_size:
                    fr.add_from(p.read_text(encoding='utf-8', errors='replace'))
        cached = {k for k in fr.urls if api.cache_path(k).exists() and api.cache_path(k).stat().st_size}
        initialized = True
        save()
        publish(status='running', pending=len(fr.urls.keys() - cached))
        api.log.info('Đã biết %d trang (%d đã có cache). Chạy theo đợt %d trang.',
                     len(fr.urls), len(cached), args.batch_size)
        while not args.max_pages or state['attempted'] < args.max_pages:
            key = fr.pop(skip=cached)
            if key is None:
                break
            publish(current_url=fr.urls[key], status='running')
            html = api.cached_get(client, fr.urls[key], api.cache_path(key))
            state['attempted'] += 1
            if html is not None:
                cached.add(key)
                fr.add_from(html)
                state['saved'] += 1
            else:
                failed[key] = fr.urls[key]
                state['failed'] += 1
            save()  # Cache is saved before marking a page successful.
            publish(pending=len(fr.urls.keys() - cached))
            api.log.info('Đã thử %d | lưu mới %d | lỗi %d | còn thiếu %d',
                         state['attempted'], state['saved'], state['failed'], state['pending'])
            if state['attempted'] % args.batch_size == 0:
                parse()
                has_more = any(k not in cached for q in fr.q.values() for k in q)
                if has_more and (not args.max_pages or state['attempted'] < args.max_pages):
                    pause = random.uniform(args.batch_pause_min, args.batch_pause_max)
                    publish(status='resting', next_action_at=time.time() + pause)
                    api.log.info('Nghỉ giữa đợt %.0f giây.', pause)
                    time.sleep(pause)
                    publish(batch=state['batch'] + 1, next_action_at=None)
        missing = fr.urls.keys() - cached
        publish(status=('limited' if missing - failed.keys() else
                        'finished_with_errors' if failed else 'finished'), current_url='')
    except api.Blocked as exc:
        publish(status='blocked', error=str(exc))
        raise
    except KeyboardInterrupt:
        publish(status='stopped', error='Người dùng dừng bằng Ctrl+C')
        raise
    except BaseException as exc:
        publish(status='error', error=str(exc))
        raise
    finally:
        try:
            if initialized:
                save()
                parse()
        finally:
            stop.set()
            worker.join(timeout=6)
            publish(ended_at=stamp(), next_action_at=None)
