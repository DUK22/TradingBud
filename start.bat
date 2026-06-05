@echo off
REM ==== IR Traders - inicializador (Windows) ====
cd /d "%~dp0"
echo Criando ambiente virtual (primeira vez pode demorar)...
if not exist ".venv" python -m venv .venv
call .venv\Scripts\activate.bat
echo Instalando dependencias...
python -m pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo Criando dados de demonstracao (login: demo@trader.com / demo1234)...
python seed.py
echo.
echo Abrindo http://127.0.0.1:5000 ...
start "" http://127.0.0.1:5000
python run.py
pause
