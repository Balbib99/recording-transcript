@echo off
chcp 65001 >nul
title Simular desinstalacion de RecordingCraft
rem Igual que DESINSTALAR.cmd pero sin borrar nada: solo enseña que se borraria.
cd /d "%TEMP%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0desinstalar.ps1" -Simular
