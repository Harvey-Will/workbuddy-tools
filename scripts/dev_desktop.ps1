# Start desktop dev: sidecar prerequisites + tauri dev
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$env:RUSTUP_HOME = Join-Path $root ".toolchain\rustup"
$env:CARGO_HOME = Join-Path $root ".toolchain\cargo"
$env:PATH = "$(Join-Path $env:CARGO_HOME 'bin');$env:PATH"

# VS env for MSVC link
$vswhere = "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
if (Test-Path $vswhere) {
  $vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
  if ($vs) {
    $vcvars = Join-Path $vs "VC\Auxiliary\Build\vcvars64.bat"
    if (Test-Path $vcvars) {
      cmd /c "`"$vcvars`" && set" | ForEach-Object {
        if ($_ -match "^([^=]+)=(.*)$") {
          [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
        }
      }
    }
  }
}

# Python deps
if (-not (Test-Path ".venv\Scripts\python.exe")) {
  python -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install -q -r requirements.txt

# UI deps
if (-not (Test-Path "ui\node_modules")) {
  Push-Location ui
  npm install
  Pop-Location
}

# Install tauri CLI locally
if (-not (Test-Path "node_modules\@tauri-apps\cli")) {
  npm install --no-save @tauri-apps/cli@2
}

npx tauri dev
