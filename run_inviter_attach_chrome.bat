@echo off
setlocal
REM One-click CLI run that attaches to a running Chrome over CDP (port 9222)
pushd "%~dp0"

REM Configure defaults (you can edit these lines)
set "CHROME_CDP_URL=http://127.0.0.1:9222"
set "VOICES_LOG_FILE=%~dp0invites_log.jsonl"
set "VOICES_INVITED_DB=%~dp0invited_ids.json"

REM Try to start Chrome with remote debugging if not already running (best-effort)
set "_CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%_CHROME%" set "_CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if exist "%_CHROME%" (
  start "Chrome CDP" "%_CHROME%" --remote-debugging-port=9222
)

REM Run the inviter script, requiring CDP attach
python "%~dp0invite_all.py" ^
  --require-cdp ^
  --manual-login ^
  --log-file "%VOICES_LOG_FILE%" ^
  --invited-db "%VOICES_INVITED_DB%"

set "EXITCODE=%ERRORLEVEL%"
popd
exit /b %EXITCODE%
