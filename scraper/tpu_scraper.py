"""Crawler TechPowerUp GPU Database cho đồ án DS101.

CÁCH KHÁM PHÁ TRANG (đọc kỹ — lý do thiết kế):
    Bộ lọc của trang danh sách (?mfgr=..&year=..) được site cố ý mã hoá để bot không
    tìm thấy ("spidertrap"); gọi tham số sai -> HTTP 410 rồi captcha (đã gặp 13/11/2026).
    Vì vậy crawler KHÔNG dùng bất kỳ URL có query string nào. Nó chỉ đi theo link công khai:
        trang gốc /gpu-specs/  ->  trang card  /gpu-specs/<slug>.c1234
                               ->  trang chip  /gpu-specs/<slug>.g1234  (liệt kê mọi card dùng chip)
    và lan dần (FIFO trong từng nhóm, tải xen kẽ card/chip).

    python scraper/tpu_scraper.py probe                 # 3 request: trang gốc + 1 card + 1 chip
    python scraper/tpu_scraper.py crawl --max-pages 50  # thử
    python scraper/tpu_scraper.py crawl                 # toàn bộ; Ctrl+C/bị chặn -> chạy lại sẽ tiếp tục
    python scraper/tpu_scraper.py parse                 # cache -> data/raw_gpu_data.csv (lọc 2000–2026)

Mọi trang lưu ở data/cache/; khi khởi động lại, hàng đợi được dựng lại từ link trong cache.
Gặp 403/410/captcha là DỪNG NGAY (không cố gõ cửa tiếp) — đợi vài giờ rồi chạy lại.
"""
from __future__ import annotations

import argparse
import csv
import logging
import random
import sys
import time
from collections import deque
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tpu_parse import (  # noqa: E402
    CORE_FIELDS, FIELD_MAP, extract_links, extract_sections, is_blocked_page, parse_detail,
    release_year,
)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "cache"
CACHE_DIRS = {"c": CACHE / "gpus", "g": CACHE / "chips"}
BASE_CACHE = CACHE / "lists" / "_base.html"
LINKS_CSV = DATA / "links.csv"
RAW_CSV = DATA / "raw_gpu_data.csv"
ALL_FIELDS_CSV = DATA / "raw_gpu_all_fields.csv"
REPORTS = ROOT / "reports"
LOGS = ROOT / "logs"

BASE = "https://www.techpowerup.com/gpu-specs/"
DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/131.0.0.0 Safari/537.36 DS101-StudentProject/1.0 (academic; non-commercial)")

log = logging.getLogger("tpu")


class Blocked(RuntimeError):
    """Site đang chặn -> dừng hẳn; chạy lại sau sẽ tiếp tục từ cache."""


# ====================================================================== HTTP
class PoliteClient:
    def __init__(self, ua: str, delay_min: float, delay_max: float, max_retries: int = 3):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": BASE,
        })
        self.delay_min, self.delay_max = delay_min, delay_max
        self.max_retries = max_retries
        self.n_requests = 0

    @staticmethod
    def _retry_after(resp: requests.Response) -> int | None:
        v = resp.headers.get("Retry-After")
        if not v:
            return None
        try:
            return int(v)
        except ValueError:
            try:
                return max(0, int(parsedate_to_datetime(v).timestamp() - time.time()))
            except Exception:
                return None

    def get(self, url: str) -> str | None:
        """HTML hợp lệ; None nếu 404/lỗi tạm thời kéo dài; raise Blocked nếu bị chặn."""
        for attempt in range(self.max_retries):
            time.sleep(random.uniform(self.delay_min, self.delay_max))
            self.n_requests += 1
            try:
                resp = self.s.get(url, timeout=30)
            except requests.RequestException as e:
                wait = 15 * 2 ** attempt
                log.warning("Lỗi mạng (%s) %s -> chờ %ss", type(e).__name__, url, wait)
                time.sleep(wait)
                continue

            code = resp.status_code
            if code == 404:
                log.warning("404 %s", url)
                return None
            if code == 200 and not is_blocked_page(resp.text):
                return resp.text
            if code in (403, 410) or code == 200:  # 200 + trang captcha
                raise Blocked(f"{'captcha' if code == 200 else 'HTTP ' + str(code)} tại {url}")
            if code == 429:
                wait = self._retry_after(resp) or 120
                if wait > 600:
                    raise Blocked(f"HTTP 429, site yêu cầu chờ {wait}s")
                log.warning("429 tại %s -> chờ %ss rồi thử lại", url, wait)
                time.sleep(wait)
                continue
            wait = 30 * 2 ** attempt  # 5xx
            log.warning("HTTP %s tại %s (lần %d/%d) -> chờ %ss", code, url, attempt + 1, self.max_retries, wait)
            time.sleep(wait)
        return None


