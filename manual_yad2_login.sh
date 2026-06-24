#!/bin/bash
echo "Starting Yad2 Manual CAPTCHA Solver on remote server..."
if [ -f "venv/bin/python" ]; then
    venv/bin/python scripts/manual_yad2_login.py
else
    python3 scripts/manual_yad2_login.py
fi
