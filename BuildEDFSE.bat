@echo off
SETLOCAL

set EXECUTABLE_NAME=EDFSaveEditor
set PYDIR=C:\Python312
set TKSHEET_DIR=%PYDIR%\Lib\site-packages\tksheet

rmdir /S /Q build
rmdir /S /Q dist
del /Q %EXECUTABLE_NAME%.spec

%PYDIR%\Scripts\pyinstaller.exe ^
  --onefile ^
  --windowed ^
  --name %EXECUTABLE_NAME% ^
  --version-file version_info.txt ^
  --collect-all cryptography ^
  --hidden-import customtkinter ^
  --hidden-import timeit ^
  --hidden-import cryptography.hazmat.bindings._openssl ^
  --add-data "%TKSHEET_DIR%;tksheet" ^
  --add-data "EDFSaveEditorLogic.py;." ^
  --add-data "EDFSaveEditorSave_Handler.py;." ^
  --add-data "TableParser.py;." ^
  --add-data "MissionNames.json;." ^
  --add-data "WeaponNamesLang.json;." ^
  --add-data "languages.json;." ^
  --add-binary "%PYDIR%\tcl\tcl8.6;lib\tcl8.6" ^
  --add-binary "%PYDIR%\tcl\tk8.6;lib\tk8.6" ^
  EDFSaveEditorMain.py

echo.
echo ✅ Build complete! Output: dist\%EXECUTABLE_NAME%.exe
pause