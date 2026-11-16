# -*- coding: utf-8 -*-
"""Ghi tiến độ thu thập ra scraper/tien_do.txt (đọc từ CSV chính + các file JSON đã nhận)."""
import csv
import glob
import os
from collections import Counter
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "..", "data", "raw", "lazada_tai_nghe.csv")
DOM = os.path.join(HERE, "..", "data", "raw", "details_dom")
OUT = os.path.join(HERE, "tien_do.txt")
SEC_PER_ITEM = 25  # ~14 s nghỉ + ~10 s tải trang, cộng nghỉ 3 phút mỗi 40 SP


def main():
    rows = list(csv.DictReader(open(CSV, encoding="utf-8-sig")))
    st = Counter(r["detail_status"] for r in rows)
    ok = sum(v for k, v in st.items() if k.startswith("ok"))
    waiting = st.get("listing_only", 0)
    files = sorted(glob.glob(os.path.join(DOM, "lazada_chitiet_*.json")), key=os.path.getmtime)
    last = os.path.basename(files[-1]) if files else "-"
    last_t = datetime.fromtimestamp(os.path.getmtime(files[-1])).strftime("%H:%M:%S") if files else "-"
    status_files = [os.path.basename(f) for f in files if "STATUS" in f]
    eta_min = round(waiting * SEC_PER_ITEM / 60 + (waiting // 40) * 3)
    eta = (datetime.now() + timedelta(minutes=eta_min)).strftime("%H:%M")
    lines = [
        "TIẾN ĐỘ THU THẬP LAZADA - tai nghe bluetooth (đồ án DS111)",
        f"Cập nhật lúc      : {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"Có chi tiết       : {ok} / {len(rows)} dòng  ({ok * 100 // len(rows)}%)",
        f"  - từ API (có sao 1-5)   : {st.get('ok', 0) + st.get('ok_redirected', 0)}",
        f"  - đọc từ giao diện       : {st.get('ok_dom', 0) + st.get('ok_dom_partial', 0)}",
        f"Chỉ xem trên app  : {st.get('app_only', 0)}",
        f"Lỗi/timeout       : {st.get('timeout', 0) + st.get('no_detail_api', 0)}",
        f"Còn chờ           : {waiting}",
        f"File gộp gần nhất : {last} (lúc {last_t})  - tổng {len(files)} file",
        f"Dự kiến xong      : ~{eta} (còn ~{eta_min} phút)" if waiting else "Dự kiến xong      : ĐÃ XONG",
        f"Trạng thái cuối   : {', '.join(status_files) if status_files else 'đang chạy'}",
        "",
        "Lưu ý: file này cập nhật mỗi phút theo dữ liệu ĐÃ GỘP vào CSV (mỗi đợt 40 SP).",
        "Tiến độ từng sản phẩm xem ở khung đen góc phải tab Lazada trong Chrome / tiêu đề tab.",
    ]
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, OUT)


if __name__ == "__main__":
    main()
