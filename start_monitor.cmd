@echo off
cd /d "%~dp0"
pythonw exploration_monitor.py --camera http://127.0.0.1:8768 --rotation 180
