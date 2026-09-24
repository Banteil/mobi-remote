@echo off
rem NOTE: keep this file ASCII-only (cmd.exe parses .cmd in the OEM code page).
rem mobi-remote (Mobi Connector Remote) - launches the Electron GUI.
rem
rem Two things this file works around:
rem
rem 1. %~dp0 ends with a backslash. Writing it as a quoted argument produces
rem    "C:\path\" and cmd.exe reads \" as an escaped quote, merging it with the
rem    next argument. So: cd first, then pass "." as the app directory.
rem
rem 2. start cannot launch node_modules\.bin\electron.cmd cleanly - that shim is
rem    itself a batch file and start mangles the quoting. Call the real exe.
cd /d "%~dp0"
start "" /b "node_modules\electron\dist\electron.exe" "."
