@echo off
rem Semiconductor Signal System launcher
rem NOTE: keep this file pure ASCII and CRLF line endings.
cd /d %~dp0
"%~dp0..\..\.venv\Scripts\python.exe" -m streamlit run app\Home.py --server.port 8512
pause
