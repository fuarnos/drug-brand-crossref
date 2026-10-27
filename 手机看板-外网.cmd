@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" set "PY=python"
echo.
echo  手机看板 · 外网 / 4G
echo  ------------------------------------------------------------
echo  会另起 cloudflared 隧道，终端会打印一个 https://xxx.trycloudflare.com 地址
echo  首次运行自动下载 cloudflared（约 55 MB，只需一次）
echo  地址每次重启都会变；进程活着期间稳定
echo  关掉这个窗口就停止服务和隧道
echo.
"%PY%" mobile\server.py --host 0.0.0.0 --port 8787 --tunnel %*
pause
