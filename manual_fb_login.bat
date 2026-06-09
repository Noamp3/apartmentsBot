@echo off
echo Starting Facebook Manual Login...
if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe scripts\manual_fb_login.py
) else (
    python scripts\manual_fb_login.py
)
pause
