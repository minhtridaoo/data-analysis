# -*- coding: utf-8 -*-
"""
Bước hoàn thiện sau khi thu thập xong:
  1. Tính lại battery_hours cho TOÀN BỘ file từ specs_raw (chỉ lấy "Thời gian sử dụng pin (giờ)",
     bỏ "Dung lượng pin" là mAh - lỗi của phiên bản đầu).
  2. Chuẩn hóa vài cột số (battery_hours, bluetooth_version, impedance_ohm, warranty_months).
  3. Tạo lại data/raw/data_dictionary_lazada.csv (mô tả, kiểu, % có giá trị, ví dụ).
  4. In thống kê cuối.
Không xóa cột nào của dữ liệu gốc; chỉ thêm cột số đã chuẩn hóa (hậu tố _num).
"""
import json
import os
import re
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "..", "data", "raw")
CSV = os.path.join(RAW, "lazada_tai_nghe.csv")
DICT = os.path.join(RAW, "data_dictionary_lazada.csv")


def spec(js, *keys):
    if not isinstance(js, str) or not js.strip():
        return None
    try:
        d = json.loads(js)
    except ValueError:
        return None
    for k, v in d.items():
        if any(x in k.lower() for x in keys):
            return v
    return None


def first_num(s):
    m = re.search(r"\d+(?:[.,]\d+)?", str(s)) if s is not None and str(s) != "nan" else None
    return float(m.group().replace(",", ".")) if m else None


def warranty_months(s):
    if s is None or str(s) == "nan":
        return None
    s = str(s).lower()
    n = first_num(s)
    if n is None:
        return 0.0 if "không" in s else None
    if "năm" in s or "year" in s:
        return n * 12
    if "ngày" in s or "day" in s:
        return round(n / 30, 2)
    return n  # mặc định là tháng


def main():
    df = pd.read_csv(CSV, encoding="utf-8-sig", dtype={"item_id": str, "sku_id": str, "seller_id": str,
                                                        "shop_id": str, "brand_id": str})
    # 1. battery_hours lấy lại từ specs_raw
    bh = df["specs_raw"].apply(lambda s: spec(s, "thời gian sử dụng pin", "battery life", "(giờ)"))
    df["battery_hours"] = bh.where(bh.notna(), None)
    # 2. cột số chuẩn hóa
    df["battery_hours_num"] = df["battery_hours"].apply(first_num)
    df.loc[df["battery_hours_num"] > 500, "battery_hours_num"] = None   # giá trị vô lý (shop nhập sai)
    df["bluetooth_version_num"] = df["bluetooth_version"].apply(first_num)
    df.loc[(df["bluetooth_version_num"] < 1) | (df["bluetooth_version_num"] > 6.5), "bluetooth_version_num"] = None
    df["impedance_ohm"] = df["impedance"].apply(first_num)
    df["warranty_months"] = df["warranty"].apply(warranty_months)
    df.to_csv(CSV, index=False, encoding="utf-8-sig")

    # 3. từ điển dữ liệu
    old = pd.read_csv(DICT, encoding="utf-8-sig") if os.path.exists(DICT) else pd.DataFrame(columns=["cot"])
    desc_old = dict(zip(old.get("cot", []), old.get("mo_ta", [])))
    note_old = dict(zip(old.get("cot", []), old.get("ghi_chu", [])))
    extra_desc = {
        "shop_age_years": "Số năm shop hoạt động (giao diện)",
        "reviews_with_media": "Số đánh giá có hình/video",
        "review_tag_repurchase": "Số đánh giá gắn nhãn 'Khách đã mua lại'",
        "review_tags_raw": "Nhãn đánh giá (chuỗi gốc)",
        "battery_hours_num": "Thời lượng pin (giờ, số)",
        "bluetooth_version_num": "Phiên bản Bluetooth (số)",
        "impedance_ohm": "Trở kháng (ohm, số)",
        "warranty_months": "Thời gian bảo hành (tháng, số)",
    }
    rows = []
    listing_cols = list(df.columns[:26])
    for c in df.columns:
        s = df[c]; nn = s.dropna()
        if s.dtype.kind in "if":
            typ = "bool" if set(nn.unique()) <= {0, 1} and len(nn) else "số"
        else:
            typ = "chữ"
        rows.append({
            "nhom": "A-listing" if c in listing_cols else "B-chi tiet",
            "cot": c,
            "mo_ta": extra_desc.get(c) or desc_old.get(c, ""),
            "kieu": typ if len(nn) else "trống",
            "pct_co": round(s.notna().mean() * 100, 1),
            "vi_du": str(nn.iloc[0])[:40] if len(nn) else "",
            "ghi_chu": note_old.get(c, "") if isinstance(note_old.get(c, ""), str) else "",
        })
    pd.DataFrame(rows).to_csv(DICT, index=False, encoding="utf-8-sig")

    # 4. thống kê
    st = df["detail_status"].value_counts().to_dict()
    ok = sum(v for k, v in st.items() if str(k).startswith("ok"))
    print("Kích thước:", df.shape, "| item_id trùng:", df["item_id"].duplicated().sum())
    print("detail_status:", st, "| có chi tiết:", ok)
    key = ["price", "original_price", "discount_pct", "rating_score", "review_count", "sold_num",
           "location", "is_lazmall", "is_freeship", "product_type", "positive_seller_rating",
           "ship_on_time_rate", "response_time_raw", "store_sold_num", "shop_age_years",
           "rating_avg_detail", "rating_count_detail", "reviews_with_media", "star_5", "n_variants",
           "bluetooth_version_num", "battery_hours_num", "waterproof", "impedance_ohm",
           "warranty_months", "is_authentic_guarantee", "shipping_fee"]
    print((df[key].notna().mean() * 100).round(1).to_string())


if __name__ == "__main__":
    main()
