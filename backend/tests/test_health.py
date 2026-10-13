import httpx
import pytest

from app.providers.ollama import OllamaProvider
from app.providers.openai_compat import OpenAICompatProvider


def test_app_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_model_health_online(client, fake_provider):
    body = client.get("/api/health/model").json()
    assert body["online"] is True
    assert body["models"] == ["llama3.1:8b", "qwen2.5:7b"]
    assert body["latency_ms"] == 1.2


def test_model_health_offline(client, fake_provider):
    fake_provider.online = False
    body = client.get("/api/health/model").json()
    assert body["online"] is False and "refused" in body["error"]


def test_untrusted_host_rejected(client):
    r = client.get("/api/health", headers={"host": "evil.example"})
    assert r.status_code == 400


@pytest.mark.parametrize(
    ("cls", "path", "payload", "expected"),
    [
        (OllamaProvider, "/api/tags", {"models": [{"name": "b"}, {"name": "a"}]}, ["a", "b"]),
        (OpenAICompatProvider, "/v1/models", {"data": [{"id": "m1"}]}, ["m1"]),
    ],
)
async def test_provider_ping(monkeypatch, cls, path, payload, expected):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == path
        return httpx.Response(200, json=payload)

    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    res = await cls("http://x", api_key=None, timeout_s=5, ping_timeout_s=1).ping()
    assert res.online and res.models == expected


async def test_ollama_stream_tool_calls(monkeypatch):
    lines = (
        '{"message":{"content":"Hi"}}\n'
        '{"message":{"content":"","tool_calls":[{"function":{"name":"t","arguments":{"a":1}}}]}}\n'
        '{"done":true}\n'
    )
    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: real(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, text=lines)), **kw
        ),
    )
    p = OllamaProvider("http://x", api_key=None, timeout_s=5, ping_timeout_s=1)
    events = [e async for e in p.chat_stream(model="m", messages=[], tools=[], temperature=0)]
    assert events[0].content == "Hi"
    assert events[-1].tool_calls[0].name == "t" and events[-1].tool_calls[0].arguments == {"a": 1}


async def test_openai_stream_assembles_partial_tool_calls(monkeypatch):
    sse = (
        'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"x","function":{"name":"fn","arguments":"{\\"q\\":"}}]}}]}\n\n'
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"1}"}}]}}]}\n\n'
        "data: [DONE]\n\n"
    )
    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: real(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, text=sse)), **kw
        ),
    )
    p = OpenAICompatProvider("http://x", api_key=None, timeout_s=5, ping_timeout_s=1)
    events = [e async for e in p.chat_stream(model="m", messages=[], tools=[], temperature=0)]
    call = events[-1].tool_calls[0]
    assert (call.id, call.name, call.arguments) == ("x", "fn", {"q": 1})
