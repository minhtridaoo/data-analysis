# -*- coding: utf-8 -*-
"""
Thu thập dữ liệu sản phẩm "tai nghe bluetooth" trên Lazada Việt Nam.
Mục đích: chỉ phục vụ học tập (đồ án môn DS111 - Phân tích dữ liệu), số lượng nhỏ, chạy chậm.

Phiên bản 2 (sau khi lần chạy thử bằng requests bị Lazada hiện captcha):
  - Mọi truy cập đều đi qua MỘT trình duyệt Chrome thật (Playwright, có giao diện) với profile riêng
    lưu ở scraper/chrome_profile -> giữ cookie giữa các lần chạy, giống người dùng quay lại.
  - Danh sách (listing): mở trang tìm kiếm https://www.lazada.vn/catalog/?q=...&page=N trong chính
    trình duyệt đó, đọc dữ liệu JSON của trang (window.pageData / response ajax).
  - Chi tiết (detail): mở trang sản phẩm, "nghe" response API `mtop.global.detail.web.getdetailinfo`
    do trang tự gọi -> điểm shop, giao đúng hạn, phân bố sao 1-5, biến thể, thông số kỹ thuật...
  - Nghỉ ngẫu nhiên 8-20 giây giữa các trang chi tiết; mỗi đợt tối đa --batch-size (mặc định 40)
    sản phẩm MỚI rồi tự dừng. Nghỉ 30-60 phút rồi mới chạy đợt tiếp theo.
  - Gặp captcha: chờ NGƯỜI DÙNG tự giải trong cửa sổ Chrome (tối đa --captcha-wait giây).
    Nếu không giải -> dừng cả đợt ngay (không thử lại liên tục).
  - Resume: lưu dần từng dòng vào CSV; chạy lại sẽ bỏ qua item_id đã có.

Các chế độ:
  (mặc định)        listing + chi tiết cho sản phẩm mới
  --listing-only    chỉ lấy các trường từ trang tìm kiếm (nhanh, ít bị chặn); detail_status = listing_only
  --fill-details    bổ sung chi tiết cho các dòng đã có trong CSV mà detail_status != ok

Ví dụ:
  python lazada_scraper.py --out ../data/raw/lazada_tai_nghe.csv                      # 1 đợt 40 SP
  python lazada_scraper.py --listing-only --pages 12 --max-items 450 --out ../data/raw/lazada_tai_nghe.csv
  python lazada_scraper.py --fill-details --out ../data/raw/lazada_tai_nghe.csv       # bổ sung 40 dòng/đợt
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

# Windows console mặc định cp1252 -> ép UTF-8 để in tiếng Việt không lỗi
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "https://www.lazada.vn"
PROFILE_DIR = os.path.join(HERE, "chrome_profile")

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
    "n_promotions", "specs_raw",
    # --- chỉ có khi đọc giao diện trang (Claude in Chrome) ---
    "shop_age_years", "reviews_with_media", "review_tag_repurchase", "review_tags_raw",
    "detail_status", "detail_time",
]

BLOCK_MARKERS = ("punish", "captcha", "slide to verify", "nc_1_n1z", "baxia", "_____tmd_____")


class Blocked(Exception):
    """Bị chặn và người dùng không giải captcha kịp -> dừng đợt."""


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
    if not new_file:
        # File cũ có bộ cột khác (phiên bản trước) -> nâng cấp header trước khi ghi thêm
        with open(path, encoding="utf-8-sig", newline="") as f:
            header = next(csv.reader(f), [])
        if header != COLUMNS:
            with open(path, encoding="utf-8-sig", newline="") as f:
                old_rows = list(csv.DictReader(f))
            rewrite_csv(path, old_rows)
    with open(path, "a", encoding="utf-8-sig" if new_file else "utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        if new_file:
            w.writeheader()
        w.writerow({k: row.get(k) for k in COLUMNS})


def rewrite_csv(path, rows):
    """Ghi lại toàn bộ file (dùng cho --fill-details khi cập nhật dòng cũ). Ghi ra file tạm rồi thay thế."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in COLUMNS})
    os.replace(tmp, path)


