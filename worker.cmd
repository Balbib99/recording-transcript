@echo off
rem Lanza el worker de transcripcion. Ctrl+C para pararlo.
rem   worker.cmd           bucle: espera trabajo y lo procesa
rem   worker.cmd --once    un trabajo y termina
setlocal
set "RC_ROOT=%~dp0"
"%RC_ROOT%.venv\Scripts\python.exe" "%RC_ROOT%worker\worker.py" %*
