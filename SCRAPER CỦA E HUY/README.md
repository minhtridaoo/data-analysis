# Thu thập dữ liệu "tai nghe bluetooth" trên Lazada Việt Nam

Đồ án môn **DS111 - Phân tích dữ liệu**. Dữ liệu tự thu thập, chỉ phục vụ học tập, số lượng nhỏ, chạy chậm.

| Mục | Giá trị |
|---|---|
| Nguồn | https://www.lazada.vn (Lazada Việt Nam) |
| Từ khóa tìm kiếm | `tai nghe bluetooth` |
| Thời gian thu thập | 13/11/2026 10:55 - 14/11/2026 ~00:42 (giờ Việt Nam) |
| File kết quả chính | `data/raw/lazada_tai_nghe.csv` (UTF-8 có BOM) |
| Từ điển dữ liệu | `data/raw/data_dictionary_lazada.csv` |
| Kết quả | **444 dòng x 72 cột**, 441/444 dòng có chi tiết, 0 captcha ở bước đọc giao diện (xem mục 6) |

## 1. Các file trong thư mục `scraper/`

| File | Vai trò |
|---|---|
| `lazada_scraper.py` | Script Python chính (Playwright + Google Chrome, profile riêng `chrome_profile/`). Chế độ `--listing-only` lấy danh sách từ trang tìm kiếm; chế độ mặc định / `--fill-details` lấy chi tiết qua trình duyệt tự động. Có resume theo `item_id`. |
| `lazada_scraper_v1_requests.py` | Phiên bản đầu: listing bằng `requests` (endpoint JSON `catalog/?ajax=true`) + chi tiết bằng Playwright. Dùng cho lần chạy mẫu 50 sản phẩm (đã bị captcha). Giữ làm minh chứng. |
| `lazada_detail_dom.js` | Script JavaScript chạy trong **Chrome thật của người dùng** (nạp qua Claude in Chrome): mở lần lượt từng trang sản phẩm, **đọc phần chữ hiển thị** (shop, đánh giá, thông số...), nghỉ 8-20 s, cứ 40 sản phẩm xuất 1 file JSON. |
| `merge_dom_details.py` | Đọc file JSON của từng đợt, chuẩn hóa (%, "29.9K" -> 29900, số năm shop...) và gộp vào CSV chính. |
| `watch_downloads.sh` | Theo dõi thư mục Downloads: có file `lazada_chitiet_*.json` mới thì chuyển vào `data/raw/details_dom/` và gọi `merge_dom_details.py`. |
| `mo_chrome_thu_cong.bat` | Mở Chrome thường (không tự động) với profile của script, để người dùng tự đăng nhập/lướt trang. |
| `hoan_thien_du_lieu.py` | Bước cuối: tính lại `battery_hours` từ `specs_raw` (bỏ nhầm mAh), thêm cột số chuẩn hóa (`battery_hours_num`, `bluetooth_version_num`, `impedance_ohm`, `warranty_months`), tạo lại từ điển dữ liệu. |
| `cap_nhat_tien_do.py`, `tien_do.txt`, `xem_tien_do.bat` | Ghi / xem tiến độ thu thập (tự làm mới). |
| `logs/` | Nhật ký các lần chạy Python (minh chứng). |

## 2. Quy trình thu thập (theo thứ tự đã thực hiện)

