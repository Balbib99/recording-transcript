<#
  Deshace scripts\instalar-arranque-worker.ps1: para el worker que este corriendo
  y borra la tarea programada. El worker sigue funcionando a mano, con
  INICIAR-WORKER.cmd. No toca grabaciones, configuracion ni la Pi.

  Hay que lanzarlo desde PowerShell abierto como administrador:
      powershell -ExecutionPolicy Bypass -File scripts\quitar-arranque-worker.ps1

  Con -SoloParar detiene el worker pero deja la tarea, y volvera a arrancar en el
  siguiente encendido. Sirve tambien para reiniciarlo tras cambiar config.toml o
  actualizar el codigo; luego: Start-ScheduledTask -TaskName "RecordingCraft Worker"

  Si en ese momento hay una reunion transcribiendose, se interrumpe. No se pierde:
  queda en "procesando" y vuelve sola a la cola; para no esperar, usa
  cliente.cmd reencolar <id>
#>

param([switch]$SoloParar)

$ErrorActionPreference = 'Stop'

$Tarea = 'RecordingCraft Worker'

$EsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $EsAdmin) {
    Write-Host ''
    Write-Host '  Hacen falta permisos de administrador.'
    Write-Host '  Abre PowerShell como administrador y vuelve a lanzar este script.'
    Write-Host ''
    exit 1
}

$Existe = Get-ScheduledTask -TaskName $Tarea -ErrorAction SilentlyContinue
if ($Existe) {
    Stop-ScheduledTask -TaskName $Tarea -ErrorAction SilentlyContinue
}

# Parar la tarea no basta: python.exe del entorno virtual lanza otro proceso, y
# el worker lanza ssh para el tunel. Se buscan por su linea de ordenes.
$Procesos = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -eq 'python.exe' -and $_.CommandLine -match 'worker\.py') -or
    ($_.Name -eq 'ssh.exe' -and $_.CommandLine -match 'ExitOnForwardFailure')
}
foreach ($Proceso in $Procesos) {
    Stop-Process -Id $Proceso.ProcessId -Force -ErrorAction SilentlyContinue
}
Write-Host "  Procesos parados: $(@($Procesos).Count)"

if ($SoloParar) {
    Write-Host '  Worker parado. La tarea sigue instalada.'
    exit 0
}

if ($Existe) {
    Unregister-ScheduledTask -TaskName $Tarea -Confirm:$false
    Write-Host "  Tarea '$Tarea' eliminada. El worker ya no arranca con Windows."
} else {
    Write-Host "  La tarea '$Tarea' no existia."
}
