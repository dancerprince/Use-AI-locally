"""``offline-ai`` command-line entry point.

offline-ai                 # start server and open the browser
offline-ai start --port 9000 --no-browser
offline-ai doctor
offline-ai models list | pull <name> | rm <name>
offline-ai paths | version
"""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Annotated

import httpx
import typer

from . import __version__
from .paths import app_paths

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    help="Offline AI: local-first AI workbench running in your browser.",
)
models_app = typer.Typer(help="Manage offline models (requires Ollama).", no_args_is_help=True)
app.add_typer(models_app, name="models")

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def port_free(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def pick_port(host: str, start: int, attempts: int = 50) -> int:
    for p in range(start, min(start + attempts, 65536)):
        if port_free(host, p):
            return p
    raise RuntimeError(f"No free port found in {start}-{start + attempts - 1}")


def _browser_url(host: str, port: int) -> str:
    shown = "127.0.0.1" if host in {"0.0.0.0", "::"} else host  # noqa: S104
    if ":" in shown:
        shown = f"[{shown}]"
    return f"http://{shown}:{port}"


def _open_when_ready(url: str, open_browser: bool, timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{url}/api/health", timeout=1.0).status_code < 500:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    typer.secho(f"\n  Offline AI is running at {url}\n  Press Ctrl+C to stop.\n", fg="green")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception as exc:  # pragma: no cover - headless systems
            typer.echo(f"  (Could not open a browser: {exc}; open the URL manually.)")


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        ctx.invoke(start)


@app.command()
def start(
    port: Annotated[int | None, typer.Option(help="Port (default 8000).")] = None,
    host: Annotated[str | None, typer.Option(help="Bind address (default 127.0.0.1).")] = None,
    no_browser: Annotated[bool, typer.Option("--no-browser", help="Don't open a browser.")] = False,
    models_dir: Annotated[
        Path | None, typer.Option(help="Where Ollama should store downloaded models.")
    ] = None,
) -> None:
    """Start the server and open the UI in your browser."""
    import uvicorn

    from .config import Settings
    from .main import create_app

    overrides: dict[str, object] = {}
    if host:
        overrides["host"] = host
    if models_dir:
        overrides["models_dir"] = models_dir.expanduser().resolve()
    s = Settings(**overrides)  # type: ignore[arg-type]
    chosen = port or s.port
    if not port_free(s.host, chosen):
        if not s.auto_port:
            typer.secho(f"Port {chosen} is already in use.", fg="red", err=True)
            raise typer.Exit(1)
        chosen = pick_port(s.host, chosen + 1)
        typer.secho(f"Port in use, using {chosen} instead.", fg="yellow")
    s = s.model_copy(update={"port": chosen})
    if s.host not in LOCAL_HOSTS and not s.api_token:
        typer.secho(
            f"WARNING: binding to {s.host} without OAI_API_TOKEN exposes this app to your network!",
            fg="red",
            err=True,
        )
    url = _browser_url(s.host, s.port)
    threading.Thread(
        target=_open_when_ready, args=(url, s.open_browser and not no_browser), daemon=True
    ).start()
    uvicorn.run(create_app(s), host=s.host, port=s.port, log_config=None)


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(f"offline-ai {__version__}")


@app.command()
def paths() -> None:
    """Show where data, config and logs are stored."""
    p = app_paths()
    typer.echo(f"data:   {p.data}\nconfig: {p.config_file}\nlogs:   {p.logs}")


@app.command()
def doctor() -> None:
    """Check that this system can run Offline AI."""
    from .config import Settings
    from .services.runtime import RuntimeManager

    s = Settings()
    ok = True

    def line(good: bool, label: str, detail: str = "") -> None:
        nonlocal ok
        ok = ok and good
        mark = typer.style("✔" if good else "✘", fg="green" if good else "red")
        typer.echo(f" {mark} {label}{': ' + detail if detail else ''}")

    py = sys.version_info
    line(py >= (3, 11), "Python", f"{py.major}.{py.minor}.{py.micro}")
    line(True, "Platform", f"{platform.system()} {platform.machine()}")
    try:
        s.data_dir.mkdir(parents=True, exist_ok=True)
        line(os.access(s.data_dir, os.W_OK), "Data directory", str(s.data_dir))
    except OSError as exc:
        line(False, "Data directory", str(exc))
    free_gb = shutil.disk_usage(_existing(s.models_dir or s.data_dir)).free / 1024**3
    line(free_gb >= 5, "Free disk", f"{free_gb:.1f} GB (models need 2-8 GB each)")
    ram = _ram_gb()
    if ram:
        line(ram >= 8, "RAM", f"{ram:.1f} GB (8 GB+ recommended)")
    st = asyncio.run(RuntimeManager(s.model_base_url, s.models_dir).status())
    line(st.installed, "Ollama installed", st.path or f"not found. Install: {st.install_hint}")
    line(
        st.running,
        "Ollama running",
        f"v{st.version} at {s.model_base_url}" if st.running else "not reachable",
    )
    if not ok:
        raise typer.Exit(1)


def _existing(p: Path) -> Path:
    while not p.exists() and p != p.parent:
        p = p.parent
    return p


def _ram_gb() -> float | None:
    try:
        if hasattr(os, "sysconf") and "SC_PHYS_PAGES" in os.sysconf_names:
            return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 1024**3
    except (ValueError, OSError):
        pass
    return None


# --- models -------------------------------------------------------------------
def _manager():  # type: ignore[no-untyped-def]
    from .config import Settings
    from .services.model_manager import ModelManager

    s = Settings()
    return ModelManager(s.model_base_url, models_dir=s.models_dir, data_dir=s.data_dir)


def _run(coro):  # type: ignore[no-untyped-def]
    from .errors import AppError

    try:
        return asyncio.run(coro)
    except AppError as exc:
        typer.secho(exc.message, fg="red", err=True)
        raise typer.Exit(1) from exc


@models_app.command("list")
def models_list() -> None:
    """List installed models."""
    rows = _run(_manager().list_installed())
    if not rows:
        typer.echo("No models installed. Try: offline-ai models pull llama3.2:3b")
    for m in rows:
        typer.echo(
            f"{m['name']:<40} {m['size'] / 1024**3:6.1f} GB  {m.get('parameter_size') or ''}"
        )


@models_app.command("pull")
def models_pull(name: str) -> None:
    """Download a model with a progress bar."""

    async def go() -> int:
        mgr = _manager()
        job = mgr.start_pull(name)
        last = ""
        async for snap in mgr.events(job.id):
            if snap["total"]:
                bar = "#" * int(snap["percent"] / 4)
                msg = f"\r{snap['status'][:30]:<30} [{bar:<25}] {snap['percent']:5.1f}%"
            else:
                msg = f"\r{snap['status'][:60]:<60}"
            if msg != last:
                typer.echo(msg, nl=False)
                last = msg
        typer.echo("")
        if job.error:
            typer.secho(f"Failed: {job.error}", fg="red", err=True)
            return 1
        typer.secho(f"Downloaded {job.model}", fg="green")
        return 0

    code = _run(go())
    raise typer.Exit(code)


@models_app.command("rm")
def models_rm(name: str) -> None:
    """Delete an installed model."""
    _run(_manager().delete(name))
    typer.echo(f"Deleted {name}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
