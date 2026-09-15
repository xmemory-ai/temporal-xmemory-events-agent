"""Configuration loading and memory-target resolution."""

import os
from pathlib import Path

import pytest

from temporal_xmemory_events_agent.config import load_dotenv, load_settings, write_instance_ids
from temporal_xmemory_events_agent.dto.settings import DEFAULT_API_KEY_ENV, DEFAULT_API_URL, MemoryTargetSettings
from temporal_xmemory_events_agent.errors import ConfigurationError
from temporal_xmemory_events_agent.memory.targets import effective_api_key_env, resolve_api_key, resolve_target

MINIMAL = """
xmemory:
  events: {url: https://events.example, api_key_env: EV_KEY, instance_id: ev-1}
  coordination: {instance_id: co-1}
openai: {model: test-model}
"""


def test_file_values_win_over_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XMEM_API_URL", "https://env.example")
    path = tmp_path / "config.yml"
    path.write_text(MINIMAL)
    settings = load_settings(path)
    events = resolve_target("events", settings.xmemory.events)
    coordination = resolve_target("coordination", settings.xmemory.coordination)
    assert events.url == "https://events.example"
    assert events.api_key_env == "EV_KEY"
    assert coordination.url == "https://env.example"
    assert coordination.api_key_env == DEFAULT_API_KEY_ENV


def test_cli_override_wins_over_file(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text(MINIMAL)
    settings = load_settings(path, {"xmemory.events.url": "https://flag.example", "openai.model": None})
    assert settings.xmemory.events.url == "https://flag.example"
    assert settings.openai.model == "test-model"


def test_library_default_when_nothing_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XMEM_API_URL", raising=False)
    target = resolve_target("events", MemoryTargetSettings())
    assert target.url == DEFAULT_API_URL


def test_api_key_prefers_the_targets_own_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    target = resolve_target("events", MemoryTargetSettings(api_key_env="EV_KEY"))
    monkeypatch.setenv("EV_KEY", "ev-secret")
    monkeypatch.setenv(DEFAULT_API_KEY_ENV, "shared-secret")
    assert effective_api_key_env(target) == "EV_KEY"
    assert resolve_api_key(target) == "ev-secret"
    monkeypatch.delenv("EV_KEY")
    assert effective_api_key_env(target) == DEFAULT_API_KEY_ENV
    monkeypatch.delenv(DEFAULT_API_KEY_ENV)
    with pytest.raises(ConfigurationError):
        effective_api_key_env(target)


def test_settings_never_carry_a_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EV_KEY", "ev-secret-value")
    path = tmp_path / "config.yml"
    path.write_text(MINIMAL)
    assert "ev-secret-value" not in load_settings(path).model_dump_json()


def test_unknown_key_and_wrong_type_fail_loudly(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text("scout: {max_parallel_processing: three}\n")
    with pytest.raises(ConfigurationError):
        load_settings(path)
    path.write_text("scout: {no_such_setting: 1}\n")
    with pytest.raises(ConfigurationError):
        load_settings(path)


def test_missing_file_falls_back_to_template_only_at_default_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigurationError):
        load_settings("elsewhere.yml")
    Path("config.yml.template").write_text("openai: {model: from-template}\n")
    assert load_settings().openai.model == "from-template"


def test_write_instance_ids_touches_only_ids(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text(MINIMAL)
    write_instance_ids(path, events="ev-2")
    settings = load_settings(path)
    assert settings.xmemory.events.instance_id == "ev-2"
    assert settings.xmemory.events.url == "https://events.example"
    assert settings.xmemory.coordination.instance_id == "co-1"
    assert settings.openai.model == "test-model"


def test_dotenv_sets_only_missing_variables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "# comment\nexport XMEM_API_KEY=xmem_from_file\nOPENAI_API_KEY='sk-quoted'\nALREADY=from-file\nnot a line\n"
    )
    monkeypatch.delenv("XMEM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ALREADY", "from-env")
    assert load_dotenv(dotenv) == ["XMEM_API_KEY", "OPENAI_API_KEY"]
    assert os.environ["XMEM_API_KEY"] == "xmem_from_file"
    assert os.environ["OPENAI_API_KEY"] == "sk-quoted"
    assert os.environ["ALREADY"] == "from-env"
    assert load_dotenv(tmp_path / "missing.env") == []


def test_write_instance_ids_keeps_comments_and_order(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text(
        '# top comment\nxmemory:\n  events:\n    url: https://x.example   # keep me\n    instance_id: ""   # filled later\n'
        "  coordination:\n    instance_id: old\nopenai: {model: m}\n"
    )
    write_instance_ids(path, events="ev-9", coordination="co-9")
    text = path.read_text()
    assert "# top comment" in text and "# keep me" in text and "# filled later" in text
    assert "    instance_id: ev-9   # filled later" in text
    assert "    instance_id: co-9" in text
    settings = load_settings(path)
    assert settings.xmemory.events.instance_id == "ev-9"
    assert settings.xmemory.coordination.instance_id == "co-9"
    assert settings.openai.model == "m"
