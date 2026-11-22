@echo off
setlocal EnableExtensions

rem Opens TortoiseGit's Push window for EXACTLY the project folder (two folders above app_tree\bat).
for %%I in ("%~dp0..\..") do set "PROJECT_DIR=%%~fI"

set "TG="
for %%P in (TortoiseGitProc.exe) do if not "%%~$PATH:P"=="" set "TG=%%~$PATH:P"
if not defined TG if exist "%ProgramFiles%\TortoiseGit\bin\TortoiseGitProc.exe" set "TG=%ProgramFiles%\TortoiseGit\bin\TortoiseGitProc.exe"
if not defined TG if defined ProgramFiles(x86) if exist "%ProgramFiles(x86)%\TortoiseGit\bin\TortoiseGitProc.exe" set "TG=%ProgramFiles(x86)%\TortoiseGit\bin\TortoiseGitProc.exe"
if not defined TG (
  echo.
  echo TortoiseGitProc.exe was not found.
  echo Install TortoiseGit or add its bin folder to PATH, then run PUSH.bat again.
  echo.
  pause
  exit /b 2
)

"%TG%" /command:push /path:"%PROJECT_DIR%" /closeonend:2
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo TortoiseGit returned error code %RC%.
  pause
)
exit /b %RC%
