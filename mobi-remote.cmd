@echo off
rem mobi-remote (Mobi Connector Remote) - command line entry point
setlocal
rem NOTE: keep this file ASCII-only. cmd.exe parses .cmd in the OEM code page
rem (CP949 here), so UTF-8 comments get mangled into bogus commands.
rem Switch the console to UTF-8 so Korean output renders correctly.
chcp 65001 >nul 2>&1
node "%~dp0src\index.js" %*
endlocal & exit /b %errorlevel%
