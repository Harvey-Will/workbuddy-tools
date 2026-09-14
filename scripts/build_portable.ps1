# Build single-file portable exe (sidecar embedded, extracted to temp on launch)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Get-Process workbuddy-tools,sidecar,api-sidecar -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 400

# Ensure sidecar exists (embedded via include_bytes!)
$sidecarSrc = Join-Path $root "src-tauri\binaries\sidecar-x86_64-pc-windows-msvc.exe"
if (-not (Test-Path $sidecarSrc)) {
  Write-Host "Building sidecar..."
  powershell -ExecutionPolicy Bypass -File (Join-Path $root "scripts\build_sidecar.ps1")
}

$env:RUSTUP_HOME = Join-Path $root ".toolchain\rustup"
$env:CARGO_HOME = Join-Path $root ".toolchain\cargo"
$env:PATH = "$(Join-Path $env:CARGO_HOME 'bin');$env:PATH"

$vswhere = "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
$vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
$vcvars = Join-Path $vs "VC\Auxiliary\Build\vcvars64.bat"

# Compile release + UI embed (no NSIS)
cmd /c "`"$vcvars`" && cd /d `"$root`" && npx tauri build --no-bundle"
if ($LASTEXITCODE -ne 0) { throw "tauri build --no-bundle failed" }

$portable = Join-Path $root "release\WorkBuddyTools-portable"
if (Test-Path $portable) { Remove-Item $portable -Recurse -Force }
New-Item -ItemType Directory -Force -Path $portable | Out-Null

Copy-Item (Join-Path $root "src-tauri\target\release\workbuddy-tools.exe") $portable -Force
# sidecar is embedded; do not ship a second exe

# zip
$zip = Join-Path $root "release\WorkBuddyTools-portable-win64.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $portable "*") -DestinationPath $zip -Force

Write-Host "PORTABLE_DIR=$portable"
Write-Host "PORTABLE_ZIP=$zip"
Get-ChildItem $portable | Select-Object Name, @{n='MB';e={[math]::Round($_.Length/1MB,2)}}
Get-Item $zip | Select-Object Name, @{n='MB';e={[math]::Round($_.Length/1MB,2)}}
