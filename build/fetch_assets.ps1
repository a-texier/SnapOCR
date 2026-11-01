# Recupere les assets Tesseract (binaire + langues) dans snapocr\resources\tesseract\.
# A lancer une fois sur une machine avec acces reseau (pas le PC entreprise).
# Les modeles viennent de tessdata_fast ; le binaire portable est copie depuis
# une install msys2/ucrt64 si presente (avec toutes ses DLL).

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$dest = Join-Path $root "snapocr\resources\tesseract"
$tessdata = Join-Path $dest "tessdata"
New-Item -ItemType Directory -Force -Path $tessdata | Out-Null

# 1) Modeles de langue (fast, legers).
$base = "https://github.com/tesseract-ocr/tessdata_fast/raw/main"
foreach ($l in @("eng", "fra")) {
  $out = Join-Path $tessdata "$l.traineddata"
  Write-Host "Telechargement $l.traineddata ..."
  Invoke-WebRequest -Uri "$base/$l.traineddata" -OutFile $out -UseBasicParsing
}

# 2) Binaire portable + DLL + configs, depuis msys2/ucrt64.
$msys = if ($env:MSYS2_ROOT) { $env:MSYS2_ROOT } else { "C:\msys64" }
$src = "$msys\ucrt64\bin"
$share = "$msys\ucrt64\share\tessdata"
$ldd = "$msys\usr\bin\ldd.exe"
if ((Test-Path "$src\tesseract.exe") -and (Test-Path $ldd)) {
  Copy-Item "$src\tesseract.exe" $dest -Force
  # Ferme les dependances DLL via ldd.
  $dlls = & $ldd "$src\tesseract.exe" 2>$null |
    Select-String -Pattern "ucrt64" |
    ForEach-Object { ($_ -split "\s+")[0].Trim() } |
    Where-Object { $_ -like "*.dll" } | Sort-Object -Unique
  foreach ($name in $dlls) {
    if (Test-Path "$src\$name") { Copy-Item "$src\$name" $dest -Force }
  }
  # Fichiers de config (tsv, hocr, ...) requis pour la sortie TSV.
  if (Test-Path "$share\configs") { Copy-Item "$share\configs" $tessdata -Recurse -Force }
  if (Test-Path "$share\tessconfigs") { Copy-Item "$share\tessconfigs" $tessdata -Recurse -Force }
  Write-Host "Binaire Tesseract portable copie depuis msys2 ($($dlls.Count) DLL)." -ForegroundColor Green
} else {
  Write-Warning "msys2/ucrt64 introuvable. Fournis manuellement tesseract.exe + ses DLL"
  Write-Warning "et le dossier tessdata\configs\ dans $dest (voir docs\README.md)."
}
