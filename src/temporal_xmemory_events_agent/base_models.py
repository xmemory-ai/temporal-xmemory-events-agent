"""Project base models, in the shape of the xmemory monorepo's ``common/util/base_models.py``.

Every DTO in this package derives from one of these instead of setting ``model_config`` itself.
"""

from pydantic import BaseModel, ConfigDict


class TightBaseModel(BaseModel):
    """Strict types, unknown keys rejected. The default for configuration and DTOs."""

    model_config = ConfigDict(strict=True, extra="forbid")


class FrozenTightBaseModel(BaseModel):
    """`TightBaseModel` that is immutable after construction."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
