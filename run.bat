@echo off
cd /d "%~dp0"
call "%~dp0\venv\Scripts\activate.bat"
python src/main.py
pause