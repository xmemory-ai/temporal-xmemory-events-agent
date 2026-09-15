"""Load ``config.yml`` into `Settings`, with CLI overrides applied before validation.

Resolution order for every value: CLI override, then the file, then (for memory targets) the environment,
then the library default. The file is strongly typed: a wrong type, an unknown key or a missing section
fails loudly at startup.
"""

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from temporal_xmemory_events_agent.dto.settings import Settings
from temporal_xmemory_events_agent.errors import ConfigurationError

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("config.yml")
TEMPLATE_CONFIG_PATH = Path("config.yml.template")
DEFAULT_DOTENV_PATH = Path(".env")
_DOTENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")

# A CLI override is a dotted path into the YAML document, e.g. "xmemory.events.url".
Overrides = dict[str, Any]


def load_dotenv(path: Path | str = DEFAULT_DOTENV_PATH) -> list[str]:
    """Put the variables of a `.env` file into the environment without overriding what is already set.

    Accepts `KEY=value` and `export KEY=value` lines, single or double quotes around the value, blank lines and
    `#` comments. Returns the names that were set. Secrets stay in the file and the process environment only.
    """
    dotenv = Path(path)
    if not dotenv.exists():
        return []
    names: list[str] = []
    for raw in dotenv.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _DOTENV_LINE.match(line)
        if not match:
            continue
        name, value = match.group(1), match.group(2)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if name not in os.environ:
            os.environ[name] = value
            names.append(name)
    return names


def _apply_override(data: dict[str, Any], dotted: str, value: Any) -> None:
    node = data
    *parents, leaf = dotted.split(".")
    for key in parents:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    node[leaf] = value


def load_settings(path: Path | str = DEFAULT_CONFIG_PATH, overrides: Overrides | None = None) -> Settings:
    """Read the config file (or the tracked template when it is absent) and validate it."""
    config_path = Path(path)
    if not config_path.exists():
        if config_path == DEFAULT_CONFIG_PATH and TEMPLATE_CONFIG_PATH.exists():
            logger.warning("%s not found; falling back to %s", config_path, TEMPLATE_CONFIG_PATH)
            config_path = TEMPLATE_CONFIG_PATH
        else:
            raise ConfigurationError(f"configuration file not found: {config_path}")
    try:
        raw = yaml.safe_load(config_path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"{config_path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigurationError(f"{config_path} must contain a mapping at the top level")
    for dotted, value in (overrides or {}).items():
        if value is not None:
            _apply_override(raw, dotted, value)
    try:
        return Settings.model_validate(raw)
    except ValidationError as exc:
        raise ConfigurationError(f"{config_path} is invalid:\n{exc}") from exc


def write_instance_ids(path: Path | str, *, events: str | None = None, coordination: str | None = None) -> None:
    """Record freshly created instance ids in the config file, touching nothing else."""
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text()) if config_path.exists() else {}
    raw = raw or {}
    section = raw.setdefault("xmemory", {})
    if events is not None:
        section.setdefault("events", {})["instance_id"] = events
    if coordination is not None:
        section.setdefault("coordination", {})["instance_id"] = coordination
    config_path.write_text(yaml.safe_dump(raw, sort_keys=False))
