from __future__ import annotations

import os

from app.config import Settings
from app.paths import app_paths, ensure_private_dir, migrate_legacy_data


def test_oai_home_override(tmp_path, monkeypatch):
    monkeypatch.setenv("OAI_HOME", str(tmp_path))
    p = app_paths()
    assert p.data == tmp_path / "data"
    assert p.config_file == tmp_path / "config.env"
    assert Settings().data_dir == tmp_path / "data"


def test_default_is_per_user(monkeypatch):
    monkeypatch.delenv("OAI_HOME", raising=False)
    p = app_paths()
    assert "offline-ai" in str(p.data)
    assert str(p.data).startswith(os.path.expanduser("~")) or os.name == "nt"


def test_private_dir(tmp_path):
    d = ensure_private_dir(tmp_path / "x" / "y")
    if os.name == "posix":
        assert (d.stat().st_mode & 0o777) == 0o700


def test_migrate_legacy(tmp_path):
    legacy = tmp_path / "old"
    legacy.mkdir()
    (legacy / "offline_ai.db").write_bytes(b"db")
    (legacy / "secret.key").write_bytes(b"k")
    target = tmp_path / "new"
    assert migrate_legacy_data(target, legacy) is True
    assert (target / "offline_ai.db").read_bytes() == b"db"
    assert migrate_legacy_data(target, legacy) is False
