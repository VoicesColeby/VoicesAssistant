@echo off
REM Close all Chrome windows first, then run this to start Chrome with DevTools port 9222
set "_CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%_CHROME%" set "_CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%_CHROME%" (
  echo Could not find chrome.exe in Program Files.
  exit /b 1
)
start "Chrome (CDP 9222)" "%_CHROME%" --remote-debugging-port=9222
