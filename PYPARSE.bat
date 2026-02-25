echo off

set BAT_FILE_PATH=%~dp0%
prompt :

echo .................
echo The absolute path of this batch file is: %BAT_FILE_PATH%
echo .................

 
echo off
echo Processing files...

setlocal enabledelayedexpansion

for %%F in (%*) do (
    echo Processing: "%%F"

    set filename=%%~nxF
    echo root: !filename!
    echo Folder: %%~dpF
    echo -----------------------
    
    copy %%F %%~dpF\_!filename!
    
    python.exe %BAT_FILE_PATH%parse_Python.py %%F

    start VFC2000 %%F.vfc -Reload
)

PAUSE

pause