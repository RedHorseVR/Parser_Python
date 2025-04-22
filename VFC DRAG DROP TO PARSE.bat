rem DRAG DROP TO PARSE AND MAKE BACKUP FOR CODE FILE 
rem MUST BE VALID PYTHON TO WORK - NO SYSNTAX ERRORS 
rem TO VIEW NEED TO OBTAIN VFC2000.exe (EMAIL luis.r.lopez@outlook.com for access or check GitHub.com/RedhorseVR for open source from VFCode
rem NEED TO SET VFCTOOLPATH and COMMENTPARSERPATH to where you have the tools 


SET VFCTOOLPATH=E:\Users\luisr\OneDrive\VFC1.0
SET COMMENTPARSERPATH=C:\Users\luisr\pyCommentParser


python %COMMENTPARSERPATH%\pyCommentParser.py %1

echo off
set filepath=%1
for %%A in ("%filepath%") do set filename=%%~nxA
echo Filename: %filename%

copy %filename% _%filename%

dir


start %VFCTOOLPATH%\VFC2000.exe %1.vfc

pause