@echo off
REM ============================================================
REM iniciar.bat - Lancador de duplo clique para OficinaApp
REM Cria venv se nao existe, instala dependencias, roda app.py
REM ============================================================
cd /d "%~dp0"

echo.
echo ============================================================
echo  OficinaApp  -  Iniciando...
echo ============================================================
echo.

python --version >nul 2>&1
if errorlevel 1 goto sem_python

echo [1/3] Ambiente virtual...
if exist .venv goto deps
python -m venv .venv
if errorlevel 1 goto erro_venv

:deps
echo [2/3] Dependencias...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt
if errorlevel 1 goto erro_deps

if not exist instance mkdir instance

REM .env: cria se faltar, gera SECRET_KEY e pergunta o e-mail do admin na 1a vez
python scripts\preparar_env.py
if errorlevel 1 goto erro_env

:roda
echo [3/3] Servidor em http://127.0.0.1:5000  (abra no navegador)
echo.
echo Primeira vez? A senha do administrador aparece abaixo em "SENHA INICIAL SORTEADA".
echo Pressione Ctrl+C para parar.
echo.
python app.py
goto fim

:sem_python
echo ERRO: Python nao encontrado no PATH.
echo Instale em https://python.org/downloads/ e marque "Add Python to PATH".
goto parar

:erro_venv
echo ERRO ao criar o ambiente virtual .venv
goto parar

:erro_deps
echo ERRO ao instalar as dependencias de requirements.txt
goto parar

:erro_env
echo ERRO ao preparar o arquivo .env (veja a mensagem acima)
goto parar

:parar
echo.
pause
exit /b 1

:fim
echo.
echo Servidor finalizado.
pause
exit /b 0
