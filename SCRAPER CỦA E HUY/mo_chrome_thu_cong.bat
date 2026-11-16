@echo off
REM Mo Chrome BINH THUONG (khong tu dong hoa) voi dung profile cua script, de tu dang nhap Lazada
REM va luot vai trang bang tay. DONG cua so Chrome nay truoc khi chay lazada_scraper.py (profile bi khoa khi dang mo).
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --user-data-dir="%~dp0chrome_profile" https://www.lazada.vn/
