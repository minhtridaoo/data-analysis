# -*- coding: utf-8 -*-
"""
Thu thập dữ liệu sản phẩm "tai nghe bluetooth" trên Lazada Việt Nam.
Mục đích: chỉ phục vụ học tập (đồ án môn DS111 - Phân tích dữ liệu), số lượng nhỏ, chạy chậm.

Quy trình 2 bước:
  1) Danh sách (listing): gọi endpoint JSON
       https://www.lazada.vn/catalog/?q=<từ khóa>&ajax=true&page=N
     bằng `requests` với header trình duyệt thật. Nếu bị chặn (trả HTML "punish"/slider captcha)
     thì tự chuyển sang Playwright có giao diện để người dùng tự giải captcha.
  2) Chi tiết (detail): mở trang sản phẩm bằng Playwright (Chrome có giao diện) và "nghe" response
     của API nội bộ `mtop.global.detail.web.getdetailinfo` (trang tự gọi khi tải) để lấy:
     điểm shop, giao hàng đúng hạn, phản hồi chat, phân bố sao 1-5, số biến thể, thông số kỹ thuật...
     (Trang HTML trả về bằng requests KHÔNG chứa các trường này vì chúng được nạp bất đồng bộ
      qua API có chữ ký/token, nên phải dùng trình duyệt thật.)

Lưu dần từng dòng vào CSV (utf-8-sig) -> nếu bị ngắt, chạy lại cùng lệnh sẽ bỏ qua item đã có (resume).

Ví dụ:
  python lazada_scraper.py --max-items 50 --out ../data/raw/lazada_tai_nghe_sample.csv
  python lazada_scraper.py --pages 12 --max-items 450 --out ../data/raw/lazada_tai_nghe.csv
  python lazada_scraper.py --max-items 50 --no-detail          # chỉ lấy danh sách
"""

import argparse
import csv
import json
import os
import random
import re
import sys
import time
from datetime import datetime
from urllib.parse import quote_plus

import requests

# Windows console mặc định cp1252 -> ép UTF-8 để in tiếng Việt không lỗi
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = "https://www.lazada.vn"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36")
HEADERS_JSON = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": BASE + "/",
    "X-Requested-With": "XMLHttpRequest",
}

# Thứ tự cột trong file CSV (cố định để append không lệch cột)
COLUMNS = [
    # --- từ trang danh sách ---
    "crawl_time", "search_page", "rank_in_page", "item_id", "sku_id", "name",
    "brand", "brand_id", "category_ids",
    "price", "original_price", "discount_raw", "discount_pct",
    "rating_score", "review_count", "sold_raw", "sold_num",
    "location", "seller_name", "seller_id", "shop_id",
    "is_lazmall", "is_freeship", "is_sponsored", "in_stock", "url",
    # --- từ trang chi tiết ---
    "category_path", "product_type",
    "positive_seller_rating", "ship_on_time_rate", "chat_response_rate",
    "response_time_raw", "store_sold_raw", "store_sold_num", "repurchase_rate",
    "returning_customers", "seller_tags_raw", "is_new_seller",
    "rating_avg_detail", "rating_count_detail",
    "star_5", "star_4", "star_3", "star_2", "star_1",
    "n_variants", "variant_names",
    "bluetooth_version", "battery_hours", "waterproof", "model", "connection",
    "driver_type", "impedance", "warranty", "warranty_type",
    "is_authentic_guarantee", "cod_available", "shipping_fee", "delivery_time",
    "n_promotions", "specs_raw", "detail_status",
]

BLOCK_MARKERS = ("punish", "captcha", "slide to verify", "nc_1_n1z", "baxia", "_____tmd_____")


# ======================================================================
# Hàm tiện ích
# ======================================================================
def polite_sleep(a, b):
    """Nghỉ ngẫu nhiên a..b giây giữa các request để không gây tải cho server."""
    t = random.uniform(a, b)
    time.sleep(t)


