@echo off
setlocal
REM Launch the GUI and force attach to an already-running Chrome over CDP
pushd "%~dp0"

REM Keep logs and invited DB next to the scripts
set "VOICES_LOG_FILE=%~dp0invites_log.jsonl"
set "VOICES_INVITED_DB=%~dp0invited_ids.json"

REM Force CDP attach mode and disallow fallback
set "CHROME_CDP_URL=http://127.0.0.1:9222"
set "CONNECT_RUNNING_CHROME=1"
set "REQUIRE_CDP=1"

REM Best-effort: start Chrome with remote debugging if not already running
set "_CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%_CHROME%" set "_CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if exist "%_CHROME%" (
  start "Chrome CDP" "%_CHROME%" --remote-debugging-port=9222
)

python "%~dp0voices_gui.py"
set "EXITCODE=%ERRORLEVEL%"
popd
exit /b %EXITCODE%
