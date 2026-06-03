@echo off
echo [1/3] Pulling latest code...
cd /d C:\project_list\connect-ai
git pull origin claude/charming-hopper-M7yZf

echo [2/3] Copying stock.py to workspace...
copy /Y C:\project_list\connect-ai\stock.py C:\project_list\NA-stock-ai\stock.py

echo [3/3] Done.
pause
