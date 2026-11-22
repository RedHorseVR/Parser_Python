@echo off
rem Commit, then open the Push window. Two steps, each its own launcher; this stops if the commit step fails.
call "%~dp0COMMIT.bat" || exit /b 1
call "%~dp0PUSH.bat"
