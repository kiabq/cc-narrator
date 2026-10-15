"""Settings: environment variables over ~/.config/claude-voice-augmented/.env over defaults."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

SAMPLE_RATE = 22050
DEFAULT_ENV_PATH = Path.home() / ".config" / "claude-voice-augmented" / ".env"
REQUIRED_KEYS = ("ELEVENLABS_API_KEY", "CVA_NARRATOR_VOICE_ID", "CVA_ANNOUNCER_VOICE_ID")
_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    api_key: str
    narrator_voice_id: str
    announcer_voice_id: str
    tts_model: str = "eleven_flash_v2_5"
    narrator_volume: float = 1.0
    announcer_volume: float = 0.4
    enabled_by_default: bool = True
    announce_max_age_seconds: float = 60.0
    missing: tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not self.missing


def _float(raw: str, default: float) -> float:
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def load_config(env: Mapping[str, str] | None = None, env_path: Path | None = None) -> Config:
    env = os.environ if env is None else env
    path = DEFAULT_ENV_PATH if env_path is None else env_path

    values: dict[str, str] = {}
    if path.is_file():
        values.update({k: v for k, v in dotenv_values(path).items() if v is not None})
    values.update({k: v for k, v in env.items() if v and k.startswith(("CVA_", "ELEVENLABS_"))})

    def get(key: str) -> str:
        return values.get(key, "").strip()

    enabled = get("CVA_ENABLED_BY_DEFAULT")
    return Config(
        api_key=get("ELEVENLABS_API_KEY"),
        narrator_voice_id=get("CVA_NARRATOR_VOICE_ID"),
        announcer_voice_id=get("CVA_ANNOUNCER_VOICE_ID"),
        tts_model=get("CVA_TTS_MODEL") or "eleven_flash_v2_5",
        narrator_volume=_float(get("CVA_NARRATOR_VOLUME"), 1.0),
        announcer_volume=_float(get("CVA_ANNOUNCER_VOLUME"), 0.4),
        enabled_by_default=enabled.lower() in _TRUE if enabled else True,
        announce_max_age_seconds=_float(get("CVA_ANNOUNCE_MAX_AGE_SECONDS"), 60.0),
        missing=tuple(key for key in REQUIRED_KEYS if not get(key)),
    )