def parse_count(s):
    """Quy đổi chuỗi số lượng dạng '1.2K sold', 'Đã bán 3,4k', '2M' -> số nguyên."""
    if s is None:
        return None
    s = str(s).strip().lower()
    # K/M phải là đơn vị đứng riêng (tránh nhầm "606 khách" thành 606K)
    m = re.search(r"(\d+(?:[.,]\d+)?)\s?([km]?)(?![a-zà-ỹđ])", s)
    if not m:
        return None
    num, unit = m.group(1), m.group(2)
    if unit:  # có K/M -> dấu , hoặc . là dấu thập phân
        val = float(num.replace(",", "."))
        val *= 1000 if unit == "k" else 1_000_000
    else:     # không có đơn vị -> , . là dấu phân cách hàng nghìn
        val = float(num.replace(",", "").replace(".", ""))
    return int(round(val))


def parse_pct(s):
    """'22% Off' / '-22%' / '99%' -> 22.0"""
    if s is None:
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", str(s))
    return float(m.group(1).replace(",", ".")) if m else None


def to_float(x):
    try:
        return float(x) if x not in (None, "") else None
    except (TypeError, ValueError):
        return None


def looks_blocked(text):
    t = (text or "")[:5000].lower()
    return any(k in t for k in BLOCK_MARKERS)


# ======================================================================
# Lưu / resume
# ======================================================================
def load_done_ids(path):
    """Đọc các item_id đã có trong file CSV để bỏ qua khi chạy lại."""
    done = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("item_id"):
                    done.add(row["item_id"])
    return done


def append_row(path, row):
    """Ghi thêm 1 dòng. File mới -> ghi header với BOM (utf-8-sig) để Excel đọc đúng tiếng Việt."""
    new_file = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", encoding="utf-8-sig" if new_file else "utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        if new_file:
            w.writeheader()
        w.writerow({k: row.get(k) for k in COLUMNS})


# ======================================================================
# Playwright (khởi tạo lười - chỉ mở trình duyệt khi cần)
# ======================================================================
class Browser:
    def __init__(self, headless=False):
        self.headless = headless
        self._pw = self._browser = self.ctx = self.page = None
        self.captured = {}  # item_id -> dict module của getdetailinfo
        self.last_capture = None

    def start(self):
        if self.page:
            return self.page
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        # Ưu tiên Google Chrome đã cài trên máy (Chromium đóng gói đôi khi bị chặn chạy trên Windows)
        try:
            self._browser = self._pw.chromium.launch(headless=self.headless, channel="chrome")
        except Exception:
            self._browser = self._pw.chromium.launch(headless=self.headless)
        self.ctx = self._browser.new_context(locale="vi-VN", user_agent=UA,
                                             viewport={"width": 1366, "height": 900})
        self.page = self.ctx.new_page()
        self.page.on("response", self._on_response)
        return self.page

    def _on_response(self, resp):
        """Bắt response của API chi tiết sản phẩm do chính trang gọi."""
        if "mtop.global.detail.web.getdetailinfo" not in resp.url:
            return
        try:
            d = resp.json()
            mod = d.get("data", {}).get("module")
            if not mod:
                return
            m = json.loads(mod) if isinstance(mod, str) else mod
            iid = str(m.get("primaryKey", {}).get("itemId") or
                      m.get("tracking", {}).get("pdt_sku") or "")
            if iid:
                self.captured[iid] = m
            self.last_capture = m  # dự phòng: trang bị chuyển hướng sang item_id khác
        except Exception:
            pass

    def is_captcha(self):
        try:
            url = self.page.url.lower()
            if any(k in url for k in BLOCK_MARKERS):
                return True
            return looks_blocked(self.page.content())
        except Exception:
            return False

    def close(self):
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass


# ======================================================================
# Bước 1: lấy danh sách sản phẩm
# ======================================================================
def fetch_listing_requests(session, query, page):
    url = f"{BASE}/catalog/?q={quote_plus(query)}&ajax=true&page={page}"
    r = session.get(url, headers=HEADERS_JSON, timeout=30)
    if "json" not in r.headers.get("content-type", "") or looks_blocked(r.text):
        return None  # bị chặn
    data = r.json()
    items = data.get("mods", {}).get("listItems")
    return items if isinstance(items, list) else None


