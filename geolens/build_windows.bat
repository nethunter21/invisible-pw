@echo off
setlocal
REM Build GeoLens on Windows (64-bit Python 3.10 - 3.12).
REM Result: GeoLens-app\GeoLens.exe  (keep the whole folder together!)
cd /d %~dp0
where python >nul 2>nul || (echo Python not found. Install 64-bit Python 3.11 or 3.12 from python.org & exit /b 1)
python -c "import struct,sys; assert struct.calcsize('P')==8, '64-bit Python required'; assert (3,10)<=sys.version_info[:2]<=(3,12), 'Use Python 3.10-3.12'" || exit /b 1
if not exist .venv python -m venv .venv || goto :err
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install torch --index-url https://download.pytorch.org/whl/cpu || goto :err
pip install -r requirements.txt pyinstaller || goto :err

REM Intermediate files go to %TEMP% so no half-built GeoLens.exe is left lying around in .\build
set WORK=%TEMP%\geolens_pyi_work
if exist build rmdir /s /q build
if exist GeoLens-app rmdir /s /q GeoLens-app
pyinstaller GeoLens.spec --noconfirm --workpath "%WORK%" --distpath "%TEMP%\geolens_pyi_dist" || goto :err
move "%TEMP%\geolens_pyi_dist\GeoLens" GeoLens-app >nul || goto :err
rmdir /s /q "%WORK%" 2>nul

REM Desktop shortcut pointing at the real exe (never copy GeoLens.exe on its own)
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\GeoLens.lnk');$s.TargetPath='%CD%\GeoLens-app\GeoLens.exe';$s.WorkingDirectory='%CD%\GeoLens-app';$s.Save()"
echo.
echo ============================================================
echo  Built: %CD%\GeoLens-app\GeoLens.exe
echo  A "GeoLens" shortcut was added to your desktop.
echo  Do NOT move GeoLens.exe out of GeoLens-app - it needs the
echo  _internal folder next to it.
echo ============================================================
start "" "%CD%\GeoLens-app"
goto :eof
:err
echo Build failed.
exit /b 1
