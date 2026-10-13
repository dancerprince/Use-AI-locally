#!/usr/bin/env sh
# Offline AI installer for Linux and macOS.
#
#   curl -fsSL <repo-raw-url>/scripts/install.sh | sh
#   sh install.sh ./offline_ai-0.1.0-py3-none-any.whl     # install a local wheel
#
# Env: OAI_SOURCE overrides what is installed (wheel path, git URL, or PyPI name).
set -eu

SOURCE="${1:-${OAI_SOURCE:-offline-ai}}"

say()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }
ask()  {
  # Read from the terminal even when piped through `curl | sh`.
  printf '%s [y/N] ' "$1"
  if [ -r /dev/tty ]; then read -r ans </dev/tty; else ans=n; fi
  case "$ans" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

# 1. uv (manages its own Python, so no system Python 3.11 is required)
if ! command -v uv >/dev/null 2>&1; then
  say "Installing uv (Python package manager) into your home directory"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"; export PATH
fi

# 2. The app itself, as an isolated user-level tool
say "Installing Offline AI from: $SOURCE"
uv tool install --force --python 3.12 "$SOURCE"
uv tool update-shell >/dev/null 2>&1 || true

# 3. Ollama (the local model runtime)
if command -v ollama >/dev/null 2>&1 || [ -x /Applications/Ollama.app/Contents/Resources/ollama ]; then
  say "Ollama found"
else
  warn "Ollama (the local model runtime) is not installed."
  case "$(uname -s)" in
    Darwin)
      if command -v brew >/dev/null 2>&1 && ask "Install Ollama with Homebrew now?"; then
        brew install ollama
      else
        warn "Install it later from https://ollama.com/download/mac"
      fi ;;
    Linux)
      if ask "Install Ollama now? (runs the official installer, which uses sudo)"; then
        curl -fsSL https://ollama.com/install.sh | sh
      else
        warn "Install it later with: curl -fsSL https://ollama.com/install.sh | sh"
      fi ;;
  esac
fi

say "Done! Open a new terminal and run:"
printf '\n    offline-ai            # opens the app in your browser\n'
printf '    offline-ai doctor     # check your setup\n\n'