def fetch_listing_playwright(br, query, page, wait_captcha=300):
    """Dự phòng: mở endpoint JSON trong trình duyệt thật; nếu gặp captcha thì chờ người dùng giải."""
    pg = br.start()
    url = f"{BASE}/catalog/?q={quote_plus(query)}&ajax=true&page={page}"
    pg.goto(url, wait_until="domcontentloaded", timeout=60000)
    t0, warned = time.time(), False
    while time.time() - t0 < wait_captcha:
        try:
            body = pg.inner_text("body")
            data = json.loads(body)
            return data.get("mods", {}).get("listItems") or []
        except Exception:
            if not warned:
                print("  [!] Có vẻ gặp captcha. Hãy giải captcha trong cửa sổ Chrome vừa mở...")
                warned = True
            time.sleep(3)
            if "ajax=true" not in pg.url:  # giải xong bị chuyển trang -> mở lại endpoint
                pg.goto(url, wait_until="domcontentloaded", timeout=60000)
    return []


def parse_list_item(it, page, rank):
    icons = [i.get("bizType", "") for i in it.get("icons", []) or []]
    qs = it.get("querystring", "") or ""
    sold_raw = it.get("itemSoldCntShow")
    url = it.get("itemUrl", "")
    if url.startswith("//"):
        url = "https:" + url
    m = re.search(r"shop_id:(\d+)", it.get("clickTrace", "") or "")
    return {
        "crawl_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "search_page": page,
        "rank_in_page": rank,
        "item_id": str(it.get("itemId") or it.get("nid")),
        "sku_id": it.get("skuId"),
        "name": it.get("name"),
        "brand": it.get("brandName"),
        "brand_id": it.get("brandId"),
        "category_ids": "|".join(str(c) for c in it.get("categories", []) or []),
        "price": to_float(it.get("price")),
        "original_price": to_float(it.get("originalPrice")),
        "discount_raw": it.get("discount"),
        "discount_pct": parse_pct(it.get("discount")),
        "rating_score": round(to_float(it.get("ratingScore")), 3) if to_float(it.get("ratingScore")) else None,
        "review_count": int(it["review"]) if str(it.get("review", "")).isdigit() else None,
        "sold_raw": sold_raw,
        "sold_num": parse_count(sold_raw),
        "location": it.get("location"),
        "seller_name": it.get("sellerName"),
        "seller_id": it.get("sellerId"),
        "shop_id": m.group(1) if m else None,
        "is_lazmall": int("lazMall" in icons),
        "is_freeship": int("Freeshipping" in icons or "freeshipping=1" in qs),
        "is_sponsored": int(bool(it.get("isSponsored"))),
        "in_stock": int(bool(it.get("inStock"))),
        "url": url,
    }


# ======================================================================
# Bước 2: lấy chi tiết sản phẩm
# ======================================================================
def find_spec(features, *keywords):
    """Tìm giá trị thông số có tên chứa 1 trong các từ khóa (không phân biệt hoa thường)."""
    for k, v in features.items():
        kl = k.lower()
        if any(kw in kl for kw in keywords):
            return v
    return None


