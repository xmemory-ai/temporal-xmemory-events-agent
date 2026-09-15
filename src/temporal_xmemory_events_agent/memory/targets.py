"""Resolve memory targets from settings, environment and CLI overrides, and read their keys."""

import os

from temporal_xmemory_events_agent.dto.settings import (
    DEFAULT_API_KEY_ENV,
    DEFAULT_API_URL,
    DEFAULT_API_URL_ENV,
    MemoryTargetSettings,
)
from temporal_xmemory_events_agent.dto.targets import MemoryTarget
from temporal_xmemory_events_agent.errors import ConfigurationError


def resolve_target(name: str, settings: MemoryTargetSettings) -> MemoryTarget:
    """Fill the gaps in a configured target from the environment, then the library defaults."""
    url = settings.url or os.environ.get(DEFAULT_API_URL_ENV) or DEFAULT_API_URL
    return MemoryTarget(
        name=name,
        url=url.rstrip("/"),
        api_key_env=settings.api_key_env or DEFAULT_API_KEY_ENV,
        instance_id=settings.instance_id,
    )


def effective_api_key_env(target: MemoryTarget) -> str:
    """The env var that actually carries this target's key: its own, else the shared fallback.

    Returned as a NAME so callers such as `XmemoryConfig` can keep the key out of persisted state.
    """
    if os.environ.get(target.api_key_env):
        return target.api_key_env
    if os.environ.get(DEFAULT_API_KEY_ENV):
        return DEFAULT_API_KEY_ENV
    raise ConfigurationError(
        f"no API key for the {target.name} memory: set {target.api_key_env} (or the shared {DEFAULT_API_KEY_ENV})"
    )


def resolve_api_key(target: MemoryTarget) -> str:
    return os.environ[effective_api_key_env(target)]


def require_instance_id(target: MemoryTarget) -> str:
    if not target.instance_id:
        raise ConfigurationError(
            f"the {target.name} memory has no instance_id in config.yml; run `create-instances --write-config`"
        )
    return target.instance_id
