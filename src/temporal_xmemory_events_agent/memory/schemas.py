"""Read an XMD schema file and the instance description it carries."""

from pathlib import Path

import yaml

from temporal_xmemory_events_agent.base_models import FrozenTightBaseModel
from temporal_xmemory_events_agent.errors import ConfigurationError

DEFAULT_SCHEMA_DIR = Path("schema")
SCHEMA_FILES = {"events": "events.yml", "coordination": "coordination.yml"}


class SchemaDocument(FrozenTightBaseModel):
    name: str
    text: str
    title: str
    description: str


def load_schema(name: str, schema_dir: Path | str = DEFAULT_SCHEMA_DIR) -> SchemaDocument:
    """Load the schema for a target by name (events or coordination) from the schema directory."""
    try:
        path = Path(schema_dir) / SCHEMA_FILES[name]
    except KeyError as exc:
        raise ConfigurationError(f"no schema is defined for a memory named {name!r}") from exc
    if not path.exists():
        raise ConfigurationError(f"schema file not found: {path} (run from the repository root or pass --schema-dir)")
    text = path.read_text()
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict) or "objects" not in raw:
        raise ConfigurationError(f"{path} is not an XMD schema document")
    return SchemaDocument(
        name=name,
        text=text,
        title=str(raw.get("title") or name),
        description=str(raw.get("description") or "").strip(),
    )