def parse_detail(m, name=""):
    out = {}
    # --- danh mục ---
    bc = [b.get("title") for b in m.get("Breadcrumb", []) or []][:-1]  # bỏ phần tử cuối (tên SP)
    out["category_path"] = " > ".join(bc) if bc else None
    out["product_type"] = bc[-1] if bc else None

    # --- người bán ---
    s = m.get("seller", {}) or {}
    out["positive_seller_rating"] = parse_pct((s.get("positiveSellerRating") or {}).get("value"))
    out["is_new_seller"] = int(bool(s.get("newSeller"))) if "newSeller" in s else None
    tags = [t.get("value", "") for t in s.get("storeSellingTags", []) or []]
    out["seller_tags_raw"] = " | ".join(t.replace("\n", " ") for t in tags) or None
    # Một số shop (định dạng cũ) có trường số liệu riêng
    for key in ("shipOnTime", "chatResponse", "chatResponseRate", "shipOnTimeRate"):
        if key in s:
            v = s[key].get("value") if isinstance(s[key], dict) else s[key]
            if "ship" in key.lower():
                out["ship_on_time_rate"] = parse_pct(v)
            else:
                out["chat_response_rate"] = parse_pct(v)
    for t in tags:
        tl = t.lower()
        if "giao" in tl and "%" in tl:
            out.setdefault("ship_on_time_rate", parse_pct(t))
        elif "phản hồi" in tl:
            if "%" in tl:
                out.setdefault("chat_response_rate", parse_pct(t))
            else:
                out["response_time_raw"] = t
        elif "đã bán tại cửa hàng" in tl:
            out["store_sold_raw"] = t
            out["store_sold_num"] = parse_count(t)
        elif "mua lại" in tl:
            out["repurchase_rate"] = parse_pct(t)
        elif "quay lại" in tl:
            out["returning_customers"] = parse_count(t)

    # --- đánh giá: scores = [5 sao, 4 sao, 3 sao, 2 sao, 1 sao] ---
    rv = m.get("review", {}) or {}
    out["rating_avg_detail"] = rv.get("averageRating")
    out["rating_count_detail"] = rv.get("reviews") or rv.get("contentedNum")
    sc = rv.get("scores") or []
    for i, star in enumerate([5, 4, 3, 2, 1]):
        out[f"star_{star}"] = sc[i] if i < len(sc) else None

    # --- biến thể ---
    po = m.get("productOption", {}) or {}
    skus = (po.get("skuBase") or {}).get("skus") or []
    out["n_variants"] = len(skus) if skus else max(len(m.get("skuInfos", {}) or {}) - 1, 1)
    vals = []
    for p in (po.get("skuBase") or {}).get("properties", []) or []:
        vals += [v.get("name", "") for v in p.get("values", []) or []]
    out["variant_names"] = " | ".join(vals) or None

    # --- thông số kỹ thuật (lấy theo SKU đầu tiên) ---
    specs = m.get("specifications", {}) or {}
    feats = {}
    if specs:
        feats = (next(iter(specs.values())) or {}).get("features", {}) or {}
    feats = {k: v for k, v in feats.items() if k not in ("SKU",)}
    out["specs_raw"] = json.dumps(feats, ensure_ascii=False) if feats else None
    alltext = " ".join(str(v) for v in feats.values()) + " " + (name or "")

    bt = find_spec(feats, "phiên bản bluetooth", "bluetooth version")
    if not bt:
        mm = re.search(r"(?:bluetooth|bt|ble)\s*v?\s*(\d\.\d)", alltext, re.I)
        bt = mm.group(1) if mm else None
    out["bluetooth_version"] = bt
    out["battery_hours"] = find_spec(feats, "thời gian sử dụng pin", "pin", "battery")
    wp = find_spec(feats, "chống nước", "kháng nước", "water")
    if not wp:
        mm = re.search(r"\bIP[X\d]\d\b", alltext, re.I)
        wp = mm.group(0).upper() if mm else ("Có" if re.search(r"chống nước|không thấm nước|waterproof", alltext, re.I) else None)
    out["waterproof"] = wp
    out["model"] = find_spec(feats, "model")
    out["connection"] = find_spec(feats, "kết nối", "connect")
    out["driver_type"] = find_spec(feats, "driver")
    out["impedance"] = find_spec(feats, "điện trở", "trở kháng", "impedance")
    out["warranty"] = find_spec(feats, "warranty", "thời gian bảo hành")
    out["warranty_type"] = find_spec(feats, "loại bảo hành")

    # --- cam kết chính hãng, giao hàng ---
    first_sku = next(iter((m.get("warranties") or {}).values()), []) or []
    out["is_authentic_guarantee"] = int(any(w.get("type") == "authenticity" for w in first_sku))
    deliv = next(iter((m.get("deliveryOptions") or {}).values()), []) or []
    out["cod_available"] = int(any(d.get("type") == "COD" for d in deliv))
    std = [d for d in deliv if d.get("dataType") == "delivery"]
    if std:
        out["shipping_fee"] = std[0].get("feeValue")
        out["delivery_time"] = std[0].get("duringTime")
    promo = next(iter(((m.get("promotionTags") or {}).get("data") or {}).values()), []) or []
    out["n_promotions"] = len(promo)
    return out


def fetch_detail(br, url, item_id, wait_captcha=300, timeout=25):
    """Mở trang chi tiết, chờ API getdetailinfo trả về. Gặp captcha thì chờ người dùng giải."""
    pg = br.start()
    br.captured.pop(item_id, None)
    br.last_capture = None
    try:
        pg.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print("  [!] Lỗi tải trang:", str(e)[:100])
    t0, warned = time.time(), False
    limit = timeout
    while time.time() - t0 < limit:
        if item_id in br.captured:
            return br.captured[item_id], "ok"
        if br.last_capture is not None and time.time() - t0 > 8:
            return br.last_capture, "ok_redirected"
        if br.is_captcha():
            if not warned:
                print("  [!] Gặp captcha ở trang chi tiết. Hãy giải trong cửa sổ Chrome (chờ tối đa "
                      f"{wait_captcha}s)...")
                warned = True
                limit = wait_captcha
        else:
            try:
                pg.mouse.wheel(0, 800)  # cuộn nhẹ cho trang nạp hết dữ liệu
            except Exception:
                pass
        time.sleep(1.5)
    return None, ("captcha_timeout" if warned else "no_detail_api")


