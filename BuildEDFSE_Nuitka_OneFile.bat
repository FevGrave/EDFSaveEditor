@echo off
SETLOCAL

REM Single-exe Nuitka build - the distribution-ready counterpart to BuildEDFSE_Nuitka.bat's
REM --standalone folder build. Kept as its own script rather than a flag toggle so the folder
REM build (easiest to debug missing data files in) stays available on its own.
REM
REM Same one-time prerequisites as BuildEDFSE_Nuitka.bat:
REM   %PYDIR%\python.exe -m pip install nuitka ordered-set zstandard
REM --mingw64 fetches/uses MinGW64 automatically so MSVC isn't required (one-time download, cached).
REM
REM THE CACHING PIECE: Nuitka's onefile mode is a self-extracting exe - by default it unpacks to
REM "%TEMP%\onefile_<PID>_<TIME>" and deletes that folder on exit, meaning a FRESH extraction (and
REM the matching startup delay) on every single launch, every time, forever - exactly the PyInstaller
REM onefile behavior this whole detour was meant to avoid. --onefile-tempdir-spec below points
REM extraction at a STABLE, version-qualified folder instead, so the 2nd and later launches can
REM reuse it.
REM
REM IMPORTANT: this uses Nuitka's OWN {CACHE_DIR}/{COMPANY}/{PRODUCT}/{VERSION} placeholders -
REM curly braces, confirmed from this exact installed Nuitka's (4.2.1) own warning output, NOT the
REM %PERCENT% style an older GitHub issue suggested (that failed here with an "illegal suffix"
REM error - wrong delimiter for this version, all 4 placeholders silently resolved to nothing).
REM These are resolved by the COMPILED EXE ITSELF, at RUNTIME, on whatever machine actually runs
REM it - critical since this tool gets distributed to other modders, each with their own username/
REM cache dir. Do NOT replace this with a literal baked-in path (e.g. via %LOCALAPPDATA%, which
REM cmd.exe would expand at BUILD time on this machine only) - that was tried as a stopgap while
REM diagnosing the delimiter issue and works fine locally, but bakes in this machine's own
REM C:\Users\<you>\... path, which doesn't exist on anyone else's PC.
REM
REM Trade-off worth knowing: including the version in the path means every version bump gets its
REM own cache folder rather than colliding with a locked-in-use previous version's extracted files
REM on Windows - but it also means old versions' cached folders are never auto-deleted. Not a
REM correctness problem (just some stray MBs per shipped version in each user's own cache dir), but
REM worth a "clears old EDFSaveEditor cache folders after updating" line in release notes someday.

set EXECUTABLE_NAME=EDFSaveEditor
set PYDIR=C:\Python312
REM Change this to your own name/handle/studio if you'd rather it not say FevGrave - it only
REM affects the cache path below, nothing user-visible in the app itself.
set COMPANY_NAME=FevGrave
REM Single source of truth for the version, used below for --file-version, --product-version,
REM AND the tempdir-spec path - so bumping a release only means changing it here once.
set VERSION_STR=1.1.0.0
REM Full, untruncated build output goes here every run (overwritten each time) - share this whole
REM file rather than copy-pasting console lines by hand when a build needs debugging help.
set LOGFILE=build_log_nuitka_onefile.txt

REM %PERCENT%-style placeholders failed on this Nuitka version (see above) - confirmed via this
REM exact install's own warning text that {CURLY_BRACE} is the right delimiter here instead.

if exist build_nuitka_onefile rmdir /S /Q build_nuitka_onefile
if exist dist_nuitka_onefile rmdir /S /Q dist_nuitka_onefile

REM Same pre-build sync step as the other two build scripts.
echo.
echo Syncing languages.json (ja/kr/cn/sc) with 'en'...
python sync_languages.py
if errorlevel 1 (
  echo.
  echo [WARN] sync_languages.py failed - continuing build with languages.json as-is.
)

REM Same optional-icon pattern as the other two build scripts.
set ICON_ARG=
set ICON_DATA_ARG=
if exist AppIcon.ico (
  set ICON_ARG=--windows-icon-from-ico=AppIcon.ico
  REM Embedding the icon into the exe (above) only sets the file/Explorer icon. The app also
  REM sets its own live window/taskbar icon at runtime via iconbitmap(resource_path('AppIcon.ico')),
  REM which needs a loose copy of AppIcon.ico bundled alongside the app - PyInstaller's .spec did
  REM this via datas=[('AppIcon.ico','.'), ...]; this line is Nuitka's equivalent.
  set ICON_DATA_ARG=--include-data-files=AppIcon.ico=AppIcon.ico
)

REM Onefile-only: shows a splash image in a small window while the exe self-extracts (first run,
REM or any run after the cache dir's contents are missing/invalidated - see the tempdir-spec note
REM above). Cached re-launches skip extraction entirely and this never shows. Not passed to the
REM standalone build - it's a --onefile-specific Nuitka flag.
REM
REM Nuitka's splash option only accepts a raw PNG (confirmed in Nuitka's own user manual - .ico is
REM not accepted, and testing also confirmed Pillow's ICO writer silently drops any frame above
REM 256x256, so a bigger splash frame can't be stashed inside the .ico either). Rather than hand-
REM maintain a second image asset, this pulls AppIcon.ico's own base frame (256x256, ORIGINAL
REM source - see PNG_TO_ICO_v2.py) out into a throwaway PNG right before the build and deletes it
REM afterward either way - AppIcon.ico stays the one art asset you actually maintain.
set SPLASH_TMP=_splash_from_ico.png
if exist %SPLASH_TMP% del /Q %SPLASH_TMP%
set SPLASH_ARG=
if exist AppIcon.ico (
  %PYDIR%\python.exe -c "from PIL import Image; Image.open('AppIcon.ico').convert('RGBA').save('%SPLASH_TMP%')" 2>nul
  if exist %SPLASH_TMP% (
    set SPLASH_ARG=--onefile-windows-splash-screen-image=%SPLASH_TMP%
  )
)

