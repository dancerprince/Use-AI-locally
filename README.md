# Offline AI

A local-first AI workbench. Chat with a model running **on your own machine** (Ollama, LM Studio,
llama.cpp, vLLM…) and extend it from the web UI with:

- **MCP servers** – any Model Context Protocol server over `stdio`, streamable HTTP or SSE
- **Connectors** – built-in sandboxed tools: local folder, SQLite, PostgreSQL (read-only), REST API, webhook
- **AI skills** – reusable instructions injected into the system prompt, with preferred tools

The sidebar shows a live status badge that pings the local model every 10 s (latency + installed models).

## Install & run (end users)

```bash
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/dancerprince/Use-AI-locally/main/scripts/install.sh | sh
# Windows (PowerShell)
irm https://raw.githubusercontent.com/dancerprince/Use-AI-locally/main/scripts/install.ps1 | iex

offline-ai          # starts the local server and opens the UI in your browser
```

Download models from the **📦 Models** page (or run `offline-ai models pull llama3.2:3b`). They're stored
on your machine, and chats and settings are kept in your user data folder (`offline-ai paths`).
See [docs/INSTALL.md](docs/INSTALL.md) for pipx/uv, standalone binaries, and other options.

Build the distributable wheel yourself with `make package`, then run `make install-local`.

## Quick start (development)

```bash
# 1. Local model
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.1:8b          # or qwen2.5:7b — pick a model that supports tool calling

# 2. App (needs uv + Node 20+)
make setup
make dev                         # API on :8000, UI on http://127.0.0.1:5173
```

Single-process mode: `make run` builds the UI and serves everything at http://127.0.0.1:8000.
Docker: `docker compose up --build`, then `docker compose exec ollama ollama pull llama3.1:8b`.

## Using it

| Page | What you can do |
|---|---|
| Chat | Stream replies, choose a model, toggle tool use, see each tool call and its result |
| MCP servers | Add, edit, enable/disable, test and reconnect servers; browse the tools they expose |
| Connectors | Add a folder, database, API or webhook; test the connection |
| Skills | Write markdown instructions, link preferred tools, enable/disable |
| Settings | Switch runtime (presets), base URL, default model, temperature, system prompt |

Example MCP server (stdio): command `npx`, args `-y`, `@modelcontextprotocol/server-filesystem`, `/home/me/docs`.

## Architecture

```
frontend (React + Vite + Tailwind)  ──/api──▶  backend (FastAPI)
                                                ├─ routers/        HTTP layer (validation, errors)
                                                ├─ services/
                                                │   ├─ orchestrator   skills → prompt, tool loop (bounded)
                                                │   ├─ mcp_manager    one task per server, auto-reconnect, keep-alive
                                                │   ├─ connectors     sandboxed adapters
                                                │   └─ repository     CRUD + secret encryption
                                                ├─ providers/      ollama, openai-compatible
                                                └─ SQLite (data/offline_ai.db)
```

Tool names exposed to the model: `mcp__<server>__<tool>` and `conn__<connector>__<tool>`.
Chat streams over SSE with these events: `session`, `delta`, `tool_call`, `tool_result`, `error`, `done`.

## Security model

- Binds to `127.0.0.1`. A Host-header allow-list blocks DNS-rebinding; CORS is limited to the dev UI.
- Optional bearer token (`OAI_API_TOKEN`); a warning is logged if you bind publicly without one.
- **stdio MCP**: the command must be on `OAI_MCP_STDIO_ALLOWED_COMMANDS`, and the user confirms it
  explicitly (`confirmed=true` / UI dialog). Child processes get a minimal environment.
- Secrets (MCP env/headers, connector headers/DSN, model API key) are encrypted with Fernet. API
  responses show them masked; sending the mask back keeps the stored value.
- Filesystem connector: resolves paths and blocks `..` and symlink escapes; read-only unless `allow_write`.
- SQL connectors: a single read-only statement. SQLite opens with `mode=ro`; Postgres runs in a
  read-only transaction with `statement_timeout`. Row caps apply to both.
- HTTP connector: paths must be relative to its base URL, methods are allow-listed, redirects are not
  followed, and `OAI_HTTP_ALLOWED_HOSTS` applies.
- Timeouts on every model, MCP and tool call. Tool output is truncated. The tool loop is capped by
  `OAI_MAX_TOOL_ROUNDS`, and the last round withholds tools so the model has to answer.
- Logs redact token- and key-like values.

## Extending

**New connector type**: subclass `ConnectorAdapter` in `backend/app/services/connectors.py`
(define `Config`, `secret_fields`, `local_tools()`, `call()`, `test()`), add it to `CONNECTOR_TYPES`,
then add a form definition in `frontend/src/pages/Connectors.tsx` (`CONNECTOR_FIELDS`).

**New model provider**: subclass `ModelProvider` in `backend/app/providers/` (implement `ping()` and
`chat_stream()`), register it in `PROVIDERS`, and add it to the `provider` literal in `schemas.py`.

## Development

```bash
make test     # pytest (incl. real MCP stdio end-to-end) + vitest
make lint     # ruff, mypy, eslint, tsc, prettier
```

Configuration: see `.env.example` (copy to `backend/.env`).
