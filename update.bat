@echo off
cd /d C:\project_list\connect-ai

echo [1/4] Pulling latest code...
git pull origin claude/charming-hopper-M7yZf
if errorlevel 1 goto :error

echo [2/4] Copying stock.py to workspace...
copy /Y C:\project_list\connect-ai\stock.py C:\project_list\NA-stock-ai\stock.py

echo [3/4] Compiling extension...
call npm run compile
if errorlevel 1 goto :error

echo [4/4] Packaging VSIX...
call npx vsce package
if errorlevel 1 goto :error

echo.
echo ========================================
echo  DONE. Install the .vsix in Antigravity:
echo  Extensions panel - "..." - Install from VSIX
echo  Then Reload Window and start a NEW chat.
echo ========================================
pause
exit /b 0

:error
echo.
echo !!! FAILED. Check the error above.
pause
exit /b 1
