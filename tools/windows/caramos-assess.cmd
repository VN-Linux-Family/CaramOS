@echo off
rem CaramOS: khao sat may Windows truoc khi chuyen sang CaramOS.
rem Chay caramos-assess.ps1 nam cung thu muc. Khong can quyen quan tri, khong ket noi mang.
if not exist "%~dp0caramos-assess.ps1" (
  echo Khong thay caramos-assess.ps1 ben canh tep nay.
  echo Hay giai nen ca thu muc roi chay lai.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0caramos-assess.ps1" %*
pause
