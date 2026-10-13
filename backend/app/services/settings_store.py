"""Runtime model settings persisted in the DB (API key encrypted)."""

from __future__ import annotations

from sqlalchemy.engine import Engine
from sqlmodel import Session

from ..config import Settings
from ..models import AppSetting
from ..providers import ModelProvider, build_provider
from ..schemas import ModelSettings
from ..security import MASK, Crypto

KEY = "model"


class SettingsStore:
    def __init__(self, engine: Engine, settings: Settings, crypto: Crypto) -> None:
        self._engine = engine
        self._settings = settings
        self._crypto = crypto

    def get(self) -> ModelSettings:
        with Session(self._engine) as s:
            row = s.get(AppSetting, KEY)
        if row is None:
            return ModelSettings(
                provider=self._settings.model_provider,
                base_url=self._settings.model_base_url,
                api_key=self._settings.model_api_key,
                default_model=self._settings.default_model,
            )
        data = dict(row.value)
        enc = data.pop("api_key_enc", None)
        data["api_key"] = self._crypto.decrypt_json(enc) if enc else None
        return ModelSettings(**data)

    def get_public(self) -> ModelSettings:
        current = self.get()
        return current.model_copy(update={"api_key": MASK if current.api_key else None})

    def update(self, new: ModelSettings) -> ModelSettings:
        current = self.get()
        api_key = current.api_key if new.api_key == MASK else (new.api_key or None)
        data = new.model_dump(exclude={"api_key"})
        data["api_key_enc"] = self._crypto.encrypt_json(api_key) if api_key else None
        with Session(self._engine) as s:
            row = s.get(AppSetting, KEY) or AppSetting(key=KEY)
            row.value = data
            s.add(row)
            s.commit()
        return self.get_public()

    def provider(self, override: ModelSettings | None = None) -> ModelProvider:
        cfg = override or self.get()
        return build_provider(
            cfg.provider,
            cfg.base_url,
            api_key=cfg.api_key,
            timeout_s=self._settings.model_timeout_s,
            ping_timeout_s=self._settings.ping_timeout_s,
        )
