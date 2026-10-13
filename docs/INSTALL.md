# Installing Offline AI

Offline AI runs entirely on your own computer. You start it with one command, and it opens in your browser.

## 1. Install

### Option A: one-line installer (recommended)

**Linux / macOS**
```sh
curl -fsSL https://raw.githubusercontent.com/<org>/offline-ai/main/scripts/install.sh | sh
```

**Windows (PowerShell)**
```powershell
irm https://raw.githubusercontent.com/<org>/offline-ai/main/scripts/install.ps1 | iex
```

The installer:
1. installs [`uv`](https://docs.astral.sh/uv/) for your user if it's missing. `uv` brings its own Python, so you don't need to install Python yourself.
2. installs Offline AI as an isolated command-line tool.
3. checks for [Ollama](https://ollama.com) and asks before installing it.

To install from a downloaded wheel instead: `sh install.sh ./offline_ai-0.1.0-py3-none-any.whl`.

### Option B: pipx / uv (Python 3.11+)
```sh
uv tool install offline-ai                 # or: pipx install offline-ai
uv tool install ./offline_ai-0.1.0-py3-none-any.whl
uv tool install "git+https://github.com/<org>/offline-ai#subdirectory=backend"  # needs a pre-built UI
```

### Option C: standalone binary
Download `offline-ai-<OS>.tar.gz` / `.zip` from the Releases page, extract it, and run `offline-ai/offline-ai`. Python isn't needed.

### Option D: Docker
`docker compose up` (see the main README).

## 2. Install the model runtime (Ollama)
| OS      | Command |
|---------|---------|
| Linux   | `curl -fsSL https://ollama.com/install.sh \| sh` |
| macOS   | `brew install ollama` or download it from ollama.com |
| Windows | `winget install Ollama.Ollama` |

If Ollama is installed but not running, Offline AI starts `ollama serve` for you and stops it again when the app quits.

## 3. Run
```sh
offline-ai                       # starts the app and opens http://127.0.0.1:8000
offline-ai start --port 9000 --no-browser
offline-ai start --models-dir /big/disk/models
offline-ai doctor                # checks Python, disk, RAM and Ollama
offline-ai models pull llama3.2:3b
offline-ai models list
offline-ai models rm llama3.2:3b
offline-ai paths                 # shows where your data is stored
```
If port 8000 is busy, the next free port is used. The URL is always printed, so headless machines and SSH sessions work too.

## 4. Download models
Open **📦 Models** in the sidebar. You can:
- pick a recommended model and click **Download** (shows live progress, can be cancelled)
- type the name of any model from [ollama.com/library](https://ollama.com/library)
- set a default model or delete models you no longer need

Models are stored on your machine: in Ollama's model folder (`~/.ollama/models` by default), or in the folder set with `--models-dir` / `OAI_MODELS_DIR`.

## Where your data lives
| OS      | App data (chats, settings, encryption key) |
|---------|------|
| Linux   | `~/.local/share/offline-ai` |
| macOS   | `~/Library/Application Support/offline-ai` |
| Windows | `%LOCALAPPDATA%\offline-ai` |

Settings go in `config.env` in the config folder (`offline-ai paths` shows where). Set `OAI_HOME=/some/dir` to keep everything in one folder. The data folder can only be read by your user account (`0700`), and so can the key file (`0600`).

## Uninstall
```sh
uv tool uninstall offline-ai     # or: pipx uninstall offline-ai
```
Your data folder is not touched. Delete it yourself if you want it gone.
