"""Typed application settings loaded from config/settings.yml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class RedisSettings(BaseModel):
    url: str = "redis://localhost:6379/0"


class RateLimitSettings(BaseModel):
    max_requests: int = 10
    window_seconds: int = 60
    method: str = "POST"
    path: str = "/shorten"


class Settings(BaseModel):
    redis: RedisSettings = RedisSettings()
    rate_limit: RateLimitSettings = RateLimitSettings()

    @classmethod
    def from_yaml(cls, path: Path | None = None) -> Settings:
        """Load settings from YAML file, falling back to defaults."""
        if path is None:
            # Resolve relative to project root (two levels up from app/)
            path = Path(__file__).resolve().parent.parent / "config" / "settings.yml"

        data: dict = {}
        if path.is_file():
            with open(path) as f:
                data = yaml.safe_load(f) or {}

        return cls(**data)


# Module-level singleton — loaded once at import.
settings = Settings.from_yaml()
