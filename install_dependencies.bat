@echo off
python -m venv venv
cd /d "%~dp0"
call "%~dp0\venv\Scripts\activate.bat"
python -m pip install -r requirements.txt
pause