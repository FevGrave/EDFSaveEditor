@echo off
SETLOCAL

set EXECUTABLE_NAME=EDFSaveEditor
set PYDIR=C:\Python312
set TKSHEET_DIR=%PYDIR%\Lib\site-packages\tksheet
REM Full, untruncated build output goes here every run (overwritten each time) - share this whole
REM file rather than copy-pasting console lines by hand when a build needs debugging help, since
REM scrollback in a terminal window is easy to clip or lose lines from without noticing.
set LOGFILE=build_log_pyinstaller.txt

if exist build rmdir /S /Q build
if exist dist rmdir /S /Q dist
if exist %EXECUTABLE_NAME%.spec del /Q %EXECUTABLE_NAME%.spec

REM Keep languages.json's ja/kr/cn/sc blocks structurally in sync with 'en' before every
REM build - added because new UI strings (e.g. the Weapon Farming panel, the Key Config
REM action labels) kept landing in 'en' only, with nobody remembering to run
REM sync_languages.py by hand afterward, so packaged builds shipped with those panels
REM silently un-translated for 4 of 5 languages. This can't fail the build (missing
REM translations aren't fatal, tr() falls back to English) - it just guarantees every
REM build starts from a synced languages.json.
echo.
echo Syncing languages.json (ja/kr/cn/sc) with 'en'...
python sync_languages.py
if errorlevel 1 (
  echo.
  echo [WARN] sync_languages.py failed - continuing build with languages.json as-is.
)

REM App icon (2026-08-30, FevGrave): AppIcon.ico is optional and not committed yet - drop a
REM real one at the project root under this exact name whenever it's ready and the build will
REM pick it up automatically, both for the .exe's own icon (--icon) and for the window's own
REM title-bar/taskbar-while-running icon (EDFSaveEditorMain.py's runtime iconbitmap call reads
REM it back out via resource_path, so it needs to be bundled as data too, not just passed to
REM --icon). No file present -> both flags are simply omitted, build proceeds exactly as before
REM with PyInstaller's default icon (matches this project's own "degrade gracefully, don't
REM guess" pattern used everywhere else - e.g. load_json_safe).
set ICON_ARG=
set ICON_DATA_ARG=
if exist AppIcon.ico (
  set ICON_ARG=--icon "AppIcon.ico"
  set ICON_DATA_ARG=--add-data "AppIcon.ico;."
)

echo.
echo Building - output is being logged to %LOGFILE% (this will look quiet for a bit, that's expected)...
%PYDIR%\Scripts\pyinstaller.exe ^
  --onefile ^
  --windowed ^
  --name %EXECUTABLE_NAME% ^
  --version-file version_info.txt ^
  %ICON_ARG% ^
  %ICON_DATA_ARG% ^
  --collect-all cryptography ^
  --hidden-import customtkinter ^
  --hidden-import timeit ^
  --hidden-import cryptography.hazmat.bindings._openssl ^
  --add-data "%TKSHEET_DIR%;tksheet" ^
  --add-data "EDFSaveEditorLogic.py;." ^
  --add-data "EDFSaveEditorSave_Handler.py;." ^
  --add-data "TableParser.py;." ^
  --add-data "EDFWeaponFarming.py;." ^
  --add-data "MissionNames.json;." ^
  --add-data "WeaponNamesLang.json;." ^
  --add-data "languages.json;." ^
  --add-data "fonts;fonts" ^
  --add-binary "%PYDIR%\tcl\tcl8.6;lib\tcl8.6" ^
  --add-binary "%PYDIR%\tcl\tk8.6;lib\tk8.6" ^
  EDFSaveEditorMain.py > "%LOGFILE%" 2>&1
set BUILD_ERR=%ERRORLEVEL%

echo.
echo Full build log saved to: %CD%\%LOGFILE%

if %BUILD_ERR% NEQ 0 (
  echo.
  echo ============ Build log ============
  type "%LOGFILE%"
  echo ====================================
  echo.
  echo ❌ Build FAILED - see log above ^(also saved to %LOGFILE%^). dist\%EXECUTABLE_NAME%.exe was NOT updated.
  pause
  exit /b 1
)

if not exist dist\%EXECUTABLE_NAME%.exe (
  echo.
  echo ❌ Build reported success but dist\%EXECUTABLE_NAME%.exe is missing.
  pause
  exit /b 1
)

echo.
echo Build complete! Output: dist\%EXECUTABLE_NAME%.exe
echo Full build log: %CD%\%LOGFILE%
pause