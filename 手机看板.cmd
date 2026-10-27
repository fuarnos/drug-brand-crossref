@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" set "PY=python"
echo.
echo  手机看板：手机看进度 / 发指令
echo  ------------------------------------------------------------
echo  同一 Wi-Fi：手机打开下面打印的内网地址（带 ?k=token）
echo  外网 / 4G ：加 --tunnel，会另给一个 https 地址
echo  关掉这个窗口就停止服务
echo.
"%PY%" mobile\server.py --host 0.0.0.0 --port 8787 --open %*
pause