# ======================================================================
# Trình duyệt Chrome thật với profile riêng (persistent context)
# ======================================================================
class Browser:
    def __init__(self, headless=False, captcha_wait=300):
        self.headless = headless
        self.captcha_wait = captcha_wait
        self._pw = self.ctx = self.page = None
        self.captured = {}          # item_id -> module của getdetailinfo
        self.last_capture = None
        self.listing_json = None    # JSON danh sách bắt được từ response ajax

    def start(self):
        if self.page:
            return self.page
        from playwright.sync_api import sync_playwright
        os.makedirs(PROFILE_DIR, exist_ok=True)
        self._pw = sync_playwright().start()
        opts = dict(user_data_dir=PROFILE_DIR, headless=self.headless, locale="vi-VN",
                    viewport={"width": 1366, "height": 900})
        # Ưu tiên Google Chrome đã cài trên máy (Chromium đóng gói bị Windows chặn chạy trên máy này)
        try:
            self.ctx = self._pw.chromium.launch_persistent_context(channel="chrome", **opts)
        except Exception:
            self.ctx = self._pw.chromium.launch_persistent_context(**opts)
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.page.on("response", self._on_response)
        return self.page

    def _on_response(self, resp):
        url = resp.url
        try:
            if "mtop.global.detail.web.getdetailinfo" in url:
                d = resp.json()
                mod = d.get("data", {}).get("module")
                if not mod:
                    return
                m = json.loads(mod) if isinstance(mod, str) else mod
                iid = str(m.get("primaryKey", {}).get("itemId") or m.get("tracking", {}).get("pdt_sku") or "")
                if iid:
                    self.captured[iid] = m
                self.last_capture = m  # dự phòng khi trang chuyển hướng sang item_id khác
            elif "/catalog/" in url and "ajax=true" in url:
                d = resp.json()
                if d.get("mods", {}).get("listItems"):
                    self.listing_json = d
        except Exception:
            pass

    def is_captcha(self):
        try:
            if any(k in self.page.url.lower() for k in BLOCK_MARKERS):
                return True
            html = self.page.content().lower()
            # trang captcha của Lazada rất ngắn; trang thật dài -> chỉ xét phần đầu
            return any(k in html[:20000] for k in BLOCK_MARKERS) and len(html) < 200000
        except Exception:
            return False

    def wait_for_human(self, check_ok):
        """Có captcha: chờ người dùng giải. check_ok() trả True khi đã có dữ liệu. Hết giờ -> Blocked."""
        print(f"  [!] Gặp captcha. Hãy tự giải trong cửa sổ Chrome (chờ tối đa {self.captcha_wait}s)...")
        t0 = time.time()
        while time.time() - t0 < self.captcha_wait:
            time.sleep(3)
            if check_ok():
                print("  [v] Đã qua captcha, tiếp tục.")
                return True
        raise Blocked("captcha không được giải")

    def close(self):
        try:
            if self.ctx:
                self.ctx.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass


# ======================================================================
# Bước 1: lấy danh sách sản phẩm qua trang tìm kiếm trong trình duyệt
# ======================================================================
def _extract_list_items(br):
    """Lấy listItems từ trang tìm kiếm đang mở: window.pageData -> JSON ajax đã bắt -> fetch cùng origin."""
    pg = br.page
    try:
        items = pg.evaluate("() => (window.pageData && window.pageData.mods && window.pageData.mods.listItems) || null")
        if items:
            return items
    except Exception:
        pass
    if br.listing_json:
        return br.listing_json["mods"]["listItems"]
    return None


