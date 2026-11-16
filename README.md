# Đồ án DS101.R11 — Bộ dữ liệu GPU tự thu thập từ TechPowerUp

Nguồn: https://www.techpowerup.com/gpu-specs/ — mọi GPU (desktop, mobile, IGP, workstation) phát hành 2000–2026.

## Cấu trúc

```
scraper/tpu_parse.py     bóc tách HTML (không truy cập mạng, test được offline)
scraper/tpu_scraper.py   CLI: probe | crawl | parse | all
tests/test_parse.py      test parser bằng HTML mô phỏng
data/cache/              HTML đã tải (lists/, gpus/) — KHÔNG xoá, đây là bằng chứng nguồn + cho phép parse lại
data/links.csv           id + URL mọi card đã phát hiện
data/raw_gpu_data.csv    ★ đầu ra Phase 2: 55 cột raw dạng chuỗi
data/raw_gpu_all_fields.csv  mọi trường "Section::Label" (dự phòng)
reports/parse_report.md  tỉ lệ điền từng cột
logs/scrape.log          nhật ký crawl
```

## Chạy (PowerShell, tại thư mục này)

```powershell
pip install -r requirements.txt
python -m pytest tests -q                          # 6 test offline

python scraper/tpu_scraper.py probe               # 3 request — gửi output cho Claude
python scraper/tpu_scraper.py crawl --max-pages 40
python scraper/tpu_scraper.py parse               # xem reports\parse_report.md
python scraper/tpu_scraper.py crawl               # toàn bộ, để máy chạy (vài giờ)
python scraper/tpu_scraper.py parse
```

- **Dừng/tiếp tục:** Ctrl+C lúc nào cũng được; chạy lại `crawl` sẽ dựng lại hàng đợi từ cache.
- **Bị chặn** (log "DỪNG vì bị chặn", exit code 2): crawler dừng NGAY ở 403/410/captcha. Đợi vài giờ, mở
  https://www.techpowerup.com/gpu-specs/ bằng trình duyệt thấy bình thường rồi mới chạy lại.
- Nghỉ ngẫu nhiên 30–60 s/request (đề bài gợi ý 1–3 s; tăng lên vì site đã từng gắn captcha), 1 luồng.

## Ghi chú phương pháp (đưa vào báo cáo)

- `robots.txt` của TechPowerUp cho phép `User-agent: *` truy cập `/gpu-specs/`, chặn các bot AI/huấn luyện LLM
  và bảo lưu quyền sử dụng thương mại → dữ liệu chỉ dùng cho mục đích học tập, không phân phối lại, ghi nguồn.
  Crawler do sinh viên chạy, User-Agent tự khai báo là dự án sinh viên phi thương mại.
- Bộ lọc của trang danh sách được site cố ý mã hoá để bot không dùng được ("spidertrap"; gọi sai tham số -> HTTP 410
  + captcha, đã gặp 13/11/2026). Crawler vì vậy KHÔNG dùng URL có query string, chỉ đi theo link công khai:
  trang gốc -> trang card (.c####) <-> trang chip (.g####, liệt kê mọi card dùng chip), FIFO từng nhóm, xen kẽ card/chip,
  khử trùng theo id; lọc năm phát hành 2000–2026 ở bước parse.

## Bộ điều phối theo đợt (15/11/2026)

Tận dụng ý tưởng chia đợt, lưu tiến độ, gộp dữ liệu và theo dõi của bộ Lazada của Huy; không chạy mã Lazada hoặc dùng profile Chrome đi kèm.

```powershell
python scraper/tpu_scraper.py crawl --max-pages 10
python scraper/tpu_scraper.py crawl
python scraper/dashboard.py
```

- Mặc định 20 trang/đợt, nghỉ 30–60 giây/request, nghỉ 120–240 giây giữa đợt. Điều chỉnh bằng `--batch-size`, `--batch-pause-min`, `--batch-pause-max`.
- `--max-pages` tính số trang đã thử, không phải số trang tải thành công. Dashboard tách attempted/saved/failed.
- Hàng đợi và lỗi lưu trong `data/runtime/checkpoint.json`; trạng thái cập nhật mỗi 5 giây trong `status.json`. Chỉ ghi thành công sau khi HTML được lưu.
- Khóa hệ điều hành ngăn hai lượt crawl của bản mới chạy cùng lúc. Không chạy song song bản cũ/probe/parse khi crawler đang xuất CSV.
- Tự parse sau mỗi đợt và khi dừng/kết thúc nếu có card. Lỗi xuất CSV được ghi riêng, không xóa HTML.
- CAPTCHA/403/410 dừng lượt, không tự khởi động lại. Trang lỗi tải được giữ để lần chạy sau thử lại; trạng thái finished_with_errors không có nghĩa đủ dữ liệu.
- Dashboard tại http://127.0.0.1:8766/; mất heartbeat quá 90 giây sẽ báo chưa xác nhận crawler còn chạy. Độ phủ năm tính từ lần xuất CSV gần nhất.
- Đây vẫn là cơ chế tải HTTP hiện có, chưa có bộ đọc giao diện Chrome. Tái cấu trúc không giải quyết hạn chế truy cập trình duyệt hoặc bảo đảm tránh CAPTCHA.
