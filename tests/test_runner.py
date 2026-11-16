import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scraper'))
import tpu_scraper as api
from tpu_runner import run, RunLock


def fixture_api(tmp_path, monkeypatch):
    monkeypatch.setattr(api, 'DATA', tmp_path)
    monkeypatch.setattr(api, 'BASE_CACHE', tmp_path / 'base.html')
    monkeypatch.setattr(api, 'CACHE_DIRS', {'c': tmp_path / 'gpus', 'g': tmp_path / 'chips'})
    monkeypatch.setattr(api, 'LINKS_CSV', tmp_path / 'links.csv')
    monkeypatch.setattr(api, 'stage_parse', lambda args: None)
    api.BASE_CACHE.write_text('<a href="/gpu-specs/a.c1"></a><a href="/gpu-specs/b.c2"></a>')
    return SimpleNamespace(max_pages=0, batch_size=20, batch_pause_min=0, batch_pause_max=0)


class Client:
    def __init__(self, results):
        self.results = iter(results)
        self.n_requests = 0

    def get(self, url):
        self.n_requests += 1
        value = next(self.results)
        if isinstance(value, BaseException):
            raise value
        return value


def test_blocked_resume_preserves_cache(tmp_path, monkeypatch):
    args = fixture_api(tmp_path, monkeypatch)
    with pytest.raises(api.Blocked):
        run(Client(['<h1>A</h1>', api.Blocked('captcha')]), args, api)
    assert json.loads((tmp_path / 'runtime/status.json').read_text())['status'] == 'blocked'
    assert json.loads((tmp_path / 'runtime/checkpoint.json').read_text())['pending'] == ['c2']
    client = Client(['<h1>B</h1>'])
    run(client, args, api)
    assert client.n_requests == 1
    assert json.loads((tmp_path / 'runtime/status.json').read_text())['status'] == 'finished'


def test_failure_is_not_success_and_retried_next_run(tmp_path, monkeypatch):
    args = fixture_api(tmp_path, monkeypatch)
    run(Client([None, '<h1>B</h1>']), args, api)
    state = json.loads((tmp_path / 'runtime/status.json').read_text())
    assert (state['saved'], state['failed'], state['status']) == (1, 1, 'finished_with_errors')
    client = Client(['<h1>A</h1>'])
    run(client, args, api)
    assert client.n_requests == 1


def test_limit_preserves_pending_and_lock_excludes_second_run(tmp_path, monkeypatch):
    args = fixture_api(tmp_path, monkeypatch)
    args.max_pages = 1
    run(Client(['<h1>A</h1>']), args, api)
    state = json.loads((tmp_path / 'runtime/status.json').read_text())
    assert state['status'] == 'limited' and state['pending'] == 1
    with RunLock(tmp_path / 'runtime/crawl.lock'):
        with pytest.raises(RuntimeError):
            run(Client([]), args, api)
