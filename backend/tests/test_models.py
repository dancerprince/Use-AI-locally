from __future__ import annotations

import json
import time

import httpx
import pytest
import respx

from app.services.model_manager import validate_name

from .conftest import parse_sse

OLLAMA = "http://localhost:11434"


@pytest.fixture
def ollama():
    with respx.mock(base_url=OLLAMA, assert_all_called=False) as mock:
        mock.get("/api/version").respond(json={"version": "0.5.0"})
        mock.get("/api/tags").respond(
            json={
                "models": [
                    {
                        "name": "llama3.2:3b",
                        "size": 2_000_000_000,
                        "modified_at": "2025-01-01T00:00:00Z",
                        "details": {"family": "llama", "parameter_size": "3.2B"},
                    }
                ]
            }
        )
        yield mock


def test_list_and_catalog(client, ollama):
    r = client.get("/api/models")
    assert r.status_code == 200
    assert r.json()[0]["name"] == "llama3.2:3b"
    cat = client.get("/api/models/catalog").json()
    by_name = {c["name"]: c for c in cat}
    assert by_name["llama3.2:3b"]["installed"] is True
    assert by_name["qwen2.5:7b"]["installed"] is False


def test_runtime_status(client, ollama):
    r = client.get("/api/health/runtime").json()
    assert r["running"] is True and r["version"] == "0.5.0"


def test_pull_progress(client, ollama):
    lines = [
        {"status": "pulling manifest"},
        {"status": "downloading", "total": 100, "completed": 50},
        {"status": "downloading", "total": 100, "completed": 100},
        {"status": "success"},
    ]
    body = "\n".join(json.dumps(x) for x in lines) + "\n"
    ollama.post("/api/pull").respond(text=body)
    r = client.post("/api/models/pull", json={"name": "phi4-mini"})
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    events = parse_sse(client.get(f"/api/models/pull/{job_id}/events").text)
    last = events[-1][1]
    assert last["done"] is True and last["status"] == "success" and last["error"] is None


def test_pull_error_reported(client, ollama):
    ollama.post("/api/pull").respond(
        text=json.dumps({"error": "pull model manifest: file does not exist"})
    )
    job_id = client.post("/api/models/pull", json={"name": "nope:1"}).json()["job_id"]
    last = parse_sse(client.get(f"/api/models/pull/{job_id}/events").text)[-1][1]
    assert last["status"] == "error" and "does not exist" in last["error"]


def test_cancel_pull(client, ollama):
    async def slow(_req):
        import asyncio

        await asyncio.sleep(5)
        return httpx.Response(200, text="")

    ollama.post("/api/pull").mock(side_effect=slow)
    job_id = client.post("/api/models/pull", json={"name": "qwen2.5:7b"}).json()["job_id"]
    client.delete(f"/api/models/pull/{job_id}")
    deadline = time.time() + 3
    snap = {}
    while time.time() < deadline:
        snap = next(j for j in client.get("/api/models/pulls").json() if j["id"] == job_id)
        if snap["done"]:
            break
        time.sleep(0.05)
    assert snap["status"] == "cancelled"


def test_delete_and_show(client, ollama):
    ollama.delete("/api/delete").respond(200)
    assert client.delete("/api/models/llama3.2:3b").status_code == 204
    ollama.post("/api/show").respond(
        json={"capabilities": ["completion", "tools"], "model_info": {"llama.context_length": 8192}}
    )
    info = client.get("/api/models/llama3.2:3b").json()
    assert info["supports_tools"] is True and info["context_length"] == 8192


@pytest.mark.parametrize("bad", ["", "a b", "../etc", "x;rm", "A" * 200, "foo:bar:baz"])
def test_invalid_names(bad, client, ollama):
    r = client.post("/api/models/pull", json={"name": bad or " "})
    assert r.status_code in (400, 422)


def test_validate_name_normalises():
    assert validate_name(" Llama3.2:3B ") == "llama3.2:3b"


def test_offline_runtime(client):
    with respx.mock(base_url=OLLAMA) as mock:
        mock.get("/api/tags").mock(side_effect=httpx.ConnectError("refused"))
        r = client.get("/api/models")
    assert r.status_code == 503 and r.json()["error"]["code"] == "runtime_offline"


def test_non_ollama_provider_409(client):
    s = client.get("/api/settings/model").json()
    s.update(provider="openai", base_url="http://localhost:1234/v1")
    assert client.put("/api/settings/model", json=s).status_code == 200
    r = client.post("/api/models/pull", json={"name": "llama3.2:3b"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "unsupported_provider"
