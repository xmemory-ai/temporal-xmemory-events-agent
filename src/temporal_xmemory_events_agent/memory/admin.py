"""Instance administration and ad-hoc reads and writes, used by the CLI (never from a workflow)."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from xmemory import AsyncXmemoryClient, ExtractionLogic, ReadMode, SchemaType, XmemoryAPIError

from temporal_xmemory_events_agent.dto.targets import MemoryTarget
from temporal_xmemory_events_agent.errors import ConfigurationError
from temporal_xmemory_events_agent.memory.schemas import SchemaDocument
from temporal_xmemory_events_agent.memory.targets import require_instance_id, resolve_api_key

logger = logging.getLogger(__name__)

ADMIN_TIMEOUT_SECONDS = 120
# Transient failures (a dropped connection, a 5xx, a rate limit) get a second and third try with a pause;
# everything else, including a write the server already accepted but is still processing, surfaces at once.
TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})
TRANSIENT_ATTEMPTS = 3
TRANSIENT_PAUSE_SECONDS = 3.0
T = TypeVar("T")
WRITE_TIMEOUT_SECONDS = 600
READ_TIMEOUT_SECONDS = 120


def is_transient(error: XmemoryAPIError) -> bool:
    if error.code == "WRITE_STILL_PROCESSING":
        return False
    return error.status is None or error.status in TRANSIENT_STATUSES


async def with_retries(label: str, call: Callable[[], Awaitable[T]]) -> T:
    """Run `call`, retrying transient xmemory errors a bounded number of times."""
    for attempt in range(1, TRANSIENT_ATTEMPTS + 1):
        try:
            return await call()
        except XmemoryAPIError as error:
            if not is_transient(error) or attempt == TRANSIENT_ATTEMPTS:
                raise
            logger.warning("%s failed transiently (attempt %d/%d): %s", label, attempt, TRANSIENT_ATTEMPTS, error)
            await asyncio.sleep(TRANSIENT_PAUSE_SECONDS * attempt)
    raise AssertionError("unreachable")


def open_client(target: MemoryTarget) -> AsyncXmemoryClient:
    return AsyncXmemoryClient(url=target.url, api_key=resolve_api_key(target), timeout=ADMIN_TIMEOUT_SECONDS)


async def pick_cluster(client: AsyncXmemoryClient, cluster_id: str | None) -> str:
    if cluster_id:
        return cluster_id
    clusters = await client.admin.list_clusters()
    if len(clusters) != 1:
        raise ConfigurationError(
            f"the account has {len(clusters)} clusters; pass --cluster-id with one of {[c.id for c in clusters]}"
        )
    return clusters[0].id


async def create_instance(target: MemoryTarget, schema: SchemaDocument, name: str, cluster_id: str | None) -> str:
    """Create an instance from an XMD document; the instance description is the document's own description."""
    async with open_client(target) as client:
        chosen = await pick_cluster(client, cluster_id)
        instance = await client.admin.create_instance(
            chosen, name, schema.text, SchemaType.YML, description=schema.description or None
        )
        logger.info("created %s instance %s on cluster %s", target.name, instance.id, chosen)
        return instance.id


async def delete_instance(target: MemoryTarget, instance_id: str) -> None:
    async with open_client(target) as client:
        await client.admin.delete_instance(instance_id)
        logger.info("deleted %s instance %s", target.name, instance_id)


async def write_text(target: MemoryTarget, text: str, *, deep: bool = False) -> str:
    """Synchronous text write; returns the write id. Deep extraction is slower but more thorough."""
    logic = ExtractionLogic.DEEP if deep else ExtractionLogic.FAST
    async with open_client(target) as client:
        instance = client.instance(require_instance_id(target))
        result = await with_retries(
            f"{target.name} write", lambda: instance.write(text, extraction_logic=logic, timeout=WRITE_TIMEOUT_SECONDS)
        )
        return result.write_id


async def read_answer(target: MemoryTarget, question: str) -> str:
    async with open_client(target) as client:
        instance = client.instance(require_instance_id(target))
        result = await with_retries(
            f"{target.name} read",
            lambda: instance.read(question, read_mode=ReadMode.SINGLE_ANSWER, timeout=READ_TIMEOUT_SECONDS),
        )
    answer = result.reader_result
    if isinstance(answer, dict) and "answer" in answer:
        return str(answer["answer"])
    return str(answer)


async def read_rows(target: MemoryTarget, question: str) -> object:
    """Structured (XRESPONSE) read; the raw reader result, parsed elsewhere."""
    async with open_client(target) as client:
        instance = client.instance(require_instance_id(target))
        result = await with_retries(
            f"{target.name} structured read",
            lambda: instance.read(question, read_mode=ReadMode.XRESPONSE, timeout=READ_TIMEOUT_SECONDS),
        )
    return result.reader_result
