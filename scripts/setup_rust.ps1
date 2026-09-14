# Setup Rust toolchain into project-local .toolchain (Windows)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$tool = Join-Path $root ".toolchain"
$env:RUSTUP_HOME = Join-Path $tool "rustup"
$env:CARGO_HOME = Join-Path $tool "cargo"
New-Item -ItemType Directory -Force -Path $tool | Out-Null
$rustup = Join-Path $tool "rustup-init.exe"
if (-not (Test-Path $rustup)) {
  Invoke-WebRequest -Uri "https://win.rustup.rs/x86_64" -OutFile $rustup
}
& $rustup -y --default-toolchain stable --profile minimal --no-modify-path
Write-Host "CARGO_HOME=$env:CARGO_HOME"
& (Join-Path $env:CARGO_HOME "bin\cargo.exe") -V
