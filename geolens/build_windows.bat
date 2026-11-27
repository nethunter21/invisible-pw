@echo off
REM Build GeoLens.exe locally on Windows (Python 3.11 64-bit recommended).
cd /d %~dp0
python -m venv .venv || goto :err
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install torch --index-url https://download.pytorch.org/whl/cpu || goto :err
pip install -r requirements.txt pyinstaller || goto :err
pyinstaller GeoLens.spec --noconfirm || goto :err
echo.
echo Done: dist\GeoLens\GeoLens.exe
goto :eof
:err
echo Build failed.
exit /b 1
