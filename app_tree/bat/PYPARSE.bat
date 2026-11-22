

set BAT_FILE_PATH=%CD%
echo The absolute path of this batch file is: %BAT_FILE_PATH%


 
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
    
	black %%F
    python.exe %CD%\Parser_Python\parse_Python.py %%F

    start VFC2000 %%F.vfc -Reload
)


pause