def fetch_listing(br, query, page):
    pg = br.start()
    br.listing_json = None
    url = f"{BASE}/catalog/?q={quote_plus(query)}&page={page}"
    pg.goto(url, wait_until="domcontentloaded", timeout=60000)
    t0 = time.time()
    while time.time() - t0 < 20:
        items = _extract_list_items(br)
        if items:
            return items
        if br.is_captcha():
            br.wait_for_human(lambda: bool(_extract_list_items(br)) or
                              ("catalog" in pg.url and not br.is_captcha()))
            if "catalog" not in pg.url:
                pg.goto(url, wait_until="domcontentloaded", timeout=60000)
            t0 = time.time()
        time.sleep(1.5)
    # Phương án cuối: gọi endpoint ajax ngay trong trang (cùng cookie, cùng origin)
    try:
        d = pg.evaluate("async (u) => { const r = await fetch(u, {credentials: 'include'});"
                        " return await r.json(); }",
                        f"{BASE}/catalog/?q={quote_plus(query)}&ajax=true&page={page}")
        return d.get("mods", {}).get("listItems") or []
    except Exception:
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
    # chỉ lấy THỜI LƯỢNG (giờ), tránh nhầm "Dung lượng pin" (mAh)
    out["battery_hours"] = find_spec(feats, "thời gian sử dụng pin", "battery life", "(giờ)")
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


def fetch_detail(br, url, item_id, timeout=25):
    """Mở trang chi tiết, chờ API getdetailinfo trả về. Gặp captcha -> chờ người dùng (hoặc Blocked)."""
    pg = br.start()
    br.captured.pop(item_id, None)
    br.last_capture = None
    try:
        pg.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print("  [!] Lỗi tải trang:", str(e)[:100])
    t0 = time.time()
    while time.time() - t0 < timeout:
        if item_id in br.captured:
            return br.captured[item_id], "ok"
        if br.last_capture is not None and time.time() - t0 > 8:
            return br.last_capture, "ok_redirected"
        if br.is_captcha():
            br.wait_for_human(lambda: item_id in br.captured or br.last_capture is not None
                              or not br.is_captcha())
            t0 = time.time()  # sau khi giải, cho trang thêm thời gian nạp
            continue
        try:
            pg.mouse.wheel(0, 700)  # cuộn nhẹ như người đọc trang
        except Exception:
            pass
        time.sleep(1.5)
    return None, "no_detail_api"


