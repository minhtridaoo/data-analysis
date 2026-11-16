@echo off
REM Mo cua so xem tien do thu thap Lazada, tu lam moi moi 30 giay. Dong cua so de thoat.
title Tien do thu thap Lazada
powershell -NoProfile -ExecutionPolicy Bypass -Command "$f = Join-Path '%~dp0' 'tien_do.txt'; while ($true) { Clear-Host; if (Test-Path $f) { Get-Content $f -Encoding UTF8 } else { 'Chua co file tien_do.txt' }; ''; 'Tu lam moi moi 30 giay - dong cua so de thoat'; Start-Sleep -Seconds 30 }"
