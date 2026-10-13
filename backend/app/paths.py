"""Per-user, OS-appropriate locations for data, config and logs.

* Linux:   ``~/.local/share/offline-ai`` (data), ``~/.config/offline-ai`` (config)
* macOS:   ``~/Library/Application Support/offline-ai``
* Windows: ``%LOCALAPPDATA%\\offline-ai``

Setting ``OAI_HOME`` puts everything under a single directory instead.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from platformdirs import PlatformDirs

APP_NAME = "offline-ai"
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppPaths:
    data: Path
    config: Path
    logs: Path

    @property
    def config_file(self) -> Path:
        return self.config / "config.env"


def app_paths() -> AppPaths:
    home = os.environ.get("OAI_HOME")
    if home:
        root = Path(home).expanduser()
        return AppPaths(data=root / "data", config=root, logs=root / "logs")
    d = PlatformDirs(APP_NAME, appauthor=False)
    return AppPaths(
        data=Path(d.user_data_dir), config=Path(d.user_config_dir), logs=Path(d.user_log_dir)
    )


def ensure_private_dir(path: Path) -> Path:
    """Create ``path`` (and parents); restrict to the current user on POSIX."""
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        try:
            path.chmod(0o700)
        except OSError:  # pragma: no cover - e.g. foreign-owned dir
            log.warning("Could not restrict permissions on %s", path)
    return path


def migrate_legacy_data(target: Path, legacy: Path = Path("./data")) -> bool:
    """One-time copy of a pre-packaging ``./data`` folder into the per-user dir."""
    try:
        if legacy.resolve() == target.resolve():
            return False
    except OSError:
        return False
    if not (legacy / "offline_ai.db").is_file() or (target / "offline_ai.db").exists():
        return False
    ensure_private_dir(target)
    for name in ("offline_ai.db", "secret.key"):
        src = legacy / name
        if src.is_file():
            shutil.copy2(src, target / name)
    log.info("Migrated legacy data from %s to %s", legacy.resolve(), target)
    return True