1. **Khảo sát** (10:55): endpoint `https://www.lazada.vn/catalog/?q=tai+nghe+bluetooth&ajax=true&page=N` trả JSON 40 sản phẩm/trang (`mods.listItems`). Trang chi tiết tải bằng `requests` **không có** thông tin shop/đánh giá/thông số vì các trường này được nạp sau qua API nội bộ có chữ ký chống bot.
2. **Chạy mẫu 50 sản phẩm** (`lazada_scraper_v1_requests.py`, 10:59-11:10, log `logs/01_...`): listing bằng `requests`, chi tiết bằng Playwright + Chrome (đọc response API mà trang tự gọi). Nghỉ 3-8 s. Được 49 dòng đầy đủ, sau đó Lazada hiện **captcha thanh trượt** -> dừng ngay. File: `data/raw/lazada_tai_nghe_sample.csv`.
3. **Sửa script** (`lazada_scraper.py`): bỏ `requests`, dùng Chrome thật với profile riêng; nghỉ 8-20 s; mỗi đợt tối đa 40 sản phẩm; gặp captcha thì chờ người dùng tự giải 5 phút, không được thì dừng đợt; thêm `--listing-only`, `--fill-details`.
4. **Listing 444 sản phẩm** (11:15-11:20, log `logs/02_...`): `python lazada_scraper.py --listing-only --pages 12 --max-items 450`. Mở 12 trang tìm kiếm trong trình duyệt, nghỉ 5-12 s/trang, **không gặp captcha**. Trang 2 trả trùng phần lớn sản phẩm trang 1 nên chỉ thêm 4 sản phẩm mới (script tự bỏ trùng). Chi tiết của 49 sản phẩm mẫu được chép sang.
5. **Chi tiết bằng trình duyệt tự động** (11:24, log `logs/03_...`): captcha xuất hiện ngay sản phẩm đầu tiên và người dùng không giải được (trình duyệt tự động bị nhận diện) -> dừng hẳn, không thử lại liên tục.
6. **Chi tiết đọc từ giao diện trong Chrome thật** (`lazada_detail_dom.js`, từ 11:30): mỗi sản phẩm mở trong iframe cùng domain, chờ trang hiển thị, đọc các khối chữ, nghỉ ngẫu nhiên **8-20 giây**; cứ **40 sản phẩm** tải về 1 file `lazada_chitiet_bN.json` rồi nghỉ **2-4 phút**. Không gọi API nội bộ, không vượt captcha (gặp captcha -> script tự dừng và lưu file trạng thái). Tiến độ lưu trong `localStorage` nên bị ngắt vẫn chạy tiếp được (đã xảy ra 1 lần lúc khoảng 12:05, khôi phục 45 kết quả).
7. **Gộp**: `watch_downloads.sh` + `merge_dom_details.py` gộp từng file vào CSV. Các file JSON thô giữ nguyên trong `data/raw/details_dom/` làm minh chứng.
8. **Tạm dừng theo yêu cầu** lúc 15:42 (248/444 dòng có chi tiết), lưu hàng chờ vào `hang_cho_con_lai.json`. **Chạy tiếp** lúc 22:35 trong tab mới, khôi phục 180 kết quả từ `localStorage`; từ đợt 8 nới thời gian chờ mỗi trang lên 45 s và chấp nhận sản phẩm không có bảng thông số. Đợt 7-11 lấy hết hàng chờ, đợt 12 thử lại 29 dòng timeout (28 thành công).
9. **Hoàn thiện** (`hoan_thien_du_lieu.py`): tính lại `battery_hours`, thêm cột số chuẩn hóa, cập nhật `data_dictionary_lazada.csv`.

## 3. Trạng thái chi tiết của từng dòng (`detail_status`)

| Giá trị | Ý nghĩa |
|---|---|
| `ok`, `ok_redirected` | Chi tiết lấy từ API mà trang tự gọi (lần chạy mẫu) - có thêm phân bố số sao 1-5 (`star_1..star_5`). |
| `ok_dom` | Chi tiết đọc từ giao diện trang (bước 6). Giao diện web hiện **không hiển thị phân bố số sao**, nhưng có thêm `shop_age_years`, `reviews_with_media`, `review_tag_repurchase`. |
| `ok_dom_partial` | Trang chưa hiện đủ trong thời gian chờ (30-45 s), giữ phần đọc được. |
| `app_only` | Sản phẩm "LazSelects" - Lazada chỉ cho xem trên ứng dụng di động. Giữ dữ liệu listing. |
| `timeout`, `no_detail_api` | Không lấy được chi tiết. Giữ dữ liệu listing. |
| `listing_only` | Chưa lấy chi tiết. |

## 4. Xử lý captcha và giới hạn

- Không tự giải hay né captcha. Gặp captcha: chờ người dùng tự giải (Python) hoặc dừng hẳn (JS).
- Không dùng thư viện "stealth", không giả chữ ký API nội bộ.
- Tốc độ chậm có chủ ý: 8-20 s/sản phẩm, 5-12 s/trang tìm kiếm, nghỉ 2-4 phút mỗi 40 sản phẩm.
- Trường **không lấy được**: `chat_response_rate` (Lazada không còn hiển thị; thay bằng `response_time_raw`). Phân bố số sao chỉ có ở các dòng `ok`.

## 5. Cách chạy lại

```bash
cd scraper
pip install requests pandas playwright
# Bước 1: danh sách (trình duyệt Chrome có giao diện, profile riêng)
python lazada_scraper.py --listing-only --pages 12 --max-items 450 --out ../data/raw/lazada_tai_nghe.csv
# Bước 2 (cách A, có thể bị captcha): chi tiết qua trình duyệt tự động, 40 dòng/đợt
python lazada_scraper.py --fill-details --out ../data/raw/lazada_tai_nghe.csv
# Bước 2 (cách B, đã dùng): mở 1 trang sản phẩm lazada.vn trong Chrome, dán lazada_detail_dom.js
#   vào console rồi gọi __lzMaster([...danh sách item_id...]); sau đó gộp từng file:
python merge_dom_details.py ../data/raw/details_dom/lazada_chitiet_b1.json
```

