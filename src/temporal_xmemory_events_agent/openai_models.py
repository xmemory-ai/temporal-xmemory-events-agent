"""Check that the configured OpenAI model exists before anything depends on it."""

import logging
import os

from openai import AsyncOpenAI, NotFoundError

from temporal_xmemory_events_agent.errors import ConfigurationError

logger = logging.getLogger(__name__)


async def verify_model(model: str) -> None:
    """Fail loudly on an empty or unknown model name; only warn when no key is available to check."""
    if not model:
        raise ConfigurationError("openai.model is empty in config.yml; set it to the model both agents should use")
    if not os.environ.get("OPENAI_API_KEY"):
        logger.warning("OPENAI_API_KEY is unset; the model name %r was not verified", model)
        return
    try:
        await AsyncOpenAI().models.retrieve(model)
    except NotFoundError as exc:
        raise ConfigurationError(f"OpenAI does not know a model named {model!r}") from exc
    logger.info("OpenAI model %r verified", model)
