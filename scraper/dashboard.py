"""Read-only local dashboard. Run: python scraper/dashboard.py"""
from collections import Counter
import csv
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import time
from pathlib import Path

from tpu_parse import release_year

ROOT = Path(__file__).resolve().parent.parent
TZ = timezone(timedelta(hours=7))


def snapshot():
    path = ROOT / 'data/raw_gpu_data.csv'
    rows = []
    if path.exists():
        with path.open(encoding='utf-8-sig', newline='') as f:
            rows = list(csv.DictReader(f))
    years = Counter(release_year(r.get('release_date', '')) for r in rows)
    log = ROOT / 'logs/scrape.log'
    lines = log.read_text(encoding='utf-8', errors='replace').splitlines() if log.exists() else []
    crawl = next((s for s in reversed(lines) if any(v in s for v in (
        'DỪNG vì bị chặn', 'Đã dừng bằng Ctrl+C', 'Đạt --max-pages',
        'Hàng đợi rỗng', 'Đã biết', '| card đã có'))), 'Chưa có log crawl')
    status_path = ROOT / 'data/runtime/status.json'
    run = json.loads(status_path.read_text(encoding='utf-8')) if status_path.exists() else {}
    labels = {'starting':'Đang khởi tạo', 'running':'Đang tải', 'resting':'Đang nghỉ giữa đợt',
              'blocked':'Đã dừng do bị chặn', 'stopped':'Đã dừng', 'limited':'Đạt giới hạn lượt',
              'finished':'Đã duyệt hết liên kết tìm được', 'finished_with_errors':'Kết thúc lượt, còn trang tải lỗi',
              'error':'Dừng do lỗi'}
    status = labels.get(run.get('status'), 'Chưa có phiên chạy bằng bộ điều phối mới')
    if run.get('status') in ('starting', 'running', 'resting') and time.time() - status_path.stat().st_mtime > 90:
        status = 'Mất tín hiệu crawler; chưa xác nhận còn chạy'
    detail = f"{status}. Lưu mới: {run.get('saved', 0)}; lỗi: {run.get('failed', 0)}; còn thiếu: {run.get('pending', '—')}. " + run.get('error', '')
    if run.get('parse_error'): detail += ' Lỗi xuất CSV: ' + run['parse_error']
    return {
        'updated': datetime.now(TZ).isoformat(timespec='seconds'),
        'exported': len(rows),
        'export_time': datetime.fromtimestamp(path.stat().st_mtime, TZ).isoformat(timespec='seconds') if path.exists() else None,
        'cards': len(list((ROOT / 'data/cache/gpus').glob('*.html'))),
        'chips': len(list((ROOT / 'data/cache/chips').glob('*.html'))),
        'years': {str(y): years[y] for y in range(2000, 2027)},
        'unknown_year': years[None],
        'missing': [y for y in range(2000, 2027) if not years[y]],
        'latest_crawl_event': crawl,
        'log': '\n'.join(lines[-30:]),
        'access': detail,
        'run': run,
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = self.path.split('?')[0]
        files = {
            '/': (ROOT / 'scraper/dashboard.html', 'text/html; charset=utf-8'),
            '/raw.csv': (ROOT / 'data/raw_gpu_data.csv', 'text/csv; charset=utf-8'),
            '/report': (ROOT / 'reports/parse_report.md', 'text/plain; charset=utf-8'),
        }
        try:
            if route == '/api/status':
                body = json.dumps(snapshot(), ensure_ascii=False).encode('utf-8')
                content_type = 'application/json; charset=utf-8'
            elif route in files:
                path, content_type = files[route]
                body = path.read_bytes()
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except FileNotFoundError:
            self.send_error(404, 'File not created yet')
        except Exception:
            self.send_error(500, 'Cannot read current snapshot')

    def log_message(self, *_):
        pass


if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 8766), Handler).serve_forever()
