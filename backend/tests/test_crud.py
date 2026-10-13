from app.security import MASK


def test_skill_crud(client):
    r = client.post(
        "/api/skills", json={"name": "sql-expert", "instructions": "Write SQL", "tools": ["x"]}
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert client.post("/api/skills", json={"name": "sql-expert"}).status_code == 409
    r = client.put(
        f"/api/skills/{sid}", json={"name": "sql-expert", "description": "d", "instructions": "y"}
    )
    assert r.json()["description"] == "d"
    assert (
        client.patch(f"/api/skills/{sid}/enabled", json={"enabled": False}).json()["enabled"]
        is False
    )
    assert client.delete(f"/api/skills/{sid}").status_code == 204
    assert client.get(f"/api/skills/{sid}").json()["error"]["code"] == "not_found"


def test_invalid_name_rejected(client):
    r = client.post("/api/skills", json={"name": "Bad Name!"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_connector_secrets_masked_and_preserved(client, settings):
    body = {
        "name": "api",
        "type": "http",
        "config": {
            "base_url": "https://example.com",
            "headers": {"Authorization": "Bearer s3cr3t"},
        },
    }
    r = client.post("/api/connectors", json=body)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["config"]["headers"]["Authorization"] == MASK
    assert out["tools"] == ["conn__api__request"]
    # Round-trip the masked value: original secret must be preserved.
    body["config"]["headers"]["Authorization"] = MASK
    client.put(f"/api/connectors/{out['id']}", json=body)
    db_bytes = (settings.data_dir / "offline_ai.db").read_bytes()
    assert b"s3cr3t" not in db_bytes  # encrypted at rest
    from sqlmodel import Session

    from app.services.repository import Repository

    st = client.app.state.oai
    with Session(st.engine) as s:
        repo = Repository(s, st.crypto, st.settings)
        cfg = repo.connector_config(repo.get_connector(out["id"]))
    assert cfg["headers"]["Authorization"] == "Bearer s3cr3t"


def test_connector_invalid_config(client):
    r = client.post(
        "/api/connectors", json={"name": "fs", "type": "filesystem", "config": {"root": "relative"}}
    )
    assert r.status_code == 422


def test_mcp_stdio_requires_confirmation_and_allowlist(client):
    base = {
        "name": "files",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "pkg"],
        "enabled": False,
    }
    r = client.post("/api/mcp-servers", json=base)
    assert r.status_code == 428 and r.json()["error"]["code"] == "confirmation_required"
    r = client.post("/api/mcp-servers", json={**base, "command": "rm", "confirmed": True})
    assert r.status_code == 403
    r = client.post("/api/mcp-servers", json={**base, "confirmed": True, "env": {"TOKEN": "abc"}})
    assert r.status_code == 201, r.text
    assert r.json()["env"] == {"TOKEN": MASK} and r.json()["status"] == "disabled"


def test_mcp_remote_requires_url(client):
    r = client.post("/api/mcp-servers", json={"name": "remote", "transport": "http"})
    assert r.status_code == 422


def test_model_settings_mask_api_key(client):
    r = client.put(
        "/api/settings/model",
        json={"provider": "openai", "base_url": "http://localhost:1234/v1", "api_key": "k-123"},
    )
    assert r.json()["api_key"] == MASK
    client.put(
        "/api/settings/model",
        json={"provider": "openai", "base_url": "http://localhost:1234/v1", "api_key": MASK},
    )
    assert client.app.state.oai.store.get().api_key == "k-123"


def test_api_token(settings):
    from fastapi.testclient import TestClient

    from app.main import create_app

    settings.api_token = "t0k"
    with TestClient(create_app(settings)) as c:
        assert c.get("/api/health").status_code == 401
        assert c.get("/api/health", headers={"Authorization": "Bearer t0k"}).status_code == 200
