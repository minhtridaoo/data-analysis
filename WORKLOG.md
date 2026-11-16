# WORKLOG — Đồ án DS101 GPU dataset

## 13/11/2026 — Phase 1 + Phase 2 (code)
- Phase 1 duyệt: lấy TẤT CẢ phân khúc, năm 2000–2026, Claude toàn quyền chọn cột → raw 55 cột
  (25 feature đã đề xuất + clock/cache/hiệu năng/board/API phụ), cột segment sẽ suy ra ở Phase 3.
- Viết scraper/tpu_parse.py + scraper/tpu_scraper.py; 4 test offline + smoke test end-to-end với mạng giả lập: đạt.
- CHƯA crawl thật: robots.txt chặn Claude nên Claude không tự gọi site; Trí chạy trên máy mình.
- Cấu trúc trang (class `gpudb-name`, `section.details`, `table.processors`, tên tham số lọc) là theo hiểu biết,
  chưa xác nhận trên trang thật → bước đầu tiên là `probe`.

## 13/11/2026 (chiều) — probe lần 1 thất bại, đổi chiến lược
- `probe`: trang gốc OK (100 card, 54 chip, bảng `items-desktop-table`), nhưng `?mfgr=NVIDIA&released=2022`
  -> HTTP 410 rồi captcha. Nguyên nhân: site đã đổi giao diện, bộ lọc thật dùng `year=` và URL lọc được mã hoá
  base64-đảo-ngược kèm chú thích "để bad bots không tìm thấy (spidertrap)" -> tham số sai bị coi là bot.
- Quyết định: KHÔNG dùng bộ lọc (tôn trọng ý chủ site, tránh bẫy). Viết lại thành BFS theo link công khai card/chip,
  dừng ngay khi 403/410/captcha, delay 2–5 s, lọc năm ở parse. 6 test + smoke test giả lập: đạt.
- IP của Trí đang bị gắn captcha -> phải đợi trước khi chạy lại.

## Việc tiếp theo
1. [ ] Đợi vài giờ, kiểm bằng trình duyệt; chạy `probe`, gửi output (nhãn trang card giao diện mới chưa xác nhận).
2. [ ] `crawl --max-pages 40` -> `parse` -> xem parse_report.md (độ phủ năm cũ qua link chip/card).
3. [ ] `crawl` toàn bộ -> `parse` -> Phase 3.
4. [ ] Dự phòng nếu bị chặn kéo dài: bảng "List of Nvidia/AMD/Intel GPUs" trên Wikipedia (CC BY-SA).

## 13/11/2026 — Sửa lịch tải sau pilot
- Cache thực tế: 52 chip, 1 card; ưu tiên chip tuyệt đối làm pilot chưa có thêm card.
- Đổi sang xen kẽ card/chip, bắt đầu bằng card; bỏ qua cache trước khi tính lượt. Mặc định nghỉ 10–20 giây, log mỗi 5 trang.
- Kiểm tra offline từ cache: 10 lượt tiếp theo là 5 card + 5 chip chưa tải; hàng đợi chỉ có card vẫn chạy hết. 6 test hiện có đạt. Không truy cập mạng trong lần sửa này.
- Chưa xác nhận độ phủ năm 2000 hay khả năng crawl dài; lượt thử tiếp theo cần người dùng chạy sau khi kiểm tra truy cập bình thường.

## 14/11/2026 — Dashboard theo dõi
- Tạo scraper/dashboard.py và dashboard.html, máy chủ chỉ lắng nghe 127.0.0.1:8766; tự làm mới 15 giây, đọc cache/CSV/log, không gọi TechPowerUp.
- Đã kiểm tra HTTP trang và API: 96 card cache, 95 dòng CSV. Đã gửi yêu cầu mở ở khung phải; ứng dụng trả queued.
- Chưa khởi chạy crawler: công cụ trình duyệt không xác minh được URL, công cụ web từ chối restricted URL. Không coi quyền người dùng là cách vượt giới hạn công cụ.

## 15/11/2026 — Tái cấu trúc theo ý tưởng bộ Huy
- Thêm tpu_runner.py: batch, checkpoint, OS lock, heartbeat, parse mỗi đợt/cuối lượt, phân biệt thử/lưu/lỗi.
- Dashboard đọc status.json, cảnh báo mất heartbeat, không còn thông báo bị chặn viết cố định.
- Kiểm tra offline: 9 tests đạt gồm bị chặn rồi resume, trang lỗi rồi retry, giới hạn lượt và khóa chạy trùng. Chưa crawl mạng hoặc triển khai đọc DOM Chrome.
