"""Detect and (optionally) start the local Ollama runtime."""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)

INSTALL_HINTS = {
    "Linux": "curl -fsSL https://ollama.com/install.sh | sh",
    "Darwin": "brew install ollama   (or download from https://ollama.com/download/mac)",
    "Windows": "winget install Ollama.Ollama   (or download from https://ollama.com/download/windows)",
}


def install_hint() -> str:
    return INSTALL_HINTS.get(platform.system(), "See https://ollama.com/download")


def find_ollama() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    candidates = [
        Path("/usr/local/bin/ollama"),
        Path("/usr/bin/ollama"),
        Path("/opt/homebrew/bin/ollama"),
        Path("/Applications/Ollama.app/Contents/Resources/ollama"),
    ]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Programs" / "Ollama" / "ollama.exe")
    return next((str(p) for p in candidates if p.is_file()), None)


def is_local_url(url: str) -> bool:
    return (urlsplit(url).hostname or "") in {"localhost", "127.0.0.1", "::1"}


@dataclass
class RuntimeStatus:
    installed: bool
    running: bool
    version: str | None
    path: str | None
    managed: bool
    install_hint: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RuntimeManager:
    """Starts ``ollama serve`` when installed but not running; stops only what it started."""

    def __init__(self, base_url: str, models_dir: Path | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.models_dir = models_dir
        self._proc: subprocess.Popen[bytes] | None = None

    async def version(self) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=2.0) as c:
                r = await c.get(f"{self.base_url}/api/version")
                r.raise_for_status()
                return str(r.json().get("version") or "unknown")
        except (httpx.HTTPError, ValueError):
            return None

    async def status(self) -> RuntimeStatus:
        path = find_ollama()
        version = await self.version()
        return RuntimeStatus(
            installed=path is not None or version is not None,
            running=version is not None,
            version=version,
            path=path,
            managed=self._proc is not None and self._proc.poll() is None,
            install_hint=install_hint(),
        )

    async def ensure_running(self, timeout_s: float = 15.0) -> RuntimeStatus:
        st = await self.status()
        if st.running or not st.path or not is_local_url(self.base_url):
            return st
        env = dict(os.environ)
        env["OLLAMA_HOST"] = urlsplit(self.base_url).netloc
        if self.models_dir:
            self.models_dir.mkdir(parents=True, exist_ok=True)
            env["OLLAMA_MODELS"] = str(self.models_dir)
        log.info("Starting Ollama runtime: %s serve", st.path)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._proc = subprocess.Popen(  # noqa: S603, ASYNC220 - fixed executable, non-blocking spawn
            [st.path, "serve"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while loop.time() < deadline:
            if self._proc.poll() is not None:
                log.warning("Ollama exited early with code %s", self._proc.returncode)
                self._proc = None
                break
            if await self.version():
                break
            await asyncio.sleep(0.4)
        return await self.status()

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            log.info("Stopping managed Ollama runtime")
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover
                self._proc.kill()
        self._proc = None
