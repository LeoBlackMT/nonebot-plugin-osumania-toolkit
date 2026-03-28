@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "REFS_ROOT=%SCRIPT_DIR%etterna-master"
set "MINACALC_DIR=%REFS_ROOT%\src\Etterna\MinaCalc"
set "ETTERNA_DIR=%REFS_ROOT%\src\Etterna"

if not exist "%MINACALC_DIR%\MinaCalc.cpp" (
	echo [ERROR] MinaCalc source not found: "%MINACALC_DIR%\MinaCalc.cpp"
	exit /b 1
)

where cl >nul 2>nul
if errorlevel 1 (
	if exist "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" (
		call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
	) else (
		echo [ERROR] cl.exe not found. Open a VS Developer Command Prompt and retry.
		exit /b 1
	)
)

pushd "%SCRIPT_DIR%"
cl /std:c++20 /O2 /EHsc /D STANDALONE_CALC /I "%MINACALC_DIR%" /I "%ETTERNA_DIR%" official_minacalc_runner.cpp "%MINACALC_DIR%\MinaCalc.cpp" /Fe:official_minacalc_runner.exe
set "BUILD_RC=%ERRORLEVEL%"
popd

if not "%BUILD_RC%"=="0" (
	echo [ERROR] Build failed with exit code %BUILD_RC%.
	exit /b %BUILD_RC%
)

echo [OK] Built official_minacalc_runner.exe
exit /b 0
