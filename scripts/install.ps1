# Offline AI installer for Windows (PowerShell 5+).
#
#   irm <repo-raw-url>/scripts/install.ps1 | iex
#   .\install.ps1 -Source .\offline_ai-0.1.0-py3-none-any.whl
param([string]$Source = $(if ($env:OAI_SOURCE) { $env:OAI_SOURCE } else { "offline-ai" }))
$ErrorActionPreference = "Stop"

function Say($m)  { Write-Host "==> $m" -ForegroundColor Green }
function Warn($m) { Write-Host "!!  $m" -ForegroundColor Yellow }

# 1. uv (brings its own Python)
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Say "Installing uv (Python package manager) for the current user"
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

# 2. The app
Say "Installing Offline AI from: $Source"
uv tool install --force --python 3.12 $Source
try { uv tool update-shell | Out-Null } catch {}

# 3. Ollama
$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama -and -not (Test-Path "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe")) {
    Warn "Ollama (the local model runtime) is not installed."
    $ans = Read-Host "Install Ollama now with winget? [y/N]"
    if ($ans -match '^(y|yes)$' -and (Get-Command winget -ErrorAction SilentlyContinue)) {
        winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
    } else {
        Warn "Install it later from https://ollama.com/download/windows"
    }
} else { Say "Ollama found" }

Say "Done! Open a new terminal and run:"
Write-Host "`n    offline-ai            # opens the app in your browser"
Write-Host "    offline-ai doctor     # check your setup`n"