Lưu ý: bundled Chromium của Playwright không chạy được trên máy thực hiện ("spawn UNKNOWN"), nên script dùng `channel="chrome"` (Google Chrome đã cài).

## 6. Kết quả cuối (14/11/2026)

| Hạng mục | Số dòng |
|---|---|
| Tổng sản phẩm (listing) | **444** (0 `item_id` trùng), 72 cột |
| Có chi tiết | **441** = 48 từ API (`ok`, có phân bố sao 1-5) + 393 đọc giao diện (`ok_dom`) |
| Chỉ xem trên app (`app_only`) | 2 |
| Không lấy được chi tiết (`timeout`) | 1 |
| Captcha ở bước đọc giao diện | 0 |
| File JSON thô (minh chứng) | 16 file dữ liệu + 3 file trạng thái + `hang_cho_con_lai.json` trong `data/raw/details_dom/` |

Tỉ lệ có giá trị (%) của các cột chính trên 444 dòng:

| Cột | % | Cột | % |
|---|---|---|---|
| price | 100 | positive_seller_rating | 98.9 |
| original_price / discount_pct | 95.3 | ship_on_time_rate | 80.4 |
| rating_score | 94.1 | store_sold_num | 85.8 |
| review_count | 94.4 | shop_age_years | 60.6 |
| sold_num | 91.2 | response_time_raw | 51.4 |
| location | 99.5 | rating_count_detail | 99.3 |
| is_lazmall / is_freeship | 100 | reviews_with_media | 88.5 |
| product_type | 99.3 | n_variants | 99.3 |
| bluetooth_version_num | 85.4 | is_authentic_guarantee | 99.3 |
| impedance_ohm | 67.6 | shipping_fee | 87.4 |
| waterproof | 56.1 | warranty_months | 53.4 |
| battery_hours_num | 38.7 | star_1..star_5 | 10.8 |

Ghi chú: `chat_response_rate` trống 100% (Lazada không hiển thị). Thông số kỹ thuật (pin, chống nước, bảo hành) phụ thuộc shop có khai báo hay không. `battery_hours_num` có giá trị đến 300 giờ (có thể là tổng kèm hộp sạc) - cần xem xét ngoại lai khi phân tích.

Sự cố trong lúc chạy (đã xử lý, không mất dữ liệu):
- ~12:05: phiên điều khiển khởi động lại, mất tab -> khôi phục 45 kết quả từ `localStorage` (`lazada_chitiet_recovered1.json`).
- ~14:15: tab chạy nền khiến Chrome bóp timer (~1 lần/phút) -> chuyển sang hẹn giờ bằng Web Worker. File `lazada_chitiet_STATUS_restart_1415_khong_phai_captcha.json` là file trạng thái của lần khởi động lại này, **không phải captcha**.
- ~14:30-15:25: Chrome chặn tải nhiều file -> người dùng cho phép, các file `b3`, `b4`, `b3b4_resend` được tải lại và gộp.

## 7. Cách chạy tiếp / chạy lại phần còn thiếu

Hàng chờ còn lại được lưu ở `data/raw/details_dom/hang_cho_con_lai.json` (`cho_lay`: 170 item_id chưa lấy, `thu_lai`: 25 item_id timeout/lỗi). Kết quả đã lấy cũng còn trong `localStorage` của Chrome (khóa `lzRes2`), nên script tự bỏ qua sản phẩm đã có.

**Cách 1 (nhờ Claude):** nhắn "tiếp tục cào" - Claude mở 1 trang sản phẩm lazada.vn trong Chrome (Claude in Chrome), nạp `lazada_detail_dom.js`, chạy `__lzMaster([...cho_lay])`, sau đó `__lzMaster([...thu_lai])`, và bật lại `watch_downloads.sh` để gộp.

**Cách 2 (tự làm):**
1. Mở Chrome, vào một trang sản phẩm bất kỳ, ví dụ `https://www.lazada.vn/products/pdp-i1891088502.html`.
2. Mở DevTools (F12) -> Console, dán toàn bộ nội dung `lazada_detail_dom.js`, Enter.
3. Dán danh sách `cho_lay` từ `hang_cho_con_lai.json`: `__lzMaster([ "2376425010", ... ])`.
4. Để tab mở; mỗi 40 sản phẩm Chrome tải 1 file `lazada_chitiet_bN.json` vào Downloads.
5. Gộp: `bash watch_downloads.sh` (tự động) hoặc `python merge_dom_details.py <file.json>` cho từng file.
6. Dừng giữa chừng: gõ `__lzState.stop = true` trong Console.

Theo dõi tiến độ: khung đen góc phải tab Lazada, tiêu đề tab, file `scraper/tien_do.txt`, hoặc bấm đúp `scraper/xem_tien_do.bat`.