# ======================================================================
# Chương trình chính
# ======================================================================
def main():
    ap = argparse.ArgumentParser(description="Thu thập tai nghe bluetooth trên Lazada (học tập).")
    ap.add_argument("--query", default="tai nghe bluetooth")
    ap.add_argument("--start-page", type=int, default=1)
    ap.add_argument("--pages", type=int, default=15, help="số trang danh sách tối đa (40 SP/trang)")
    ap.add_argument("--max-items", type=int, default=50, help="tổng số dòng muốn có trong file")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "data", "raw",
                                                  "lazada_tai_nghe_sample.csv"))
    ap.add_argument("--no-detail", action="store_true", help="bỏ qua trang chi tiết")
    ap.add_argument("--skip-sponsored", action="store_true", help="bỏ sản phẩm quảng cáo")
    ap.add_argument("--headless", action="store_true", help="chạy ẩn trình duyệt (dễ bị captcha hơn)")
    ap.add_argument("--min-delay", type=float, default=3.0)
    ap.add_argument("--max-delay", type=float, default=8.0)
    args = ap.parse_args()

    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    done = load_done_ids(out)
    print(f"File: {out}\nĐã có {len(done)} dòng (sẽ bỏ qua khi resume). Mục tiêu: {args.max_items}.")

    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    try:  # vào trang chủ trước để nhận cookie như người dùng thật
        session.get(BASE + "/", headers={"Accept": "text/html", "User-Agent": UA}, timeout=20)
    except Exception:
        pass

    br = Browser(headless=args.headless)
    mode_listing = "requests"
    stats = {"captcha_listing": 0, "detail_ok": 0, "detail_fail": 0}

    try:
        for page in range(args.start_page, args.start_page + args.pages):
            if len(done) >= args.max_items:
                break
            print(f"\n=== Trang danh sách {page} ({mode_listing}) ===")
            items = None
            if mode_listing == "requests":
                try:
                    items = fetch_listing_requests(session, args.query, page)
                except Exception as e:
                    print("  requests lỗi:", e)
                if items is None:
                    print("  -> Bị chặn/captcha với requests, chuyển sang Playwright.")
                    stats["captcha_listing"] += 1
                    mode_listing = "playwright"
            if mode_listing == "playwright":
                items = fetch_listing_playwright(br, args.query, page)
            if not items:
                print("  Không có sản phẩm -> dừng.")
                break

            for rank, it in enumerate(items, 1):
                if len(done) >= args.max_items:
                    break
                row = parse_list_item(it, page, rank)
                if row["item_id"] in done:
                    continue
                if args.skip_sponsored and row["is_sponsored"]:
                    continue
                if not args.no_detail:
                    polite_sleep(args.min_delay, args.max_delay)
                    m, status = fetch_detail(br, row["url"], row["item_id"])
                    row["detail_status"] = status
                    if m:
                        row.update(parse_detail(m, row["name"]))
                        stats["detail_ok"] += 1
                    else:
                        stats["detail_fail"] += 1
                else:
                    row["detail_status"] = "skipped"
                append_row(out, row)
                done.add(row["item_id"])
                print(f"  [{len(done):>3}] {row['item_id']} | {row['price']} | sold={row['sold_raw']} "
                      f"| shop={row.get('positive_seller_rating')}% | {row['detail_status']} | "
                      f"{(row['name'] or '')[:50]}")
            polite_sleep(args.min_delay, args.max_delay)
    except KeyboardInterrupt:
        print("\nĐã dừng bởi người dùng. Dữ liệu đã lưu tới dòng cuối cùng; chạy lại để tiếp tục.")
    finally:
        br.close()

    print(f"\nXong. Tổng dòng trong file: {len(done)}. Listing qua: {mode_listing}. Thống kê: {stats}")


if __name__ == "__main__":
    main()
