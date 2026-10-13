from __future__ import annotations

import socket

from typer.testing import CliRunner

from app import __version__
from app.cli import app, pick_port, port_free

runner = CliRunner()


def test_version():
    r = runner.invoke(app, ["version"])
    assert r.exit_code == 0 and __version__ in r.stdout


def test_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("OAI_HOME", str(tmp_path))
    r = runner.invoke(app, ["paths"])
    assert r.exit_code == 0 and str(tmp_path) in r.stdout


def test_doctor_reports_missing_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("OAI_HOME", str(tmp_path))
    monkeypatch.setenv("OAI_MODEL_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setattr("app.services.runtime.find_ollama", lambda: None)
    r = runner.invoke(app, ["doctor"])
    assert r.exit_code == 1
    assert "Ollama installed" in r.stdout and "Install:" in r.stdout


def test_pick_port_skips_busy():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        busy = s.getsockname()[1]
        assert not port_free("127.0.0.1", busy)
        assert pick_port("127.0.0.1", busy) != busy
