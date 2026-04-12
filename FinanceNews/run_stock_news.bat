@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d D:\workspace\QClaw\FinanceNews
python stock_news.py %*
pause
