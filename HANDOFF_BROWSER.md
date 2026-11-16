# Tiếp tục thu thập GPU

Người dùng đã cho phép trực tiếp vận hành crawler, giữ máy chạy, và yêu cầu dashboard bên phải cùng thông báo khi hoàn tất. Không yêu cầu xác nhận lại việc crawl thông thường.

## Trạng thái xác nhận gần nhất
- Workspace: D:\MINHTRIHOCCODE\HOCKI5\DS111\Đồ án.
- 96 HTML card, 145 HTML chip; CSV có 95 dòng × 53 cột. Kiểm tra lại trước khi dùng số liệu.
- Dữ liệu giữ lại từ 2012 đến 2026, chưa có 2000–2011 và 2015. Không được tuyên bố đã đủ database.
- Một card ghi năm 2027 bị loại. Đây là thông tin trong nguồn, không xác minh phát hành sản phẩm.
- Crawler xen kẽ card/chip, tiếp tục từ cache. Parser đã sửa FP16/32/64, không lấy nhầm Matrix Performance.
- Lần crawl gần nhất bị CAPTCHA tại radeon-rx-7600-xt.c4190 lúc 10:10:43 ngày 14/11/2026. Không có crawler do trợ lý khởi chạy sau đó.
- Dashboard đọc dữ liệu trên máy: http://127.0.0.1:8766/; nguồn scraper/dashboard.py và dashboard.html. Trạng thái phiên trợ lý trong snapshot hiện là chuỗi cố định báo bị chặn công cụ; cần cập nhật thành trạng thái thực nếu bắt đầu vận hành, tránh hiển thị sai.

## Vướng mắc phiên cũ
Chrome có extension ChatGPT trong Profile 1. Người dùng đã gửi tab mention hợp lệ. Cả sau tab mention, công cụ vẫn trả `Local browser access is unavailable for this chat`. Web tool cũng từng trả restricted URL. Không tìm cách vượt hạn chế này qua công cụ khác. Hãy dùng kết nối trình duyệt được hỗ trợ trong phiên mới nếu có; không mặc định lỗi là do người dùng cài sai.

## Bước tiếp theo
1. Dùng tab Chrome mà người dùng chia sẻ để kiểm tra trang. Nếu công cụ không khả dụng, nêu rõ; nếu CAPTCHA, dừng, không tự giải hoặc vượt chặn.
2. Khi có truy cập hợp lệ và trang bình thường, kiểm tra không có crawler khác, rồi chạy crawler một luồng với delay 30–60 giây, giám sát log và dừng khi chặn. Giữ cache. Không chạy nhiều crawler cùng lúc.
3. Cập nhật dashboard với trạng thái tiến trình thật; parse sau khi dừng/kết thúc. Kiểm tra phân bố năm, trường thiếu, trang tải lỗi.
4. Không xem hàng đợi rỗng là bằng chứng đủ mọi GPU; ghi rõ giới hạn độ phủ và trang tải thất bại.