def apply_detail(br, row, args):
    m, status = fetch_detail(br, row["url"], row["item_id"])
    row["detail_status"] = status
    row["detail_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if m:
        row.update(parse_detail(m, row.get("name") or ""))
    return m is not None


# ======================================================================
# Chế độ chạy
# ======================================================================
def run_collect(br, args, out):
    """Listing (+ chi tiết nếu không --listing-only) cho các sản phẩm CHƯA có trong file."""
    done = load_done_ids(out)
    print(f"Đã có {len(done)} dòng. Mục tiêu tổng: {args.max_items}. Đợt này tối đa {args.batch_size} SP mới.")
    new_cnt = 0
    for page in range(args.start_page, args.start_page + args.pages):
        if len(done) >= args.max_items or new_cnt >= args.batch_size:
            break
        print(f"\n=== Trang tìm kiếm {page} ===")
        items = fetch_listing(br, args.query, page)
        if not items:
            print("  Không đọc được sản phẩm -> dừng.")
            break
        fresh = 0
        for rank, it in enumerate(items, 1):
            if len(done) >= args.max_items or new_cnt >= args.batch_size:
                break
            row = parse_list_item(it, page, rank)
            if row["item_id"] in done or (args.skip_sponsored and row["is_sponsored"]):
                continue
            fresh += 1
            if args.listing_only:
                row["detail_status"] = "listing_only"
            else:
                polite_sleep(args.min_delay, args.max_delay)
                apply_detail(br, row, args)
            append_row(out, row)
            done.add(row["item_id"])
            new_cnt += 1
            print(f"  [{len(done):>3}] {row['item_id']} | {row['price']} | {row['sold_raw']} | "
                  f"shop={row.get('positive_seller_rating')} | {row['detail_status']} | {(row['name'] or '')[:45]}")
        if fresh == 0:
            print("  (trang này toàn sản phẩm đã có)")
        polite_sleep(args.page_min_delay, args.page_max_delay)
    return new_cnt


def run_fill_details(br, args, out):
    """Bổ sung chi tiết cho các dòng đã có mà detail_status != ok (ví dụ lấy bằng --listing-only)."""
    with open(out, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    todo = [r for r in rows if not str(r.get("detail_status", "")).startswith("ok")]
    print(f"{len(rows)} dòng, {len(todo)} dòng thiếu chi tiết. Đợt này làm tối đa {args.batch_size}.")
    n = 0
    try:
        for r in todo[:args.batch_size]:
            polite_sleep(args.min_delay, args.max_delay)
            apply_detail(br, r, args)
            n += 1
            print(f"  [{n:>3}] {r['item_id']} | {r['detail_status']} | shop={r.get('positive_seller_rating')}")
            if n % 5 == 0:
                rewrite_csv(out, rows)  # lưu định kỳ
    finally:
        rewrite_csv(out, rows)
    return n


def main():
    ap = argparse.ArgumentParser(description="Thu thập tai nghe bluetooth trên Lazada (học tập).")
    ap.add_argument("--query", default="tai nghe bluetooth")
    ap.add_argument("--start-page", type=int, default=1)
    ap.add_argument("--pages", type=int, default=15, help="số trang tìm kiếm tối đa (40 SP/trang)")
    ap.add_argument("--max-items", type=int, default=500, help="tổng số dòng mong muốn trong file")
    ap.add_argument("--batch-size", type=int, default=40, help="số SP mới tối đa mỗi đợt chạy rồi dừng")
    ap.add_argument("--out", default=os.path.join(HERE, "..", "data", "raw", "lazada_tai_nghe.csv"))
    ap.add_argument("--listing-only", action="store_true", help="chỉ lấy trường từ trang tìm kiếm")
    ap.add_argument("--fill-details", action="store_true", help="bổ sung chi tiết cho dòng còn thiếu")
    ap.add_argument("--skip-sponsored", action="store_true", help="bỏ sản phẩm quảng cáo")
    ap.add_argument("--headless", action="store_true", help="chạy ẩn (KHÔNG khuyến nghị: không giải được captcha)")
    ap.add_argument("--captcha-wait", type=int, default=300, help="số giây chờ người dùng giải captcha")
    ap.add_argument("--min-delay", type=float, default=8.0, help="nghỉ tối thiểu giữa trang chi tiết (s)")
    ap.add_argument("--max-delay", type=float, default=20.0, help="nghỉ tối đa giữa trang chi tiết (s)")
    ap.add_argument("--page-min-delay", type=float, default=5.0, help="nghỉ tối thiểu giữa trang tìm kiếm (s)")
    ap.add_argument("--page-max-delay", type=float, default=12.0, help="nghỉ tối đa giữa trang tìm kiếm (s)")
    args = ap.parse_args()
    if args.listing_only:
        args.batch_size = max(args.batch_size, args.max_items)  # listing nhẹ -> không giới hạn theo đợt

    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    print(f"File: {out}\nProfile Chrome: {PROFILE_DIR}")

    br = Browser(headless=args.headless, captcha_wait=args.captcha_wait)
    n = 0
    try:
        if args.fill_details:
            if not os.path.exists(out):
                sys.exit("Chưa có file CSV để bổ sung.")
            n = run_fill_details(br, args, out)
        else:
            n = run_collect(br, args, out)
    except Blocked:
        print("\n[X] Bị chặn và captcha không được giải -> DỪNG đợt này. Đợi 30-60 phút rồi chạy lại "
              "(dữ liệu đã lưu, sẽ tự resume).")
    except KeyboardInterrupt:
        print("\nĐã dừng bởi người dùng. Dữ liệu đã lưu; chạy lại để tiếp tục.")
    finally:
        br.close()
    print(f"\nXong đợt: xử lý {n} sản phẩm. Tổng dòng trong file: {len(load_done_ids(out))}.")


if __name__ == "__main__":
    main()
