import sys
import time
from pathlib import Path

from tests.conftest import parse_sse

FAKE_SERVER = str(Path(__file__).with_name("fake_mcp_server.py"))


def _wait_connected(client, sid, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/mcp-servers/{sid}").json()
        if body["status"] == "connected":
            return body
        time.sleep(0.3)
    raise AssertionError(f"MCP server did not connect: {body}")


def test_plain_chat_streams_and_persists(client, fake_provider):
    fake_provider.script = [{"text": "Hello there"}]
    r = client.post("/api/chat", json={"message": "hi"})
    events = parse_sse(r.text)
    kinds = [e for e, _ in events]
    assert kinds[0] == "session" and kinds[-1] == "done" and "delta" in kinds
    sid = events[0][1]["session_id"]
    msgs = client.get(f"/api/chat/sessions/{sid}/messages").json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["content"].strip() == "Hello there"


def test_skills_injected_into_system_prompt(client, fake_provider):
    client.post("/api/skills", json={"name": "pirate", "instructions": "Talk like a pirate."})
    client.post(
        "/api/skills", json={"name": "off", "instructions": "SHOULD NOT APPEAR", "enabled": False}
    )
    client.post("/api/chat", json={"message": "hi"})
    system = fake_provider.calls[0]["messages"][0]["content"]
    assert "Talk like a pirate." in system and "SHOULD NOT APPEAR" not in system


def test_tool_loop_with_connector(client, fake_provider, tmp_path):
    (tmp_path / "notes.txt").write_text("secret plan")
    client.post(
        "/api/connectors",
        json={"name": "docs", "type": "filesystem", "config": {"root": str(tmp_path)}},
    )
    fake_provider.script = [
        {"calls": [("conn__docs__read_file", {"path": "notes.txt"})]},
        {"text": "The file says secret plan"},
    ]
    events = parse_sse(client.post("/api/chat", json={"message": "read notes"}).text)
    result = next(d for e, d in events if e == "tool_result")
    assert result["ok"] and result["content"] == "secret plan"
    # Second model call must include the tool result.
    assert fake_provider.calls[1]["messages"][-1]["role"] == "tool"


def test_tool_loop_is_bounded(client, fake_provider, tmp_path):
    client.post(
        "/api/connectors",
        json={"name": "docs", "type": "filesystem", "config": {"root": str(tmp_path)}},
    )
    fake_provider.script = [{"calls": [("conn__docs__list_dir", {})]}] * 10
    events = parse_sse(client.post("/api/chat", json={"message": "loop"}).text)
    assert events[-1][0] == "done"
    assert len(fake_provider.calls) == 4  # max_tool_rounds=3 + final tool-less round
    assert fake_provider.calls[-1]["tools"] == []


def test_unknown_tool_reported_not_crashing(client, fake_provider):
    fake_provider.script = [{"calls": [("nope", {})]}, {"text": "sorry"}]
    events = parse_sse(client.post("/api/chat", json={"message": "x"}).text)
    result = next(d for e, d in events if e == "tool_result")
    assert result["ok"] is False and "Unknown tool" in result["content"]


def test_no_model_selected(client, fake_provider):
    client.app.state.oai.settings.default_model = None
    r = client.post("/api/chat", json={"message": "hi"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "no_model"


def test_mcp_stdio_end_to_end(client, fake_provider, settings):
    settings.mcp_stdio_allowed_commands.append(Path(sys.executable).name)
    r = client.post(
        "/api/mcp-servers",
        json={
            "name": "fake",
            "transport": "stdio",
            "command": sys.executable,
            "args": [FAKE_SERVER],
            "confirmed": True,
        },
    )
    assert r.status_code == 201, r.text
    server = _wait_connected(client, r.json()["id"])
    assert [t["exposed_name"] for t in server["tools"]] == ["mcp__fake__add"]

    tools = client.get("/api/tools").json()
    assert {"name": "mcp__fake__add", "source": "mcp:fake"}.items() <= tools[0].items()

    fake_provider.script = [{"calls": [("mcp__fake__add", {"a": 2, "b": 40})]}, {"text": "42"}]
    events = parse_sse(client.post("/api/chat", json={"message": "add"}).text)
    result = next(d for e, d in events if e == "tool_result")
    assert result["ok"] and result["content"] == "42"

    assert client.delete(f"/api/mcp-servers/{r.json()['id']}").status_code == 204
