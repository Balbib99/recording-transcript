@echo off
rem Cliente de la API: subir grabaciones y leer transcripciones.
rem   cliente.cmd lista
rem   cliente.cmd subir "D:\audio.m4a" --titulo "Reunion"
rem   cliente.cmd ver <id>
setlocal
set "RC_ROOT=%~dp0"
"%RC_ROOT%.venv\Scripts\python.exe" "%RC_ROOT%worker\cliente.py" %*
