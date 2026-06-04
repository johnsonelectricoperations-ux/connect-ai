@echo off
cd /d C:\project_list\connect-ai

echo [1/4] Pulling latest code...
git pull origin claude/charming-hopper-M7yZf
if errorlevel 1 goto :error

echo [2/4] Copying tools (stock, macro, backtest, sec) to workspace...
copy /Y C:\project_list\connect-ai\stock.py C:\project_list\NA-stock-ai\stock.py
copy /Y C:\project_list\connect-ai\macro.py C:\project_list\NA-stock-ai\macro.py
copy /Y C:\project_list\connect-ai\backtest.py C:\project_list\NA-stock-ai\backtest.py
copy /Y C:\project_list\connect-ai\sec.py C:\project_list\NA-stock-ai\sec.py
copy /Y C:\project_list\connect-ai\portfolio.py C:\project_list\NA-stock-ai\portfolio.py
copy /Y C:\project_list\connect-ai\screen.py C:\project_list\NA-stock-ai\screen.py

echo [3/4] Deploying agent skills to brain company folder...
xcopy /E /I /Y "C:\project_list\connect-ai\agent-skills" "C:\project_list\ai_agent_antigravity\_company\_agents"

echo [3a/4] Deploying investment knowledge + templates to brain wiki...
xcopy /E /I /Y "C:\project_list\connect-ai\knowledge-pack\10_Wiki" "C:\project_list\ai_agent_antigravity\10_Wiki"

echo Seeding portfolio.csv / watchlist.txt (only if missing - your data is preserved)...
if not exist "C:\project_list\NA-stock-ai\portfolio.csv" copy /Y "C:\project_list\connect-ai\portfolio.csv.example" "C:\project_list\NA-stock-ai\portfolio.csv"
if not exist "C:\project_list\NA-stock-ai\watchlist.txt" copy /Y "C:\project_list\connect-ai\watchlist.txt.example" "C:\project_list\NA-stock-ai\watchlist.txt"

echo [3b/4] Compiling extension...
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
