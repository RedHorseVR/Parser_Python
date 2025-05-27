

set BAT_FILE_PATH=%CD%
echo The absolute path of this batch file is: %BAT_FILE_PATH%


 
echo off
echo Processing files...

@echo off
setlocal enabledelayedexpansion

for %%F in (%*) do (
    echo Processing: "%%F"

    set filename=%%~nxF
    echo root: !filename!
    echo Folder: %%~dpF
    echo -----------------------
    
    copy %%F %%~dpF\_!filename!
    
    python %BAT_FILE_PATH%\parse_Python.py %%F

    start VFC2000 %%F.vfc
)



