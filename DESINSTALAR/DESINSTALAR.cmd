@echo off
chcp 65001 >nul
title Desinstalar RecordingCraft
rem Se cambia a %TEMP% para que esta ventana no bloquee el borrado de la carpeta.
cd /d "%TEMP%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0desinstalar.ps1" %*