def cached_get(client: PoliteClient, url: str, path: Path) -> str | None:
    if path.exists() and path.stat().st_size > 0:
        return path.read_text(encoding="utf-8", errors="replace")
    html = client.get(url)
    if html is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(html, encoding="utf-8")
        tmp.replace(path)  # ghi nguyên tử: Ctrl+C giữa chừng không để lại file hỏng
    return html


def cache_path(key: str) -> Path:
    return CACHE_DIRS[key[0]] / f"{key}.html"


# ====================================================================== CRAWL (BFS)
class Frontier:
    """Xen kẽ card/chip, bắt đầu bằng card; cache không chiếm lượt."""

    def __init__(self):
        self.q = {"g": deque(), "c": deque()}
        self.seen: set[str] = set()
        self.urls: dict[str, str] = {}
        self.next_kind = "c"

    def add_from(self, html: str) -> int:
        n = 0
        for key, url in extract_links(html):
            if key not in self.seen:
                self.seen.add(key)
                self.urls[key] = url
                self.q[key[0]].append(key)
                n += 1
        return n

    def pop(self, skip: set[str] | frozenset[str] = frozenset()) -> str | None:
        other = "g" if self.next_kind == "c" else "c"
        for kind in (self.next_kind, other):
            while self.q[kind] and self.q[kind][0] in skip:
                self.q[kind].popleft()
            if self.q[kind]:
                self.next_kind = "g" if kind == "c" else "c"
                return self.q[kind].popleft()
        return None

    def __len__(self):
        return len(self.q["g"]) + len(self.q["c"])


def save_links(fr: Frontier) -> None:
    rows = [{"gpu_id": k, "url": u} for k, u in fr.urls.items() if k.startswith("c")]
    write_csv(LINKS_CSV, rows, ["gpu_id", "url"])


def stage_crawl(client: PoliteClient, args) -> None:
    from tpu_runner import run
    run(client, args, sys.modules[__name__])


# ====================================================================== PARSE
def stage_parse(args) -> None:
    url_of = {}
    if LINKS_CSV.exists():
        with LINKS_CSV.open(encoding="utf-8-sig", newline="") as f:
            url_of = {r["gpu_id"]: r["url"] for r in csv.DictReader(f)}
    files = sorted(CACHE_DIRS["c"].glob("*.html")) if CACHE_DIRS["c"].exists() else []
    raw_rows, all_rows, out_of_range, no_year = [], [], 0, 0
    for p in files:
        gid = p.stem
        try:
            rec, all_fields = parse_detail(p.read_text(encoding="utf-8", errors="replace"))
        except Exception as e:  # một trang lỗi không làm hỏng cả bộ dữ liệu
            log.warning("Parse lỗi %s: %s", p.name, e)
            continue
        y = release_year(rec.get("release_date", ""))
        if y is None:
            no_year += 1  # "Never Released"/"Unknown" -> giữ lại, Phase 3 quyết định
        elif not (args.year_from <= y <= args.year_to):
            out_of_range += 1
            continue
        meta = {"gpu_id": gid, "url": url_of.get(gid, "")}
        raw_rows.append({**meta, **rec})
        all_rows.append({**meta, "product_name": rec["product_name"], **all_fields})

    if not raw_rows:
        sys.exit("Không có trang card nào trong cache — chạy `crawl` trước.")
    raw_cols = ["gpu_id", "url", "product_name", *FIELD_MAP]
    write_csv(RAW_CSV, raw_rows, raw_cols)
    all_cols = list(dict.fromkeys(k for row in all_rows for k in row))
    write_csv(ALL_FIELDS_CSV, all_rows, all_cols)
    write_parse_report(raw_rows, raw_cols, len(files), out_of_range, no_year, args)
    log.info("raw_gpu_data.csv: %d dòng × %d cột (bỏ %d ngoài %d–%d, %d không rõ năm) | all_fields: %d cột",
             len(raw_rows), len(raw_cols), out_of_range, args.year_from, args.year_to, no_year, len(all_cols))


def write_parse_report(rows, cols, n_files, out_of_range, no_year, args) -> None:
    n = len(rows)
    fill = {c: sum(1 for r in rows if (r.get(c) or "").strip()) / n for c in cols}
    lines = [f"# Báo cáo parse — {time.strftime('%Y-%m-%d %H:%M')}", "",
             f"- Trang card trong cache: {n_files} | giữ: **{n}** | bỏ ngoài {args.year_from}–{args.year_to}: "
             f"{out_of_range} | không rõ năm (giữ): {no_year} | cột raw: **{len(cols)}**", "",
             "| Cột | Tỉ lệ điền |", "|---|---|"]
    lines += [f"| {c} | {fill[c]:.1%} |" for c in cols]
    bad = [c for c in CORE_FIELDS if fill.get(c, 0) < 0.5]
    if bad:
        msg = f"CẢNH BÁO: cột lõi điền < 50%: {bad} — nhãn trên trang có thể đã đổi, chạy `probe` để xem."
        lines += ["", f"**{msg}**"]
        log.warning(msg)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "parse_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ====================================================================== PROBE
