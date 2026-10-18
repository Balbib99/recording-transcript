<#
.SYNOPSIS
    Desinstala RecordingCraft por completo: entorno virtual, modelos descargados
    y la propia carpeta del proyecto.

.DESCRIPTION
    Enseña primero todo lo que va a borrar con su tamaño, ofrece guardar una copia
    de las transcripciones y pide confirmacion escrita antes de tocar nada.

    No toca ffmpeg (es independiente del proyecto) ni tu token de Hugging Face.

.PARAMETER Simular
    Enseña lo que se borraria sin borrar nada.

.PARAMETER ConservarModelos
    No borra los modelos descargados en la cache de Hugging Face / torch.

.PARAMETER ConservarTranscripciones
    No borra data\meetings (pero si el resto del proyecto, asi que conviene
    combinarlo con la copia de seguridad que ofrece el script).

.PARAMETER SinPreguntar
    No pide confirmacion. Usalo solo si sabes exactamente lo que haces.

.EXAMPLE
    .\desinstalar.ps1 -Simular
    .\desinstalar.ps1
#>
[CmdletBinding()]
param(
    [switch]$Simular,
    [switch]$ConservarModelos,
    [switch]$ConservarTranscripciones,
    [switch]$SinPreguntar
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Write-Titulo($texto) {
    Write-Host ""
    Write-Host $texto -ForegroundColor Cyan
    Write-Host ("-" * $texto.Length) -ForegroundColor DarkGray
}

function Get-Tamano($ruta) {
    if (-not (Test-Path $ruta)) { return 0 }
    $item = Get-Item $ruta -Force
    if (-not $item.PSIsContainer) { return $item.Length }
    $suma = (Get-ChildItem $ruta -Recurse -File -Force -ErrorAction SilentlyContinue |
             Measure-Object -Property Length -Sum).Sum
    if ($null -eq $suma) { return 0 }
    return $suma
}

function Formatear($bytes) {
    if ($bytes -ge 1GB) { return "{0,8:N2} GB" -f ($bytes / 1GB) }
    if ($bytes -ge 1MB) { return "{0,8:N0} MB" -f ($bytes / 1MB) }
    return "{0,8:N0} KB" -f ($bytes / 1KB)
}

# --- salvaguarda: esto tiene que ser RecordingCraft de verdad ----------
$marcador = Join-Path $root "pyproject.toml"
if (-not (Test-Path $marcador)) {
    Write-Host "ABORTADO: no encuentro pyproject.toml en $root" -ForegroundColor Red
    Write-Host "Este script solo debe ejecutarse desde DESINSTALAR\ dentro del proyecto."
    Read-Host "Pulsa Enter para salir"
    exit 1
}
if ((Get-Content $marcador -Raw) -notmatch 'name\s*=\s*"recordingcraft"') {
    Write-Host "ABORTADO: $root no parece ser RecordingCraft." -ForegroundColor Red
    Read-Host "Pulsa Enter para salir"
    exit 1
}

Write-Host ""
Write-Host "  DESINSTALADOR DE RECORDINGCRAFT" -ForegroundColor Yellow
Write-Host "  Proyecto: $root"
if ($Simular) {
    Write-Host "  MODO SIMULACION: no se va a borrar nada." -ForegroundColor Green
}

# --- inventario --------------------------------------------------------
$objetivos = @()
$objetivos += [pscustomobject]@{ Tipo = "proyecto"; Ruta = $root; Bytes = (Get-Tamano $root) }

$hub = Join-Path $env:USERPROFILE ".cache\huggingface\hub"
$patronesHub = @(
    "models--Systran--faster-whisper-*",      # modelos de transcripcion
    "models--pyannote--*",                    # diarizacion y segmentacion
    "models--jonatasgrosman--wav2vec2-*"      # alineacion de algunos idiomas
)
$torchHub = Join-Path $env:USERPROFILE ".cache\torch\hub\checkpoints"

if (-not $ConservarModelos) {
    if (Test-Path $hub) {
        foreach ($patron in $patronesHub) {
            Get-ChildItem $hub -Directory -Filter $patron -ErrorAction SilentlyContinue |
                ForEach-Object {
                    $objetivos += [pscustomobject]@{
                        Tipo = "modelo"; Ruta = $_.FullName; Bytes = (Get-Tamano $_.FullName)
                    }
                }
        }
    }
    if (Test-Path $torchHub) {
        Get-ChildItem $torchHub -File -Filter "wav2vec2_*.pt" -ErrorAction SilentlyContinue |
            ForEach-Object {
                $objetivos += [pscustomobject]@{
                    Tipo = "modelo"; Ruta = $_.FullName; Bytes = $_.Length
                }
            }
    }
}

Write-Titulo "Se va a borrar"
foreach ($o in $objetivos) {
    $etiqueta = if ($o.Tipo -eq "proyecto") { "[proyecto]" } else { "[modelo]  " }
    Write-Host ("  {0} {1}  {2}" -f $etiqueta, (Formatear $o.Bytes), $o.Ruta)
}
$total = ($objetivos | Measure-Object -Property Bytes -Sum).Sum
Write-Host ""
Write-Host ("  TOTAL A LIBERAR: {0}" -f (Formatear $total).Trim()) -ForegroundColor Yellow

Write-Titulo "NO se toca"
Write-Host "  ffmpeg            (quitalo aparte con: winget uninstall Gyan.FFmpeg)"
Write-Host "  Tu token de HF    (revocalo en https://huggingface.co/settings/tokens)"
Write-Host "  Python            (sigue instalado en el sistema)"
if ($ConservarModelos) {
    Write-Host "  Modelos           (-ConservarModelos)"
}

# --- copia de seguridad de las transcripciones -------------------------
$meetings = Join-Path $root "data\meetings"
$reuniones = @()
if (Test-Path $meetings) {
    $reuniones = @(Get-ChildItem $meetings -Directory -ErrorAction SilentlyContinue)
}

if ($reuniones.Count -gt 0 -and -not $Simular) {
    Write-Titulo "Tienes $($reuniones.Count) reunion(es) transcrita(s)"
    $destino = Join-Path ([Environment]::GetFolderPath("Desktop")) ("RecordingCraft-transcripciones-" + (Get-Date -Format "yyyy-MM-dd"))
    Write-Host "  Puedo copiar las transcripciones al escritorio antes de borrar:"
    Write-Host "  $destino"
    Write-Host "  (solo los textos: md, txt, srt, json y speakers.toml; sin los audios)"

    $copiar = $true
    if (-not $SinPreguntar) {
        $r = Read-Host "  Guardar esa copia? [S/n]"
        if ($r -match '^[nN]') { $copiar = $false }
    }

    if ($copiar) {
        New-Item -ItemType Directory -Force -Path $destino | Out-Null
        foreach ($reunion in $reuniones) {
            $sub = Join-Path $destino $reunion.Name
            New-Item -ItemType Directory -Force -Path $sub | Out-Null
            Get-ChildItem $reunion.FullName -File |
                Where-Object { $_.Extension -in ".md", ".txt", ".srt", ".json", ".toml" } |
                Copy-Item -Destination $sub -Force
        }
        Write-Host "  Copia guardada." -ForegroundColor Green
    }
}

if ($Simular) {
    Write-Host ""
    Write-Host "Simulacion terminada: no se ha borrado nada." -ForegroundColor Green
    Read-Host "Pulsa Enter para salir"
    exit 0
}

# --- confirmacion ------------------------------------------------------
if (-not $SinPreguntar) {
    Write-Host ""
    Write-Host "  Esto es irreversible." -ForegroundColor Red
    $confirmacion = Read-Host "  Escribe BORRAR para continuar (cualquier otra cosa cancela)"
    if ($confirmacion -cne "BORRAR") {
        Write-Host ""
        Write-Host "Cancelado. No se ha borrado nada." -ForegroundColor Green
        Read-Host "Pulsa Enter para salir"
        exit 0
    }
}

# --- borrado de modelos ------------------------------------------------
Write-Titulo "Borrando"
foreach ($o in ($objetivos | Where-Object { $_.Tipo -eq "modelo" })) {
    try {
        Remove-Item -Recurse -Force -LiteralPath $o.Ruta
        Write-Host "  borrado: $($o.Ruta)" -ForegroundColor DarkGray
    } catch {
        Write-Host "  ! no se pudo borrar $($o.Ruta): $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

# --- transcripciones que se conservan ----------------------------------
if ($ConservarTranscripciones -and (Test-Path $meetings)) {
    $rescate = Join-Path ([Environment]::GetFolderPath("Desktop")) ("RecordingCraft-meetings-" + (Get-Date -Format "yyyy-MM-dd-HHmm"))
    Move-Item -LiteralPath $meetings -Destination $rescate
    Write-Host "  reuniones movidas a: $rescate" -ForegroundColor Green
}

# --- borrado del proyecto (en diferido: el script vive dentro) ---------
# No se puede borrar la carpeta desde la que se esta ejecutando el propio
# script, asi que se lanza un cmd independiente desde %TEMP% que espera a
# que este proceso termine y lo intenta varias veces.
$script = Join-Path $env:TEMP ("recordingcraft-borrar-" + [guid]::NewGuid().ToString("N") + ".cmd")
$contenido = @"
@echo off
set INTENTOS=0
:reintentar
timeout /t 2 /nobreak >nul
rmdir /s /q "$root" 2>nul
if not exist "$root" goto hecho
set /a INTENTOS+=1
if %INTENTOS% lss 15 goto reintentar
echo.
echo No se pudo borrar "$root".
echo Cierra VS Code, el explorador y cualquier terminal abierta ahi dentro,
echo y borra la carpeta a mano.
pause
:hecho
del "%~f0" >nul 2>&1
"@
Set-Content -LiteralPath $script -Value $contenido -Encoding OEM

Write-Host ""
Write-Host "  Modelos borrados." -ForegroundColor Green
Write-Host "  La carpeta del proyecto se borrara en unos segundos, al cerrarse esta ventana."
Write-Host ""
Write-Host "  Si despues sigue existiendo, es que algo la tiene abierta" -ForegroundColor DarkGray
Write-Host "  (VS Code, el explorador, una terminal): cierralo y borrala a mano." -ForegroundColor DarkGray
Write-Host ""
Read-Host "  Pulsa Enter para terminar"

Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "`"$script`"" `
    -WorkingDirectory $env:TEMP -WindowStyle Hidden
