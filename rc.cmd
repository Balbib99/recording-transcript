@echo off
setlocal
set "RC_ROOT=%~dp0"
if exist "%RC_ROOT%.venv\Scripts\python.exe" (
    set "RC_PY=%RC_ROOT%.venv\Scripts\python.exe"
) else (
    set "RC_PY=python"
)
set "PYTHONPATH=%RC_ROOT%src;%PYTHONPATH%"
"%RC_PY%" -m recordingcraft %*
