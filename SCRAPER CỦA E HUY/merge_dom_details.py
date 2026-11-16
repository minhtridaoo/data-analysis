# -*- coding: utf-8 -*-
"""
Gộp dữ liệu chi tiết đọc từ GIAO DIỆN trang sản phẩm (lấy bằng Claude in Chrome - trình duyệt thật
của người dùng, đọc phần chữ hiển thị trên trang) vào file CSV chính.

Đầu vào : file JSON {item_id: {...}} (mỗi giá trị là kết quả hàm __lzExtract trong trình duyệt)
Đầu ra  : cập nhật các cột chi tiết trong data/raw/lazada_tai_nghe.csv cho các dòng tương ứng.

Lưu ý: giao diện web hiện KHÔNG hiển thị phân bố số sao 1-5 -> các cột star_* chỉ có ở những dòng
lấy bằng API trước đó. Thêm 2 cột mới lấy được từ giao diện: shop_age_years, reviews_with_media,
review_tag_repurchase.

Cách dùng: python merge_dom_details.py <file_json> [--csv ../data/raw/lazada_tai_nghe.csv]
"""
import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lazada_scraper import COLUMNS, parse_count, parse_pct, find_spec, rewrite_csv  # noqa: E402



def parse_dom(r, name=""):
    out = {}
    crumbs = r.get("crumbs") or []
    out["category_path"] = " > ".join(crumbs) or None
    out["product_type"] = crumbs[-1] if crumbs else None

    # --- khối người bán: mỗi dòng 1 thông tin ---
    lines = [l.strip() for l in (r.get("seller") or "").split("\n") if l.strip()]
    tags = []
    for l in lines[1:]:
        ll = l.lower()
        if ll in ("chat", "đến gian hàng"):
            continue
        tags.append(l)
        if "đánh giá tích cực" in ll:
            out["positive_seller_rating"] = parse_pct(l)
        elif "đã bán tại cửa hàng" in ll:
            out["store_sold_raw"], out["store_sold_num"] = l, parse_count(l)
        elif "phản hồi" in ll:
            if "%" in l:
                out["chat_response_rate"] = parse_pct(l)
            else:
                out["response_time_raw"] = l
        elif "giao" in ll and "%" in l:
            out["ship_on_time_rate"] = parse_pct(l)
        elif "mua lại" in ll:
            out["repurchase_rate"] = parse_pct(l)
        elif "quay lại" in ll:
            out["returning_customers"] = parse_count(l)
        elif re.match(r"cửa hàng \d+ năm", ll):
            out["shop_age_years"] = int(re.search(r"\d+", ll).group())
        elif "nhà bán hàng mới" in ll or "shop mới" in ll:
            out["is_new_seller"] = 1
    out["seller_tags_raw"] = " | ".join(tags) or None
    if lines and "is_new_seller" not in out:
        out["is_new_seller"] = 0

    # --- đánh giá ---
    # điểm: ưu tiên ô score-average; nếu không có (ít đánh giá) lấy số đầu của khối tóm tắt "4.8\n(442)"
    score = r.get("score")
    if not score:
        mm = re.match(r"\s*(\d(?:[.,]\d)?)\s*\n?\s*\(", r.get("summary") or "")
        score = mm.group(1).replace(",", ".") if mm else None
    try:
        out["rating_avg_detail"] = float(score) if score else None
    except ValueError:
        out["rating_avg_detail"] = None
    m = re.search(r"\((\d+)\)", r.get("title_count") or r.get("summary") or "")
    out["rating_count_detail"] = int(m.group(1)) if m else (0 if r.get("seller") else None)
    tags_txt = r.get("review_tags") or ""
    out["review_tags_raw"] = tags_txt or None
    m = re.search(r"Có hình/video\((\d+)\)", tags_txt)
    out["reviews_with_media"] = int(m.group(1)) if m else 0
    m = re.search(r"Khách đã mua lại\((\d+)\)", tags_txt)
    out["review_tag_repurchase"] = int(m.group(1)) if m else 0

    # --- biến thể: "Màu sắc: | Đen | Trắng || Kích cỡ: | ..." ---
    groups = [g for g in (r.get("sku") or "").split("||") if g.strip()]
    vals, n = [], 1
    for g in groups:
        parts = [p.strip() for p in g.split("|") if p.strip()]
        v = [p for p in parts if not p.endswith(":")]
        # giao diện in giá trị đang chọn trước danh sách -> bỏ trùng, giữ thứ tự
        v = list(dict.fromkeys(v))
        if v:
            vals += v
            n *= len(v)
    out["n_variants"] = n if groups else 1
    out["variant_names"] = " | ".join(vals) or None

    # --- thông số ---
    feats = r.get("specs") or {}
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

    # --- dịch vụ / giao hàng ---
    svc = r.get("service") or ""
    out["is_authentic_guarantee"] = int("chính hãng" in svc.lower()) if svc else None
    deliv = r.get("delivery") or ""
    # giao diện mới không luôn hiện COD -> chỉ ghi 1 khi thấy, còn lại để trống (không suy ra 0)
    out["cod_available"] = 1 if re.search(r"khi nhận hàng|\bCOD\b", deliv, re.I) else None
    m = re.search(r"([\d.]+)\s*₫", deliv)
    out["shipping_fee"] = float(m.group(1).replace(".", "")) if m else None
    m = re.search(r"(Đảm bảo nhận[^\n]*|Nhận hàng[^\n]*|\d+\s*-\s*\d+\s*ngày[^\n]*)", deliv)
    out["delivery_time"] = m.group(1).strip() if m else None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json_file")
    ap.add_argument("--csv", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                  "..", "data", "raw", "lazada_tai_nghe.csv"))
    a = ap.parse_args()
    res = json.load(open(a.json_file, encoding="utf-8"))
    with open(a.csv, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    cols = list(COLUMNS)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    upd = {}
    for r in rows:
        v = res.get(r["item_id"])
        # không ghi đè dòng đã có chi tiết từ API (có thêm phân bố sao)
        if not v or r.get("detail_status") in ("ok", "ok_redirected"):
            continue
        st = v.get("status", "")
        if st in ("ok", "ok_partial"):
            r.update({k: ("" if x is None else x) for k, x in parse_dom(v, r.get("name", "")).items()})
            r["detail_status"] = "ok_dom" if st == "ok" else "ok_dom_partial"
            r["detail_time"] = now
        elif st in ("app_only", "captcha", "timeout") or st.startswith("err"):
            r["detail_status"] = st if st != "captcha" else r.get("detail_status")
        upd[st] = upd.get(st, 0) + 1
    # ghi lại với bộ cột mở rộng
    tmp = a.csv + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})
    os.replace(tmp, a.csv)
    print("Cập nhật:", upd)
    from collections import Counter
    print("detail_status:", dict(Counter(r["detail_status"] for r in rows)))


if __name__ == "__main__":
    main()
