@ECHO OFF

REM SET THESE VARIABLES
set templateurl=https://github.com/costateixeira/smart-ig-template-who.git
set templatebranch=master
set templatefolder=who.fhir.template#current


REM NORMALLY YOU DON'T NEED TO TOUCH THESE
set packagePath=%USERPROFILE%\.fhir\packages
set DEST_FOLDER=%packagePath%\%templatefolder%
set TEMP_FOLDER=TEMPLATE


REM ---- SCRIPT BEGINS HERE


echo 1. Delete temporary folders....
DEL /F/Q/S %TEMP_FOLDER%
RMDIR /Q/S %TEMP_FOLDER%
echo Done


echo 2. Clone repo w branch
git clone --branch %templatebranch% %templateurl% %TEMP_FOLDER%
cd %TEMP_FOLDER%

REM delete the package.json to make sure it won't ever overwrite the one we need to preserve
del package\package.json

echo 3. Re-organizing the content of the repository to be under the package folder

call robocopy . original_package /E /XD original_package .git /Move
call robocopy original_package newpackage /E /XD "original_package" "newpackage" /XF "getTemplate.bat" /Move

md newpackage\$root
move newpackage\*.* newpackage\$root

move newpackage\package\*.* newpackage
rd newpackage\package

echo 4. Remove the .git folder and setting the right folder name
DEL /F/Q/S .\.git
RMDIR /Q/S .\.git
ren newpackage package

cd ..

echo 5. renaming the original folder to keep it but give room to the new one
rem ren "%DEST_FOLDER%" "%DEST_FOLDER%-ORIGINAL"

echo 5. moving the original folder to another name, keep its content, but giving room to the new one

call robocopy %DEST_FOLDER% %DEST_FOLDER%-ORIGINAL  /MIR /ETA /Move /Move


echo 6. Moving the temp content to the template cache
call robocopy %TEMP_FOLDER% %DEST_FOLDER% /E /XD "original_package" "newpackage" /XF "getTemplate.bat" /Move

echo 7. restoring the package.json
echo copy %DEST_FOLDER%-ORIGINAL\package\package.json %DEST_FOLDER%\package\package.json
copy %DEST_FOLDER%-ORIGINAL\package\package.json %DEST_FOLDER%\package\package.json

echo Done
