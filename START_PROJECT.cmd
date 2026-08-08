@echo off
chcp 65001 >nul
title مکالمه‌بان - راه‌اندازی پروژه
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_project.ps1"
set EXIT_CODE=%ERRORLEVEL%
echo.
if not "%EXIT_CODE%"=="0" echo راه‌اندازی کامل نشد. پیام بالا را بررسی کنید.
pause
exit /b %EXIT_CODE%
