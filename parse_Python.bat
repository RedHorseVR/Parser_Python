echo off
rem DRAG DROP TO PARSE AND MAKE BACKUP FOR CODE FILE 
rem MUST BE VALID PYTHON TO WORK - NO SYNTAX ERRORS 
rem TO VIEW AS FLOW YOU WILL NEED TO OBTAIN VFC2000.exe 
rem EMAIL luis.r.lopez@outlook.com for access or check for a GitHub.com/RedhorseVR/VFCode open version
rem NEED TO SET VFCTOOLPATH and COMMENTPARSERPATH to where you have the tools 


set BAT_FILE_PATH=%CD%
echo The absolute path of this batch file is: %BAT_FILE_PATH%


echo off
set filepath=%1
for %%A in ("%filepath%") do set filename=%%~nxA
echo Filename: %filename%
ECHO %CD%/%filename%
echo -----------------------

echo off
echo Processing files...

for %%F in (%*) do (
	echo Processing: "%%F"
	echo root: %filename%
	echo Folder: %~dp1

	copy %1 %~dp1\_%filename%

	python %BAT_FILE_PATH%\parse_Python.py %1


)






dir

echo ---------------- %1.vfc

start VFC2000 %1.vfc


