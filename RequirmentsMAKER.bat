@echo off
:: BUG FIX: plain "setlocal" left every %VAR% reference inside a multi-line ( ... ) block
:: frozen to whatever value it held when cmd.exe first PARSED that block - not when each line
:: actually ran. That silently broke several things below: %PYTHON_VERSION%/%url%/%output%/
:: %installDir% were all set AND read inside the same "else ( ... )" install block, so the
:: download URL and installer path were built from empty/stale values; and every
:: "if %ERRORLEVEL% neq 0" check nested inside that same block (mkdir, curl-missing,
:: download, install) was testing a stale ERRORLEVEL captured at block-entry, not the actual
:: result of the command right above it. EnableDelayedExpansion + !VAR! (used everywhere a
:: variable is set and re-read within the same block below) fixes all of that.
setlocal EnableDelayedExpansion

:: Prompt for project directory
set /p projectDir="Enter the project directory (default: current directory): "
if "%projectDir%"=="" set "projectDir=."

:: Check if Python is in PATH
where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    for /f "tokens=*" %%i in ('where python') do (
        set "PYTHON_PATH=%%i"
        echo Found Python at: !PYTHON_PATH!
        goto :python_found
    )
)

:: Fallback to common installation paths
for %%P in (
    "%ProgramFiles%\Python*"
    "%ProgramFiles(x86)%\Python*"
    "%LocalAppData%\Programs\Python\Python*"
    "C:\Python*"
) do (
    if exist "%%P\python.exe" (
        set "PYTHON_PATH=%%P\python.exe"
        echo Found Python at: !PYTHON_PATH!
        goto :python_found
    )
)

:: If Python not found, prompt for installation
echo Python not found in expected locations.
set /p userInput="Is Python installed somewhere else? (Y/N): "
if /I "%userInput%"=="Y" (
    echo Please ensure Python is accessible from the command line.
) else (
    echo Proceeding with Python installation...

    :: Set Python version
    set "PYTHON_VERSION=3.12.4"
    set "url=https://www.python.org/ftp/python/!PYTHON_VERSION!/python-!PYTHON_VERSION!-amd64.exe"
    set "output=python-!PYTHON_VERSION!-amd64.exe"

    :: Prompt for installation directory
    set /p installDir="Enter the directory for Python installation (e.g., C:\Python312): "
    if not exist "!installDir!" (
        echo Creating directory "!installDir!"...
        mkdir "!installDir!"
        if !ERRORLEVEL! neq 0 (
            echo Failed to create directory.
            exit /b !ERRORLEVEL!
        )
    )

    :: Download Python installer
    where curl >nul 2>&1
    if !ERRORLEVEL! neq 0 (
        echo curl is not available. Please install curl.
        exit /b 1
    )
    echo Downloading Python !PYTHON_VERSION!...
    curl -o "!output!" "!url!"
    if !ERRORLEVEL! neq 0 (
        echo Failed to download installer.
        exit /b !ERRORLEVEL!
    )

    :: Install Python
    echo Installing Python !PYTHON_VERSION! to "!installDir!"...
    "!output!" /quiet InstallAllUsers=1 TargetDir="!installDir!" PrependPath=1
    if !ERRORLEVEL! neq 0 (
        echo Installation failed.
        del /q "!output!" >nul 2>&1
        exit /b !ERRORLEVEL!
    )
    :: BUG FIX: leftover multi-hundred-MB installer was never cleaned up on success either.
    del /q "!output!" >nul 2>&1
    set "PYTHON_PATH=!installDir!\python.exe"
)

:python_found

:: Ensure pip is installed and upgraded
:: BUG FIX: every "%PYTHON_PATH%" invocation below is now quoted - PYTHON_PATH commonly
:: resolves to a path with a space in it (e.g. "C:\Program Files\Python312\python.exe", which
:: the fallback loop above explicitly searches for), and an unquoted %PYTHON_PATH% at the
:: start of a command line gets tokenized at the first space - cmd would try to run the
:: literal file "C:\Program" and fail, even though the path itself is completely valid.
"%PYTHON_PATH%" -m ensurepip
if %ERRORLEVEL% neq 0 (
    echo Warning: ensurepip reported an error - continuing, since pip may already be present.
)
"%PYTHON_PATH%" -m pip install --upgrade pip
if %ERRORLEVEL% neq 0 (
    echo Warning: pip self-upgrade failed - continuing with whatever pip version is already installed.
)

:: Check if requirements.txt exists, generate if not
if not exist "%projectDir%\requirements.txt" (
    echo requirements.txt not found in %projectDir%^! Attempting to generate...
    :: BUG FIX: this looked for "make_requirements.py", but the actual generator script in
    :: this project is RequirmentsMAKER.py - the filename never matched, so this branch
    :: always fell through to "not found" and aborted, every single time.
    if exist "%projectDir%\RequirmentsMAKER.py" (
        echo Running RequirmentsMAKER.py...
        pushd "%projectDir%"
        "%PYTHON_PATH%" RequirmentsMAKER.py .
        set "GEN_ERRORLEVEL=!ERRORLEVEL!"
        popd
        :: BUG FIX: "popd" itself succeeds and resets ERRORLEVEL to 0, so checking
        :: %ERRORLEVEL% AFTER popd (as this used to) was actually checking popd's exit code,
        :: not RequirmentsMAKER.py's - a generation failure would go completely unnoticed.
        :: Captured into GEN_ERRORLEVEL (with delayed expansion, so it's read at the right
        :: moment) right after the python command runs, before popd gets a chance to stomp it.
        if not !GEN_ERRORLEVEL! equ 0 (
            echo Failed to generate requirements.txt.
            exit /b !GEN_ERRORLEVEL!
        )
    ) else (
        echo RequirmentsMAKER.py not found in %projectDir%^!
        exit /b 1
    )
)

:: Check if requirements.txt is empty
for %%F in ("%projectDir%\requirements.txt") do set "filesize=%%~zF"
if %filesize% leq 0 (
    echo requirements.txt is empty^! Skipping package installation.
    exit /b 1
)

:: Install Python packages
echo Installing packages from requirements.txt...
"%PYTHON_PATH%" -m pip install -r "%projectDir%\requirements.txt"
if %ERRORLEVEL% neq 0 (
    echo Package installation failed.
    exit /b %ERRORLEVEL%
)

echo All prerequisites installed successfully.
pause
exit /b 0
