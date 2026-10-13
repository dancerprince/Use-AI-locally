"""Download, list, inspect and delete local models via the Ollama HTTP API."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import httpx

from ..errors import AppError

log = logging.getLogger(__name__)

NAME_RE = re.compile(r"^[a-z0-9._/-]+(:[a-z0-9._-]+)?$")
MAX_NAME = 128
GB = 1024**3


def validate_name(name: str) -> str:
    name = name.strip().lower()
    if not name or len(name) > MAX_NAME or not NAME_RE.match(name) or ".." in name:
        raise AppError(f"Invalid model name '{name[:MAX_NAME]}'", code="invalid_model_name")
    return name


def load_catalog() -> list[dict[str, Any]]:
    text = resources.files("app").joinpath("catalog.json").read_text(encoding="utf-8")
    data: list[dict[str, Any]] = json.loads(text)
    return data


@dataclass
class PullJob:
    id: str
    model: str
    status: str = "queued"
    completed: int = 0
    total: int = 0
    done: bool = False
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    task: asyncio.Task[None] | None = field(default=None, repr=False)
    changed: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    @property
    def percent(self) -> float:
        return round(self.completed * 100 / self.total, 1) if self.total else 0.0

    def snapshot(self) -> dict[str, Any]:
        keys = ("id", "model", "status", "completed", "total", "done", "error", "started_at")
        d: dict[str, Any] = {k: getattr(self, k) for k in keys}
        d["percent"] = self.percent
        return d

    def _notify(self) -> None:
        self.changed.set()


class ModelManager:
    def __init__(
        self,
        base_url: str,
        *,
        models_dir: Path | None = None,
        data_dir: Path | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.models_dir = models_dir
        self.data_dir = data_dir
        self.timeout_s = timeout_s
        self.jobs: dict[str, PullJob] = {}

    def _client(self, timeout: float | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, timeout=timeout or self.timeout_s)

    async def _call(self, method: str, path: str, **kw: Any) -> httpx.Response:
        try:
            async with self._client() as c:
                r = await c.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise AppError(
                f"Model runtime unreachable at {self.base_url}: {type(exc).__name__}",
                code="runtime_offline",
                status=503,
            ) from exc
        if r.status_code == 404:
            raise AppError("Model not found", code="not_found", status=404)
        if r.is_error:
            raise AppError(f"Runtime error: {r.text[:300]}", code="runtime_error", status=502)
        return r

    # --- queries ----------------------------------------------------------------
    async def list_installed(self) -> list[dict[str, Any]]:
        r = await self._call("GET", "/api/tags")
        out = []
        for m in r.json().get("models", []):
            det = m.get("details") or {}
            out.append(
                {
                    "name": m.get("name") or m.get("model"),
                    "size": int(m.get("size") or 0),
                    "modified_at": m.get("modified_at"),
                    "family": det.get("family"),
                    "parameter_size": det.get("parameter_size"),
                    "quantization": det.get("quantization_level"),
                }
            )
        return out

    async def show(self, name: str) -> dict[str, Any]:
        name = validate_name(name)
        r = await self._call("POST", "/api/show", json={"model": name})
        body = r.json()
        info = body.get("model_info") or {}
        ctx = next((v for k, v in info.items() if k.endswith(".context_length")), None)
        caps = body.get("capabilities") or []
        template = body.get("template") or ""
        return {
            "name": name,
            "details": body.get("details") or {},
            "context_length": ctx,
            "capabilities": caps,
            "supports_tools": "tools" in caps or ".Tools" in template,
        }

    async def delete(self, name: str) -> None:
        name = validate_name(name)
        await self._call("DELETE", "/api/delete", json={"model": name})

    async def catalog(self) -> list[dict[str, Any]]:
        try:
            installed = {m["name"] for m in await self.list_installed()}
        except AppError:
            installed = set()
        cat = load_catalog()
        for entry in cat:
            n = entry["name"]
            entry["installed"] = n in installed or f"{n}:latest" in installed
        return cat

    # --- downloads --------------------------------------------------------------
    def _check_disk(self, name: str) -> None:
        size = next((e.get("size_gb") for e in load_catalog() if e["name"] == name), None)
        target = self.models_dir or self.data_dir or Path.home()
        while not target.exists() and target != target.parent:
            target = target.parent
        free = shutil.disk_usage(target).free
        if size and free < size * GB * 1.1:
            raise AppError(
                f"Not enough disk space for {name}: need ~{size:.1f} GB, {free / GB:.1f} GB free",
                code="insufficient_disk",
                status=507,
            )

    def start_pull(self, name: str) -> PullJob:
        name = validate_name(name)
        for job in self.jobs.values():
            if job.model == name and not job.done:
                return job  # de-duplicate concurrent pulls
        self._check_disk(name)
        job = PullJob(id=uuid.uuid4().hex, model=name)
        self.jobs[job.id] = job
        job.task = asyncio.create_task(self._run_pull(job))
        return job

    async def _run_pull(self, job: PullJob) -> None:
        try:
            async with (
                httpx.AsyncClient(
                    base_url=self.base_url, timeout=httpx.Timeout(30, read=None)
                ) as c,
                c.stream("POST", "/api/pull", json={"model": job.model, "stream": True}) as r,
            ):
                if r.is_error:
                    body = (await r.aread()).decode(errors="replace")
                    raise RuntimeError(body[:300] or f"HTTP {r.status_code}")
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    evt = json.loads(line)
                    if evt.get("error"):
                        raise RuntimeError(evt["error"])
                    job.status = evt.get("status", job.status)
                    if evt.get("total"):
                        job.total = int(evt["total"])
                        job.completed = int(evt.get("completed") or 0)
                    job._notify()
            job.status = "success"
        except asyncio.CancelledError:
            job.status, job.error = "cancelled", "Cancelled by user"
        except httpx.HTTPError as exc:
            job.status, job.error = "error", f"Runtime unreachable: {type(exc).__name__}"
        except Exception as exc:
            job.status, job.error = "error", str(exc)
        finally:
            job.done = True
            job._notify()

    def get_job(self, job_id: str) -> PullJob:
        job = self.jobs.get(job_id)
        if not job:
            raise AppError("Download job not found", code="not_found", status=404)
        return job

    def cancel(self, job_id: str) -> PullJob:
        job = self.get_job(job_id)
        if job.task and not job.done:
            job.task.cancel()
        return job

    async def events(self, job_id: str) -> AsyncIterator[dict[str, Any]]:
        job = self.get_job(job_id)
        while True:
            job.changed.clear()
            yield job.snapshot()
            if job.done:
                return
            try:
                await asyncio.wait_for(job.changed.wait(), timeout=15)
            except TimeoutError:
                pass  # heartbeat: re-send current snapshot

    async def shutdown(self) -> None:
        for job in self.jobs.values():
            if job.task and not job.done:
                job.task.cancel()
