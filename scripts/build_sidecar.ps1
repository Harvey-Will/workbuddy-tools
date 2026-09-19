# Build Python API sidecar for Tauri bundling (Windows x64)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
  python -m venv .venv
  $py = Join-Path $root ".venv\Scripts\python.exe"
}
& $py -m pip install -q -r requirements.txt pyinstaller

$dist = Join-Path $root "src-tauri\binaries"
New-Item -ItemType Directory -Force -Path $dist | Out-Null

# Clean previous
Remove-Item (Join-Path $root "build\sidecar") -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $root "dist\sidecar") -Recurse -Force -ErrorAction SilentlyContinue

& $py -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --name sidecar `
  --paths $root `
  --hidden-import backend.app `
  --hidden-import core.accounts `
  --hidden-import core.editions `
  --hidden-import core.migrate `
  --hidden-import core.tokens `
  --hidden-import core.models `
  --hidden-import core.sessions `
  --hidden-import uvicorn.logging `
  --hidden-import uvicorn.loops.auto `
  --hidden-import uvicorn.loops.asyncio `
  --hidden-import uvicorn.protocols.http.auto `
  --hidden-import uvicorn.protocols.websockets.auto `
  --hidden-import uvicorn.lifespan.on `
  --collect-submodules backend `
  --collect-submodules core `
  --distpath (Join-Path $root "dist\sidecar") `
  --workpath (Join-Path $root "build\sidecar") `
  (Join-Path $root "scripts\sidecar_entry.py")

$built = Join-Path $root "dist\sidecar\sidecar.exe"
if (-not (Test-Path $built)) { throw "sidecar build missing: $built" }

# Tauri externalBin naming: <name>-<target-triple>.exe
$target = "x86_64-pc-windows-msvc"
Copy-Item $built (Join-Path $dist "sidecar-$target.exe") -Force
Write-Host "sidecar -> $dist\sidecar-$target.exe"
Get-Item (Join-Path $dist "sidecar-$target.exe") | Select-Object FullName, @{n='MB';e={[math]::Round($_.Length/1MB,1)}}
