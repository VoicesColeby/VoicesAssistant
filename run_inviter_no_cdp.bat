@echo off
setlocal
REM One-click CLI run without attaching to Chrome (Playwright launches its own browser)
pushd "%~dp0"

REM Configure defaults (you can edit these lines)
set "VOICES_START_URL=https://www.voices.com/talents/search?keywords=&language_ids=1"
set "VOICES_LOG_FILE=%~dp0invites_log.jsonl"
set "VOICES_INVITED_DB=%~dp0invited_ids.json"

REM Run the inviter script
python "%~dp0invite_all.py" ^
  --no-cdp ^
  --manual-login ^
  --slow-mo 70 ^
  --scroll-passes 2 ^
  --log-file "%VOICES_LOG_FILE%" ^
  --invited-db "%VOICES_INVITED_DB%" ^
  --start-url "%VOICES_START_URL%"

set "EXITCODE=%ERRORLEVEL%"
popd
exit /b %EXITCODE%
