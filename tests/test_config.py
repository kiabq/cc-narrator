import pytest

from cc_narrator.config import REQUIRED_KEYS, load_config

REQUIRED = {
    "ELEVENLABS_API_KEY": "key",
    "CC_NARRATOR_NARRATOR_VOICE_ID": "narrator",
    "CC_NARRATOR_ANNOUNCER_VOICE_ID": "announcer",
}


def env_file(tmp_path, text):
    path = tmp_path / ".env"
    path.write_text(text)
    return path


def test_missing_required_keys_are_reported(tmp_path):
    cfg = load_config(env={}, env_path=tmp_path / "absent.env")
    assert cfg.missing == REQUIRED_KEYS
    assert not cfg.is_valid


def test_defaults_apply(tmp_path):
    cfg = load_config(env=REQUIRED, env_path=tmp_path / "absent.env")
    assert cfg.is_valid
    assert cfg.api_key == "key"
    assert cfg.narrator_voice_id == "narrator"
    assert cfg.announcer_voice_id == "announcer"
    assert cfg.tts_model == "eleven_flash_v2_5"
    assert cfg.narrator_volume == 1.0
    assert cfg.announcer_volume == 0.4
    assert cfg.enabled_by_default is True
    assert cfg.announce_max_age_seconds == 60.0


def test_values_come_from_env_file(tmp_path):
    path = env_file(
        tmp_path,
        "ELEVENLABS_API_KEY=filekey\nCC_NARRATOR_NARRATOR_VOICE_ID=n\nCC_NARRATOR_ANNOUNCER_VOICE_ID=a\n"
        "CC_NARRATOR_ANNOUNCER_VOLUME=0.2\n",
    )
    cfg = load_config(env={}, env_path=path)
    assert cfg.api_key == "filekey"
    assert cfg.announcer_volume == 0.2


def test_environment_overrides_file(tmp_path):
    path = env_file(tmp_path, "ELEVENLABS_API_KEY=filekey\n")
    cfg = load_config(env={**REQUIRED, "ELEVENLABS_API_KEY": "envkey"}, env_path=path)
    assert cfg.api_key == "envkey"


def test_empty_environment_value_does_not_override_file(tmp_path):
    path = env_file(tmp_path, "ELEVENLABS_API_KEY=filekey\n")
    cfg = load_config(env={**REQUIRED, "ELEVENLABS_API_KEY": ""}, env_path=path)
    assert cfg.api_key == "filekey"


def test_bad_number_falls_back_to_default(tmp_path):
    env = {**REQUIRED, "CC_NARRATOR_NARRATOR_VOLUME": "loud"}
    cfg = load_config(env=env, env_path=tmp_path / "x")
    assert cfg.narrator_volume == 1.0


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("false", False), ("0", False), ("no", False), ("off", False), ("true", True), ("YES", True)],
)
def test_enabled_by_default_parsing(tmp_path, raw, expected):
    env = {**REQUIRED, "CC_NARRATOR_ENABLED_BY_DEFAULT": raw}
    cfg = load_config(env=env, env_path=tmp_path / "x")
    assert cfg.enabled_by_default is expected
