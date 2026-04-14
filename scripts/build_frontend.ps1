# scripts/build_frontend.ps1
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$frontendDir = Join-Path $repoRoot "frontend"
$distDir = Join-Path $frontendDir "dist"
$staticDir = Join-Path $repoRoot "static"

Write-Host "== Ticketera: build frontend -> copy to /static ==" -ForegroundColor Cyan

if (!(Test-Path $frontendDir)) {
  throw "No existe la carpeta 'frontend' en: $frontendDir"
}

if (!(Test-Path (Join-Path $frontendDir "package.json"))) {
  throw "No existe 'frontend/package.json'. Asegurate de estar en el repo correcto."
}

Push-Location $frontendDir

Write-Host "-> npm install (si hace falta)..." -ForegroundColor Yellow
npm install

Write-Host "-> npm run build..." -ForegroundColor Yellow
npm run build

Pop-Location

if (!(Test-Path (Join-Path $distDir "index.html"))) {
  throw "Build falló: no se encontró dist/index.html en $distDir"
}

# Validación rápida: asegurar que existan assets
$assetsDir = Join-Path $distDir "assets"
if (!(Test-Path $assetsDir)) {
  throw "Build sospechoso: no existe dist/assets/. Revisá Vite build."
}

# Copiar a static (limpio)
Write-Host "-> limpiando /static..." -ForegroundColor Yellow
if (Test-Path $staticDir) { Remove-Item $staticDir -Recurse -Force }
New-Item -ItemType Directory -Path $staticDir | Out-Null

Write-Host "-> copiando dist -> static..." -ForegroundColor Yellow
Copy-Item (Join-Path $distDir "*") $staticDir -Recurse -Force

# Validación post-copia
if (!(Test-Path (Join-Path $staticDir "index.html"))) {
  throw "Copia falló: no se encontró static/index.html"
}
if (!(Test-Path (Join-Path $staticDir "assets"))) {
  throw "Copia falló: no se encontró static/assets/"
}

Write-Host "✅ Listo. 'static/' actualizado. Ya podés commitear y deployar." -ForegroundColor Green
Write-Host "Tip: chequeá que tu backend tenga app.mount('/', StaticFiles(directory='static', html=True))" -ForegroundColor DarkGray
