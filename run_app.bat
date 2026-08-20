@echo off
rem Semiconductor Signal System launcher
rem NOTE: keep this file pure ASCII and CRLF line endings.
cd /d %~dp0

rem ---- Port guard: evict any process squatting on 8512 before we bind ----
powershell -NoProfile -Command "Get-NetTCPConnection -State Listen -LocalPort 8512 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Write-Host ('[port-guard] port 8512 occupied by PID ' + $_ + ' - killing'); Stop-Process -Id $_ -Force }; Start-Sleep -Milliseconds 800"

"%~dp0..\..\.venv\Scripts\python.exe" -m streamlit run app\Home.py --server.port 8512
pause
