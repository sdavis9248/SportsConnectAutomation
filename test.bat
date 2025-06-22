@echo off
echo Running tests...
call venv\Scripts\activate
pytest tests -v
pause
