@echo off
echo Setting up Sports Connect Automation...
python -m venv venv
call venv\Scripts\activate
pip install -r requirements.txt
python scripts\setup.py
pause
