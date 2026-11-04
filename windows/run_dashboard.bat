@echo off
setlocal EnableExtensions
title IQCC Chip Dashboard

rem ---------------------------------------------------------------------------
rem  One-click launcher for a fresh Windows 10/11 machine (no git, no Python,
rem  no admin rights needed). Keep "dashboard.env" next to this file.
rem
rem  On first run it copies itself + dashboard.env to %LOCALAPPDATA% and runs
rem  from there, so the USB stick can be removed afterwards. It then checks
rem  server health and GitHub every UPDATE_CHECK_SECONDS; restarts on a new
rem  version or if data goes stale.
rem  Closing this window stops the dashboard server.
rem ---------------------------------------------------------------------------

set "PORT=8080"
set "REPO=i-qcc/iqcc-chip-dashboard"
set "BRANCH=main"
set "REPO_ZIP_URL=https://github.com/%REPO%/archive/refs/heads/%BRANCH%.zip"
set "REPO_SHA_URL=https://api.github.com/repos/%REPO%/commits/%BRANCH%"
set "UV_ARCH=x86_64"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "UV_ARCH=aarch64"
set "UV_ZIP_URL=https://github.com/astral-sh/uv/releases/latest/download/uv-%UV_ARCH%-pc-windows-msvc.zip"

set "INSTALL_DIR=%LOCALAPPDATA%\iqcc-chip-dashboard"
set "APP_DIR=%INSTALL_DIR%\iqcc-chip-dashboard-main"
set "STAGING_DIR=%INSTALL_DIR%\staging"
set "SHA_FILE=%INSTALL_DIR%\installed_sha.txt"
set "KIOSK_PROFILE=%INSTALL_DIR%\edge-kiosk-profile"
set "UV=%INSTALL_DIR%\uv\uv.exe"

set "UV_CACHE_DIR=%INSTALL_DIR%\cache"
set "UV_PYTHON_INSTALL_DIR=%INSTALL_DIR%\python"
set "UV_PROJECT_ENVIRONMENT=%INSTALL_DIR%\venv"

if not exist "%~dp0dashboard.env" (
    echo ERROR: "%~dp0dashboard.env" not found.
    echo Copy dashboard.env.example to dashboard.env next to this file and fill in the tokens.
    goto :fail
)

if /i "%~dp0"=="%INSTALL_DIR%\" goto :installed
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
copy /y "%~dp0dashboard.env" "%INSTALL_DIR%\dashboard.env" >nul || goto :fail
copy /y "%~f0" "%INSTALL_DIR%\run_dashboard.bat" >nul || goto :fail
rem Chaining (no "call") hands control to the installed copy for good.
"%INSTALL_DIR%\run_dashboard.bat"

:installed
set "ENV_FILE=%INSTALL_DIR%\dashboard.env"
set "UPDATE_CHECK_SECONDS=600"
set "REFRESH_INTERVAL_SECONDS=600"
for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%ENV_FILE%") do (
    if /i "%%a"=="UPDATE_CHECK_SECONDS" set "UPDATE_CHECK_SECONDS=%%b"
    if /i "%%a"=="REFRESH_INTERVAL_SECONDS" set "REFRESH_INTERVAL_SECONDS=%%b"
)
rem Allow the data to be a few refresh cycles late (slow network, retry,
rem etc.) before we conclude the server is stuck and force-restart it.
set /a "STALE_SECONDS=REFRESH_INTERVAL_SECONDS*4"
if %STALE_SECONDS% LSS 900 set "STALE_SECONDS=900"
rem Health check and GitHub-update check both run on the same 10-min cycle.
set "HEALTH_CHECK_SECONDS=600"

cd /d "%INSTALL_DIR%" || goto :fail

if not exist "%UV%" (
    echo Downloading uv...
    curl -fL --retry 3 -o uv.zip "%UV_ZIP_URL%" || goto :fail
    if not exist uv mkdir uv
    tar -xf uv.zip -C uv || goto :fail
    del uv.zip
)
if not exist "%UV%" (
    echo ERROR: uv.exe not found after extraction.
    goto :fail
)

call :update_code || goto :fail
call :install_deps || goto :fail
call :start_keep_awake

:run
call :stop_kiosk
call :stop_server
call :start_server
call :open_kiosk
echo.
echo Dashboard running on http://127.0.0.1:%PORT%  (exit full screen with Alt+F4).
echo Checking health every %HEALTH_CHECK_SECONDS% s and for updates every %UPDATE_CHECK_SECONDS% s.
echo Close this window to stop.
set "SINCE_UPDATE_CHECK=0"

:watch
timeout /t %HEALTH_CHECK_SECONDS% /nobreak >nul

rem Health/staleness watchdog: if the server is unresponsive, or its cloud
rem data hasn't refreshed in a while (e.g. a stuck network call on the
rem server side - see app/main.py's per-backend fetch timeout for the
rem primary fix), restart the server. This is the safety net for anything
rem that fix doesn't catch, so an unattended kiosk laptop can't silently
rem show stale numbers for hours.
call :check_health
if errorlevel 1 (
    echo.
    echo [%date% %time%] Dashboard unresponsive or data stale ^(^>%STALE_SECONDS%s^), restarting...
    goto :run
)

