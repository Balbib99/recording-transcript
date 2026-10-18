@echo off
rem Doble clic para poner el worker a transcribir.
title RecordingCraft - worker
cd /d "%~dp0"
call "%~dp0worker.cmd" %*
pause
