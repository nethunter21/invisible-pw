@echo off
cd /d "%~dp0"
python -m venv .venv
.venv\Scripts\python.exe -m pip install -q --upgrade pip
.venv\Scripts\python.exe -m pip install -q -r requirements.txt
echo installed. next: write your config, then: .venv\Scripts\python.exe -m lastchance seal my-config.json
pause
