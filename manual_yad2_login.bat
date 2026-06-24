@echo off
echo Starting Yad2 Manual CAPTCHA Solver...
if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe scripts\manual_yad2_login.py
) else (
    python scripts\manual_yad2_login.py
)
pause