def stage_probe(client: PoliteClient, args) -> None:
    base = cached_get(client, BASE, BASE_CACHE)
    if not base:
        sys.exit("Không tải được trang gốc.")
    links = extract_links(base)
    cards = [x for x in links if x[0].startswith("c")]
    chips = [x for x in links if x[0].startswith("g")]
    print(f"\n[1] Trang gốc: {len(cards)} card, {len(chips)} chip")
    if not cards:
        sys.exit("Không thấy link card nào — cấu trúc trang khác, gửi file data/cache/lists/_base.html cho Claude.")
    key, url = next((x for x in cards if "4090" in x[1]), cards[0])
    html = cached_get(client, url, cache_path(key))
    name, sections = extract_sections(html)
    print(f"\n[2] Trang card: {name}  ({url})")
    for s, d in sections.items():
        print(f"    == {s} ({len(d)} trường)")
        for k, v in d.items():
            print(f"         {k:<24} {v[:60]}")
    rec, _ = parse_detail(html)
    empty = [c for c, v in rec.items() if not v]
    print(f"    -> map được {len(rec) - len(empty)}/{len(rec)} cột. Trống: {empty}")
    nl = extract_links(html)
    print(f"    -> trang card này dẫn tới {sum(k[0]=='c' for k,_ in nl)} card, {sum(k[0]=='g' for k,_ in nl)} chip")
    if chips:
        key, url = chips[0]
        h2 = cached_get(client, url, cache_path(key))
        nl = extract_links(h2 or "")
        print(f"\n[3] Trang chip {url}: dẫn tới {sum(k[0]=='c' for k,_ in nl)} card, {sum(k[0]=='g' for k,_ in nl)} chip")


# ====================================================================== tiện ích
def write_csv(path: Path, rows: list[dict], cols: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:  # utf-8-sig để Excel đọc đúng
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def setup_logging() -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S")
    for h in (logging.StreamHandler(sys.stdout), logging.FileHandler(LOGS / "scrape.log", encoding="utf-8")):
        h.setFormatter(fmt)
        log.addHandler(h)
    log.setLevel(logging.INFO)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=["probe", "crawl", "parse", "all"])
    ap.add_argument("--delay-min", type=float, default=30.0)
    ap.add_argument("--delay-max", type=float, default=60.0)
    ap.add_argument("--user-agent", default=DEFAULT_UA)
    ap.add_argument("--max-pages", type=int, default=0, help="thử tải tối đa N trang chưa có cache; gồm cả trang lỗi")
    ap.add_argument("--year-from", type=int, default=2000)
    ap.add_argument("--year-to", type=int, default=2026)
    ap.add_argument("--batch-size", type=int, default=20)
    ap.add_argument("--batch-pause-min", type=float, default=120)
    ap.add_argument("--batch-pause-max", type=float, default=240)
    args = ap.parse_args()
    if args.batch_size < 1 or args.max_pages < 0:
        ap.error("batch-size phải >= 1; max-pages phải >= 0")
    if not (0 <= args.delay_min <= args.delay_max and 0 <= args.batch_pause_min <= args.batch_pause_max):
        ap.error("Khoảng nghỉ không hợp lệ")
    setup_logging()

    client = PoliteClient(args.user_agent, args.delay_min, args.delay_max)
    t0 = time.time()
    try:
        if args.stage == "probe":
            stage_probe(client, args)
        if args.stage in ("crawl", "all"):
            stage_crawl(client, args)
        if args.stage in ("parse", "all"):
            stage_parse(args)
    except Blocked as e:
        log.error("DỪNG vì bị chặn: %s. Đợi vài giờ (mở trang bằng trình duyệt thấy bình thường) "
                  "rồi chạy lại đúng lệnh — sẽ tiếp tục từ cache.", e)
        sys.exit(2)
    except KeyboardInterrupt:
        log.warning("Đã dừng bằng Ctrl+C — chạy lại cùng lệnh sẽ tiếp tục từ cache.")
        sys.exit(130)
    finally:
        log.info("Xong sau %.1f phút, %d request mạng.", (time.time() - t0) / 60, client.n_requests)


if __name__ == "__main__":
    main()
