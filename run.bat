@echo off
echo Starting Sports Connect Automation...
call venv\Scripts\activate
python src\main.py %*
pause
