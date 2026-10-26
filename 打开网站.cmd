@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" serve.py 8000 --open
pause