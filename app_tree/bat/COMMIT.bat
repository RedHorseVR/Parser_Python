@echo off
setlocal EnableExtensions

rem Scope this commit to EXACTLY the project folder (two folders above app_tree\bat).
rem Do not climb to the repository root and do not broaden the TortoiseGit path.
for %%I in ("%~dp0..\..") do set "PROJECT_DIR=%%~fI"
pushd "%PROJECT_DIR%" >nul 2>&1 || (
  echo Could not open project folder:
  echo "%PROJECT_DIR%"
  pause
  exit /b 2
)

rem THE VERSION IS READ, NEVER TYPED.
rem VERSION.txt is the one place a release number lives; this reads it.
set "PROJECT_VERSION="
for /f "usebackq delims=" %%V in ("%PROJECT_DIR%\.zygote\VERSION.txt") do if not defined PROJECT_VERSION set "PROJECT_VERSION=%%V"
if not defined PROJECT_VERSION (
  echo.
  echo Could not read .zygote\VERSION.txt in:
  echo "%PROJECT_DIR%"
  echo.
  pause
  popd
  exit /b 4
)

rem Validate only that this exact folder is somewhere inside a Git working tree.
git -C "%PROJECT_DIR%" rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
  echo.
  echo This project folder is not inside a Git working tree:
  echo "%PROJECT_DIR%"
  echo.
  echo A new project has no repo until its first build is done: that is normal. Create the repo from the first build,
  echo then adapt this file to it - see START_HERE.md, "After the first build" - then run it again.
  echo COMMIT.bat will not search upward for another project and will not use C:\.
  echo.
  pause
  popd
  exit /b 3
)

set "TG="
for %%P in (TortoiseGitProc.exe) do if not "%%~$PATH:P"=="" set "TG=%%~$PATH:P"
if not defined TG if exist "%ProgramFiles%\TortoiseGit\bin\TortoiseGitProc.exe" set "TG=%ProgramFiles%\TortoiseGit\bin\TortoiseGitProc.exe"
if not defined TG if defined ProgramFiles(x86) if exist "%ProgramFiles(x86)%\TortoiseGit\bin\TortoiseGitProc.exe" set "TG=%ProgramFiles(x86)%\TortoiseGit\bin\TortoiseGitProc.exe"
if not defined TG (
  echo.
  echo TortoiseGitProc.exe was not found.
  echo Install TortoiseGit or add its bin folder to PATH, then run COMMIT.bat again.
  echo.
  pause
  popd
  exit /b 2
)

set "MSG=%TEMP%\PROJECT_COMMIT_%RANDOM%_%RANDOM%.txt"
>"%MSG%" echo %PROJECT_VERSION%
>>"%MSG%" echo.
rem ---------------------------------------------------------------------------
rem RELEASE NOTES - rewritten with every version bump, describing THAT build.
rem One line per change, newest first, in the order someone reviewing the diff would want it.
rem ---------------------------------------------------------------------------
>>"%MSG%" echo - PARSER_PYTHON_0.1.5: SameProgram (are two Python files the same program with only things moved around, by AST). Notes: RELEASE_NOTES_PARSER_PYTHON_0.1.5.md
>>"%MSG%" echo - PARSER_PYTHON_0.1.4: one tab for each level of four spaces inside a var box; the export reads a tab as one level. Notes: RELEASE_NOTES_PARSER_PYTHON_0.1.4.md
>>"%MSG%" echo - PARSER_PYTHON_0.1.3: RUN.bat does not pause at the end. Notes: RELEASE_NOTES_PARSER_PYTHON_0.1.3.md
>>"%MSG%" echo - PARSER_PYTHON_0.1.2: the white space in front of a var box is left off its rows and the export indents from where the box stands; read_rows can return the begin and end marks; 36 tests. Notes: RELEASE_NOTES_PARSER_PYTHON_0.1.2.md
>>"%MSG%" echo - Vars: a list, dictionary, set or tuple assigned over several lines is written between the notes ;@beginvar and ;@endvar, each line a generic row. VFlow draws it as one box; the legacy tool skips the notes.
>>"%MSG%" echo - Black runs at 100 on both sides of the check (RoundTrip.LINE_LENGTH).
>>"%MSG%" echo - New test_files\test1.py: legal Python that runs, with every structure the parser handles. RUN.bat pauses at the end.
>>"%MSG%" echo - Notes: RELEASE_NOTES_PARSER_PYTHON_0.1.1.md and RELEASE_NOTES_PARSER_PYTHON_0.1.0.md, and SYNC_exporter_with_VFlow.md for what VFlow must take from FlowToPy.py.
>>"%MSG%" echo - Tests: app_tree\tests\test_parser.py (42), RUN_TESTS.bat. The parser parses itself and every sample file; all round trip.
>>"%MSG%" echo - New RUN.bat: runs app\parse_Python.py with what you give it (no file name: help).
>>"%MSG%" echo - Check: the flow file is read back, exported by FlowToPy.py, run through Black and compared with the Black source; a difference is printed and saved as file.py.roundtrip.txt.
>>"%MSG%" echo - New parser: Black, then one AST pass writes the .vfc rows; no commented copy of the source. The old comment route is kept in app\extras.
rem IMPORTANT: /path is PROJECT_DIR, not the parent Git root.
"%TG%" /command:commit /path:"%PROJECT_DIR%" /logmsgfile:"%MSG%" /closeonend:2
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo TortoiseGit returned error code %RC%.
  pause
)
del /q "%MSG%" >nul 2>&1
popd
exit /b %RC%
