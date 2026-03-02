@echo off
setlocal

REM Execute from repository root
cd /d %~dp0\..\..

py -m pip install --upgrade pip
py -m pip install -r requirements.txt pyinstaller

py -m PyInstaller ^
  --noconfirm ^
  --onefile ^
  --noconsole ^
  --name WRMetaViewer ^
  --hidden-import app.main ^
  --add-data "app;app" ^
  --add-data "data;data" ^
  windows_launcher.py

echo.
echo Build concluido. Executavel em: dist\WRMetaViewer.exe
endlocal
