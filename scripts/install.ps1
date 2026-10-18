<#
.SYNOPSIS
    Instala RecordingCraft: entorno virtual, WhisperX y PyTorch con CUDA.

.DESCRIPTION
    Importante: WhisperX se instala PRIMERO porque fija su propia version de
    PyTorch (y la baja de PyPI, que en Windows es la compilacion sin CUDA).
    Despues se reinstalan torch/torchaudio/torchvision en esa misma version
    pero desde el indice CUDA, para no perder la GPU.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\install.ps1
    powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Cpu
#>
[CmdletBinding()]
param(
    # No instalar CUDA: dejar PyTorch en modo CPU.
    [switch]$Cpu,
    # Version de Python para el entorno virtual.
    [string]$PythonVersion = "3.12",
    # Ruedas CUDA a probar, de mas nueva a mas antigua.
    [string[]]$CudaTags = @("cu126", "cu124", "cu121")
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "RecordingCraft - instalacion" -ForegroundColor Cyan
Write-Host "Proyecto: $root"
Write-Host ""

# --- 1. ffmpeg ---------------------------------------------------------
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Warning "No se encuentra ffmpeg en el PATH. Instalalo con:  winget install Gyan.FFmpeg"
    Write-Warning "Despues cierra y abre la terminal para que el PATH se actualice."
}

# --- 2. entorno virtual ------------------------------------------------
$venv = Join-Path $root ".venv"
$py = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "Creando entorno virtual con Python $PythonVersion..." -ForegroundColor Cyan
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py "-$PythonVersion" -m venv $venv
    } else {
        & python -m venv $venv
    }
    if (-not (Test-Path $py)) { throw "No se pudo crear el entorno virtual en $venv" }
} else {
    Write-Host "Entorno virtual ya existente: $venv"
}

& $py -m pip install --upgrade pip setuptools wheel

# --- 3. WhisperX + RecordingCraft --------------------------------------
Write-Host ""
Write-Host "Instalando WhisperX, pyannote y RecordingCraft..." -ForegroundColor Cyan
& $py -m pip install -e .
if ($LASTEXITCODE -ne 0) { throw "Fallo la instalacion de las dependencias." }

# --- 4. PyTorch con CUDA -----------------------------------------------
if ($Cpu) {
    Write-Host ""
    Write-Host "Modo CPU solicitado: se deja PyTorch tal cual." -ForegroundColor Yellow
} else {
    # Se reinstalan exactamente las versiones que ha fijado WhisperX, pero
    # tomandolas del indice CUDA. Las tres tienen que ir a la vez: mezclar
    # compilaciones CPU y CUDA rompe la carga de las librerias.
    $spec = & $py -c "import importlib.metadata as m;
names=['torch','torchaudio','torchvision'];
out=[]
for n in names:
    try: out.append(n+'=='+m.version(n).split('+')[0])
    except Exception: pass
print(' '.join(out))"
    $packages = $spec.Trim() -split '\s+' | Where-Object { $_ }

    if (-not $packages) {
        Write-Warning "No se encontro PyTorch instalado; se omite el paso CUDA."
    } else {
        Write-Host ""
        Write-Host "Reinstalando con CUDA: $($packages -join ', ')" -ForegroundColor Cyan
        $installed = $false
        foreach ($tag in $CudaTags) {
            Write-Host "  probando $tag..." -ForegroundColor DarkGray
            & $py -m pip install --force-reinstall --no-cache-dir @packages `
                --index-url "https://download.pytorch.org/whl/$tag"
            if ($LASTEXITCODE -eq 0) { $installed = $true; break }
            Write-Warning "  la rueda $tag no sirvio, probando la siguiente."
        }
        if (-not $installed) {
            Write-Warning "No se pudo instalar PyTorch con CUDA. Seguira funcionando en CPU."
        }
    }
}

# --- 5. ficheros de configuracion --------------------------------------
if (-not (Test-Path (Join-Path $root "config.toml"))) {
    Copy-Item (Join-Path $root "config.example.toml") (Join-Path $root "config.toml")
    Write-Host "Creado config.toml a partir del ejemplo." -ForegroundColor Green
}
if (-not (Test-Path (Join-Path $root ".env"))) {
    Copy-Item (Join-Path $root ".env.example") (Join-Path $root ".env")
    Write-Host "Creado .env: pon ahi tu HF_TOKEN para la diarizacion." -ForegroundColor Yellow
}

# --- 6. comprobacion ---------------------------------------------------
Write-Host ""
& $py -m recordingcraft doctor

Write-Host ""
Write-Host "Listo. Uso:" -ForegroundColor Cyan
Write-Host "  .\rc.cmd process        # procesa todo lo que haya en data\inbox"
Write-Host "  .\rc.cmd list"
Write-Host "  .\rc.cmd speakers <id> --clips"
