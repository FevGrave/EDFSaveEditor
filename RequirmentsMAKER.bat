@echo off
setlocal

:: Prompt for project directory
set /p projectDir="Enter the project directory (default: current directory): "
if "%projectDir%"=="" set "projectDir=."

:: Check if Python is in PATH
where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    for /f "tokens=*" %%i in ('where python') do (
        set "PYTHON_PATH=%%i"
        echo Found Python at: %PYTHON_PATH%
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
        echo Found Python at: %PYTHON_PATH%
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
    set "url=https://www.python.org/ftp/python/%PYTHON_VERSION%/python-%PYTHON_VERSION%-amd64.exe"
    set "output=python-%PYTHON_VERSION%-amd64.exe"

    :: Prompt for installation directory
    set /p installDir="Enter the directory for Python installation (e.g., C:\Python312): "
    if not exist "%installDir%" (
        echo Creating directory "%installDir%"...
        mkdir "%installDir%"
        if %ERRORLEVEL% neq 0 (
            echo Failed to create directory.
            exit /b %ERRORLEVEL%
        )
    )

    :: Download Python installer
    where curl >nul 2>&1
    if %ERRORLEVEL% neq 0 (
        echo curl is not available. Please install curl.
        exit /b 1
    )
    echo Downloading Python %PYTHON_VERSION%...
    curl -o "%output%" "%url%"
    if %ERRORLEVEL% neq 0 (
        echo Failed to download installer.
        exit /b %ERRORLEVEL%
    )

    :: Install Python
    echo Installing Python %PYTHON_VERSION% to "%installDir%"...
    "%output%" /quiet InstallAllUsers=1 TargetDir="%installDir%" PrependPath=1
    if %ERRORLEVEL% neq 0 (
        echo Installation failed.
        exit /b %ERRORLEVEL%
    )
    set "PYTHON_PATH=%installDir%\python.exe"
)

:python_found

:: Ensure pip is installed and upgraded
%PYTHON_PATH% -m ensurepip
%PYTHON_PATH% -m pip install --upgrade pip

:: Check if requirements.txt exists, generate if not
if not exist "%projectDir%\requirements.txt" (
    echo requirements.txt not found in %projectDir%! Attempting to generate...
    if exist "%projectDir%\make_requirements.py" (
        echo Running make_requirements.py...
        pushd "%projectDir%"
        %PYTHON_PATH% make_requirements.py .
        popd
        if %ERRORLEVEL% neq 0 (
            echo Failed to generate requirements.txt.
            exit /b %ERRORLEVEL%
        )
    ) else (
        echo make_requirements.py not found in %projectDir%!
        exit /b 1
    )
)

:: Check if requirements.txt is empty
for %%F in ("%projectDir%\requirements.txt") do set "filesize=%%~zF"
if %filesize% leq 0 (
    echo requirements.txt is empty! Skipping package installation.
    exit /b 1
)

:: Install Python packages
echo Installing packages from requirements.txt...
%PYTHON_PATH% -m pip install -r "%projectDir%\requirements.txt"
if %ERRORLEVEL% neq 0 (
    echo Package installation failed.
    exit /b %ERRORLEVEL%
)

echo All prerequisites installed successfully.
pause
exit /b 0