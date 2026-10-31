<#
  Hace que el worker arranque con Windows, sin necesidad de iniciar sesion.

  Crea la tarea programada "RecordingCraft Worker". Es lo unico que toca: no
  cambia nada de la BIOS, de la Pi ni de la configuracion del proyecto.
  Se deshace con scripts\quitar-arranque-worker.ps1

  Hay que lanzarlo desde PowerShell abierto como administrador, con TU usuario:
      powershell -ExecutionPolicy Bypass -File scripts\instalar-arranque-worker.ps1

  Se puede repetir: si la tarea ya existe, la sustituye.

  Por que asi:
  - Al iniciar el equipo (no "al iniciar sesion"): encendido desde la app, nadie
    va a teclear la contrasena.
  - Inicio de sesion S4U: corre como tu usuario sin guardar tu contrasena en
    ningun sitio. A cambio no tiene acceso a recursos de red de Windows, que el
    worker no usa: habla con la Pi por SSH, con su clave.
  - --insistir: si al arrancar aun no hay red, reintenta en vez de cerrarse.
  - python.exe y no pythonw.exe: en la sesion de servicios no se ve ninguna
    ventana, y pythonw no tiene salida estandar, que algunas librerias esperan.
#>

$ErrorActionPreference = 'Stop'

$Tarea  = 'RecordingCraft Worker'
$Raiz   = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Raiz '.venv\Scripts\python.exe'
$Worker = Join-Path $Raiz 'worker\worker.py'
$Log    = Join-Path $Raiz 'worker\worker.log'

$Identidad = [Security.Principal.WindowsIdentity]::GetCurrent()
$EsAdmin = ([Security.Principal.WindowsPrincipal]$Identidad).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $EsAdmin) {
    Write-Host ''
    Write-Host '  Hacen falta permisos de administrador.'
    Write-Host '  Abre PowerShell como administrador y vuelve a lanzar este script.'
    Write-Host ''
    exit 1
}

foreach ($Necesario in @($Python, $Worker, (Join-Path $Raiz 'worker\.env'))) {
    if (-not (Test-Path $Necesario)) {
        Write-Host "  Falta: $Necesario"
        exit 1
    }
}

$Accion = New-ScheduledTaskAction -Execute $Python `
    -Argument "`"$Worker`" --insistir" -WorkingDirectory $Raiz

$Disparador = New-ScheduledTaskTrigger -AtStartup
$Disparador.Delay = 'PT30S'   # da tiempo a que la red este lista

$Usuario = New-ScheduledTaskPrincipal -UserId $Identidad.Name `
    -LogonType S4U -RunLevel Limited

# Prioridad 4 = normal. La de defecto (7) frena CPU y disco: mala idea para
# transcribir. Sin limite de tiempo, porque el worker no termina nunca.
$Ajustes = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -DontStopOnIdleEnd `
    -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -Priority 4

Register-ScheduledTask -TaskName $Tarea -Action $Accion -Trigger $Disparador `
    -Principal $Usuario -Settings $Ajustes -Force `
    -Description 'Worker de transcripcion de RecordingCraft. Se quita con scripts\quitar-arranque-worker.ps1' `
    | Out-Null

Write-Host ''
Write-Host "  Tarea '$Tarea' creada para $($Identidad.Name)."
Write-Host '  La arranco ahora para comprobar que funciona...'

Start-ScheduledTask -TaskName $Tarea
Start-Sleep -Seconds 10

$Estado = (Get-ScheduledTask -TaskName $Tarea).State
Write-Host "  Estado: $Estado"
Write-Host ''
Write-Host '  Ultimas lineas del registro:'
if (Test-Path $Log) {
    Get-Content $Log -Tail 5 -Encoding UTF8 | ForEach-Object { Write-Host "    $_" }
}
Write-Host ''
Write-Host '  Si ves "Ya hay otro worker en marcha", cierra la ventana del worker que'
Write-Host '  tengas abierta y arranca la tarea: Start-ScheduledTask -TaskName "RecordingCraft Worker"'
Write-Host ''