set /a "SINCE_UPDATE_CHECK+=HEALTH_CHECK_SECONDS"
if %SINCE_UPDATE_CHECK% LSS %UPDATE_CHECK_SECONDS% goto :watch
set "SINCE_UPDATE_CHECK=0"

call :remote_sha
if not defined REMOTE_SHA goto :watch
set "LOCAL_SHA="
if exist "%SHA_FILE%" set /p LOCAL_SHA=<"%SHA_FILE%"
if /i "%REMOTE_SHA%"=="%LOCAL_SHA%" goto :watch
echo.
echo [%date% %time%] New dashboard version %REMOTE_SHA% found, updating...
call :stop_kiosk
call :stop_server
call :update_code
call :install_deps
goto :run


rem ---------------------------------------------------------------------------
rem Returns errorlevel 0 if /healthz responds AND (no data yet, i.e. still on
rem its first fetch after a fresh start, OR /api/data's last_refresh is newer
rem than STALE_SECONDS). Returns errorlevel 1 (triggers a restart) otherwise,
rem i.e. the server is unresponsive or data has gone genuinely stale.
:check_health
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 'http://127.0.0.1:%PORT%/healthz' | Out-Null; $r = Invoke-RestMethod -UseBasicParsing -TimeoutSec 5 'http://127.0.0.1:%PORT%/api/data'; if (-not $r.last_refresh) { exit 0 }; $age = ((Get-Date).ToUniversalTime() - [DateTime]::Parse($r.last_refresh).ToUniversalTime()).TotalSeconds; if ($age -gt %STALE_SECONDS%) { exit 1 } else { exit 0 } } catch { exit 1 }"
exit /b %errorlevel%


rem ---------------------------------------------------------------------------
:remote_sha
set "REMOTE_SHA="
for /f "usebackq delims=" %%s in (`curl -fsSL -H "Accept: application/vnd.github.sha" "%REPO_SHA_URL%" 2^>nul`) do set "REMOTE_SHA=%%s"
exit /b 0

:update_code
call :remote_sha
echo Downloading latest dashboard code...
if exist "%STAGING_DIR%" rmdir /s /q "%STAGING_DIR%"
mkdir "%STAGING_DIR%"
curl -fsSL --retry 3 -o "%INSTALL_DIR%\repo.zip" "%REPO_ZIP_URL%" || goto :update_code_offline
tar -xf "%INSTALL_DIR%\repo.zip" -C "%STAGING_DIR%" || goto :update_code_offline
if exist "%APP_DIR%" rmdir /s /q "%APP_DIR%"
move "%STAGING_DIR%\iqcc-chip-dashboard-%BRANCH%" "%APP_DIR%" >nul || exit /b 1
del "%INSTALL_DIR%\repo.zip"
rmdir /s /q "%STAGING_DIR%"
set "NEW_SHA=%REMOTE_SHA%"
exit /b 0

:update_code_offline
set "NEW_SHA="
if exist "%APP_DIR%\pyproject.toml" (
    echo WARNING: download failed, using the previously downloaded copy.
    exit /b 0
)
exit /b 1

:install_deps
copy /y "%ENV_FILE%" "%APP_DIR%\.env" >nul || exit /b 1
cd /d "%APP_DIR%" || exit /b 1
echo Installing Python and dependencies (first run takes a few minutes)...
"%UV%" sync --frozen --no-dev
if errorlevel 1 "%UV%" sync --no-dev || exit /b 1
if defined NEW_SHA (echo %NEW_SHA%)>"%SHA_FILE%"
exit /b 0

:start_keep_awake
rem Run a copy outside APP_DIR so updates can replace APP_DIR while it runs.
copy /y "%APP_DIR%\windows\keep_awake.ps1" "%INSTALL_DIR%\keep_awake.ps1" >nul || exit /b 0
cd /d "%INSTALL_DIR%"
start "" /b powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%INSTALL_DIR%\keep_awake.ps1"
echo Keep-awake started (prevents sleep, screen-off and auto-lock).
exit /b 0

:start_server
cd /d "%APP_DIR%"
echo Starting dashboard server...
start "" /b "%UV%" run --no-sync uvicorn app.main:app --host 127.0.0.1 --port %PORT%
exit /b 0

:stop_server
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
timeout /t 2 /nobreak >nul
exit /b 0

:open_kiosk
powershell -NoProfile -Command "for ($i = 0; $i -lt 180; $i++) { try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 'http://127.0.0.1:%PORT%/healthz' | Out-Null; break } catch { Start-Sleep -Seconds 1 } }"
start "" msedge --kiosk "http://127.0.0.1:%PORT%" --edge-kiosk-type=fullscreen --no-first-run --user-data-dir="%KIOSK_PROFILE%"
exit /b 0

:stop_kiosk
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'msedge.exe' -and $_.CommandLine -like '*edge-kiosk-profile*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
exit /b 0

:fail
echo.
echo Dashboard launcher failed. See the messages above.
pause
exit /b 1