echo.
echo Building - output is being logged to %LOGFILE% (this will look quiet for a while - Nuitka compiles to C then to a binary, expect minutes not seconds)...
%PYDIR%\python.exe -m nuitka ^
  --onefile ^
  --onefile-tempdir-spec={CACHE_DIR}/{COMPANY}/{PRODUCT}/{VERSION} ^
  --windows-console-mode=disable ^
  --enable-plugin=tk-inter ^
  --mingw64 ^
  --output-dir=dist_nuitka_onefile ^
  --output-filename=%EXECUTABLE_NAME%.exe ^
  --file-version=%VERSION_STR% ^
  --product-version=%VERSION_STR% ^
  --company-name=%COMPANY_NAME% ^
  --product-name=%EXECUTABLE_NAME% ^
  %ICON_ARG% ^
  %ICON_DATA_ARG% ^
  %SPLASH_ARG% ^
  --include-package=cryptography ^
  --include-package-data=cryptography ^
  --include-package=customtkinter ^
  --include-module=timeit ^
  --include-package=tksheet ^
  --include-package-data=tksheet ^
  --include-data-files=EDFSaveEditorLogic.py=EDFSaveEditorLogic.py ^
  --include-data-files=EDFSaveEditorSave_Handler.py=EDFSaveEditorSave_Handler.py ^
  --include-data-files=TableParser.py=TableParser.py ^
  --include-data-files=EDFWeaponFarming.py=EDFWeaponFarming.py ^
  --include-data-files=MissionNames.json=MissionNames.json ^
  --include-data-files=WeaponNamesLang.json=WeaponNamesLang.json ^
  --include-data-files=languages.json=languages.json ^
  --include-data-dir=fonts=fonts ^
  EDFSaveEditorMain.py > "%LOGFILE%" 2>&1
set BUILD_ERR=%ERRORLEVEL%
if exist %SPLASH_TMP% del /Q %SPLASH_TMP%

echo.
echo Full build log saved to: %CD%\%LOGFILE%

if %BUILD_ERR% NEQ 0 (
  echo.
  echo ============ Build log ============
  type "%LOGFILE%"
  echo ====================================
  echo.
  echo Build FAILED - see log above (also saved to %LOGFILE%).
  pause
  exit /b 1
)

if not exist dist_nuitka_onefile\%EXECUTABLE_NAME%.exe (
  echo.
  echo Build reported success but dist_nuitka_onefile\%EXECUTABLE_NAME%.exe is missing.
  pause
  exit /b 1
)

echo.
echo Build complete! Output: dist_nuitka_onefile\%EXECUTABLE_NAME%.exe
echo (First launch extracts to each user's own cache dir under FevGrave\EDFSaveEditor\%VERSION_STR% -
echo  later launches should feel close to instant since that extraction gets reused.)
echo Full build log: %CD%\%LOGFILE%
pause
