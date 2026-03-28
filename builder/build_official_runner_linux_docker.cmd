@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "ETTERNA_ROOT=%SCRIPT_DIR%\etterna-master"
set "MINACALC_DIR=%ETTERNA_ROOT%\src\Etterna\MinaCalc"
set "ETTERNA_DIR=%ETTERNA_ROOT%\src\Etterna"

if not exist "%MINACALC_DIR%\MinaCalc.cpp" (
    echo [ERROR] MinaCalc source not found: "%MINACALC_DIR%\MinaCalc.cpp"
    exit /b 1
)

where docker >nul 2>nul
if errorlevel 1 (
    echo [ERROR] docker not found. Install Docker Desktop first.
    exit /b 1
)

docker version >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Docker daemon is not reachable.
    echo.
    echo Common fixes:
    echo   1. Start Docker Desktop and wait until it shows "Engine running".
    echo   2. Ensure Linux container engine is enabled.
    echo   3. If you see named-pipe errors, run PowerShell as Administrator and execute:
    echo      Start-Service com.docker.service
    echo   4. Verify with: docker version
    exit /b 2
)

set "PRIMARY_IMAGE=%ETT_LINUX_BUILD_IMAGE%"
if "%PRIMARY_IMAGE%"=="" set "PRIMARY_IMAGE=mcr.microsoft.com/devcontainers/cpp:1-debian-12"
set "FALLBACK_IMAGE=gcc:13"

call :TryBuild "%PRIMARY_IMAGE%"
if errorlevel 1 (
    echo [WARN] Failed with image: %PRIMARY_IMAGE%
    if /I not "%PRIMARY_IMAGE%"=="%FALLBACK_IMAGE%" (
        echo [INFO] Retrying with fallback image: %FALLBACK_IMAGE%
        call :TryBuild "%FALLBACK_IMAGE%"
    )
)

if errorlevel 1 (
    echo [ERROR] Linux runner build failed.
    echo [HINT] You can override image via: set ETT_LINUX_BUILD_IMAGE=your/image:tag
    exit /b 1
)

echo [OK] Built Linux runner: official_minacalc_runner
exit /b 0

:TryBuild
set "BUILD_IMAGE=%~1"
echo [INFO] Building with image: %BUILD_IMAGE%
docker run --rm -v "%SCRIPT_DIR%:/work" -w /work %BUILD_IMAGE% bash -lc "set -euo pipefail; g++ -std=c++20 -O2 -DSTANDALONE_CALC -I /work/etterna-master/src/Etterna/MinaCalc -I /work/etterna-master/src/Etterna /work/official_minacalc_runner.cpp /work/etterna-master/src/Etterna/MinaCalc/MinaCalc.cpp -o /work/official_minacalc_runner"
if errorlevel 1 exit /b 1
exit /b 0
