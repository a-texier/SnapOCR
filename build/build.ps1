# Build portable (onedir) de SnapOCR avec PyInstaller.
# Produit dist\SnapOCR\ : dossier a copier tel quel, lancable sans admin.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# Python a utiliser : $env:SNAPOCR_PYTHON, sinon celui du PATH.
$py = $env:SNAPOCR_PYTHON
if (-not $py) { $py = (Get-Command python -ErrorAction Stop).Source }
if (-not (Test-Path $py)) { throw "python introuvable: $py (definir SNAPOCR_PYTHON)" }
$envRoot = Split-Path -Parent $py
$condaBin = Join-Path $envRoot "Library\bin"

# Sous conda, les DLL runtime (ffi-8.dll pour _ctypes, etc.) sont dans
# Library\bin. On les expose a PyInstaller pour qu'il les embarque : sans ca
# l'exe plante au demarrage sur une machine sans conda (ImportError _ctypes).
# _ctypes.pyd (Anaconda 3.12) importe precisement 'ffi.dll', on prend les deux noms.
$extraBinaries = @()
if (Test-Path $condaBin) {
  $env:PATH = "$condaBin;" + $env:PATH
  foreach ($name in @("ffi.dll", "ffi-8.dll")) {
    $dll = Join-Path $condaBin $name
    if (Test-Path $dll) { $extraBinaries += @("--add-binary", "$dll;.") }
  }
}

# Verifie la presence des assets Tesseract avant de builder.
$tess = Join-Path $root "snapocr\resources\tesseract\tesseract.exe"
$eng  = Join-Path $root "snapocr\resources\tesseract\tessdata\eng.traineddata"
$fra  = Join-Path $root "snapocr\resources\tesseract\tessdata\fra.traineddata"
foreach ($f in @($tess, $eng, $fra)) {
  if (-not (Test-Path $f)) {
    throw "Asset manquant: $f. Lance build\fetch_assets.ps1 (voir docs\README.md)."
  }
}

# Nettoyage des sorties precedentes.
foreach ($d in @("build\pyi", "dist\SnapOCR")) {
  if (Test-Path $d) { Remove-Item -Recurse -Force $d }
}

& $py -m PyInstaller `
  --noconfirm --clean --windowed `
  --name SnapOCR `
  --icon "$root\snapocr\resources\icon.ico" `
  --workpath "build\pyi" `
  --distpath "dist" `
  --specpath "build" `
  --add-data "$root\snapocr\resources;resources" `
  @extraBinaries `
  --hidden-import win32com `
  --hidden-import win32com.client `
  --hidden-import win32timezone `
  "run_snapocr.py"

if ($LASTEXITCODE -ne 0) { throw "PyInstaller a echoue (code $LASTEXITCODE)" }

Write-Host ""
Write-Host "OK -> dist\SnapOCR\SnapOCR.exe" -ForegroundColor Green
Write-Host "Copie le dossier dist\SnapOCR sur le PC cible, lance SnapOCR.exe (sans admin)."
