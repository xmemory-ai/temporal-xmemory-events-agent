"""Command-line entrypoint. Run from the repository root:

    uv run temporal-xmemory-events-agent <subcommand> [options]

Every subcommand accepts --config and per-target overrides (--events-url, --events-api-key-env,
--events-instance-id, and the same for --coordination-*), which win over config.yml.
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from temporalio.common import WorkflowIDConflictPolicy

from temporal_xmemory_events_agent.config import (
    DEFAULT_CONFIG_PATH,
    Overrides,
    load_dotenv,
    load_settings,
    write_instance_ids,
)
from temporal_xmemory_events_agent.dto.settings import Settings
from temporal_xmemory_events_agent.dto.targets import MemoryTarget
from temporal_xmemory_events_agent.errors import ConfigurationError
from temporal_xmemory_events_agent.memory import admin
from temporal_xmemory_events_agent.memory.schemas import DEFAULT_SCHEMA_DIR, load_schema
from temporal_xmemory_events_agent.memory.targets import resolve_target
from temporal_xmemory_events_agent.memory.queries import UNPROCESSED_EVENTS
from temporal_xmemory_events_agent.memory.xresponse import event_rows
from temporal_xmemory_events_agent.dto.scout import ScoutInput
from temporal_xmemory_events_agent.worker import connect, run_worker, stage_settings
from temporal_xmemory_events_agent.workflows.scout import EventScoutWorkflow
from temporal_xmemory_events_agent.openai_models import verify_model

logger = logging.getLogger(__name__)

DEFAULT_SEEDS_DIR = Path("seeds")
TARGET_NAMES = ("events", "coordination")


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="configuration file (default: config.yml)")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    for name in TARGET_NAMES:
        parser.add_argument(f"--{name}-url", dest=f"{name}_url", help=f"xmemory API URL of the {name} memory")
        parser.add_argument(
            f"--{name}-api-key-env", dest=f"{name}_api_key_env", help=f"env var holding the {name} memory key"
        )
        parser.add_argument(f"--{name}-instance-id", dest=f"{name}_instance_id", help=f"{name} instance id")


def _overrides(ns: argparse.Namespace) -> Overrides:
    overrides: Overrides = {}
    for name in TARGET_NAMES:
        for field in ("url", "api_key_env", "instance_id"):
            overrides[f"xmemory.{name}.{field}"] = getattr(ns, f"{name}_{field}", None)
    return overrides


def _settings(ns: argparse.Namespace) -> Settings:
    return load_settings(ns.config, _overrides(ns))


def _target(settings: Settings, name: str) -> MemoryTarget:
    return resolve_target(name, getattr(settings.xmemory, name))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="temporal-xmemory-events-agent", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-instances", help="create the events and coordination instances from the schemas")
    _add_common_options(p)
    group = p.add_mutually_exclusive_group()
    group.add_argument("--events-only", action="store_true")
    group.add_argument("--coordination-only", action="store_true")
    p.add_argument("--write-config", action="store_true", help="record the new ids in the config file")
    p.add_argument("--force", action="store_true", help="create even when the config already names an instance")
    p.add_argument("--cluster-id", help="cluster to create on (needed only when the account has several)")
    p.add_argument("--name-prefix", default="ai-events", help="instance names are <prefix>-events / -coordination")
    p.add_argument("--schema-dir", default=str(DEFAULT_SCHEMA_DIR))
    p.add_argument("--skip-model-check", action="store_true", help="do not verify openai.model")

    p = sub.add_parser("seed-board", help="write the seed knowledge (candidate sources) to the coordination memory")
    _add_common_options(p)
    p.add_argument("--seeds-dir", default=str(DEFAULT_SEEDS_DIR))

    p = sub.add_parser("remember", help="write free text to a memory (team members, attendance, notes)")
    _add_common_options(p)
    p.add_argument("--target", choices=TARGET_NAMES, required=True)
    p.add_argument("--deep", action="store_true", help="deep extraction (slower, more thorough)")
    p.add_argument("text")

    p = sub.add_parser("worker", help="run the Temporal worker (workflows, activities, both memory plugins)")
    _add_common_options(p)

    p = sub.add_parser("queue", help="list the unprocessed events, with the read the workflow itself uses")
    _add_common_options(p)

    p = sub.add_parser("start", help="start the entity workflow (no-op when it is already running)")
    _add_common_options(p)
    p.add_argument("--paused", action="store_true", help="start paused; use run-now or resume later")
    for name, help_text in (
        ("run-now", "run a cycle now"),
        ("pause", "pause the cadence after the current cycle"),
        ("resume", "resume the cadence"),
        ("stop", "stop after the current cycle"),
        ("status", "show the entity's state"),
    ):
        p = sub.add_parser(name, help=help_text)
        _add_common_options(p)
    p = sub.add_parser("instruct", help="queue an operator instruction for the next cycle")
    _add_common_options(p)
    p.add_argument("text")

    p = sub.add_parser("ask", help="ask the events memory a question")
    _add_common_options(p)
    p.add_argument("question")

    p = sub.add_parser("board", help="ask the coordination memory a question")
    _add_common_options(p)
    p.add_argument("question")
    return parser


async def cmd_create_instances(ns: argparse.Namespace) -> int:
    settings = _settings(ns)
    if not ns.skip_model_check:
        await verify_model(settings.openai.model)
    selected = [
        n
        for n in TARGET_NAMES
        if not (ns.events_only and n != "events") and not (ns.coordination_only and n != "coordination")
    ]
    created: dict[str, str] = {}
    for name in selected:
        target = _target(settings, name)
        if target.instance_id and not ns.force:
            raise ConfigurationError(
                f"config already names a {name} instance ({target.instance_id}); pass --force to create another"
            )
        schema = load_schema(name, ns.schema_dir)
        created[name] = await admin.create_instance(target, schema, f"{ns.name_prefix}-{name}", ns.cluster_id)
        print(f"{name}={created[name]}")
    if ns.write_config:
        write_instance_ids(ns.config, events=created.get("events"), coordination=created.get("coordination"))
        logger.info("recorded the new instance ids in %s", ns.config)
    return 0


async def cmd_seed_board(ns: argparse.Namespace) -> int:
    settings = _settings(ns)
    path = Path(ns.seeds_dir) / "seed_board.md"
    if not path.exists():
        raise ConfigurationError(f"seed file not found: {path}")
    write_id = await admin.write_text(_target(settings, "coordination"), path.read_text())
    print(f"write_id={write_id}")
    return 0


async def cmd_remember(ns: argparse.Namespace) -> int:
    settings = _settings(ns)
    write_id = await admin.write_text(_target(settings, ns.target), ns.text, deep=ns.deep)
    print(f"write_id={write_id}")
    return 0


async def cmd_queue(ns: argparse.Namespace) -> int:
    settings = _settings(ns)
    rows = event_rows(await admin.read_rows(_target(settings, "events"), UNPROCESSED_EVENTS))
    for row in rows:
        print(f"{row.name} | {row.website} | discovered {row.discovered_at} | {row.discovery_note}")
    print(f"{len(rows)} unprocessed event(s)")
    return 0


ENTITY_COMMANDS = ("start", "run-now", "pause", "resume", "stop", "status", "instruct")


async def cmd_entity(ns: argparse.Namespace) -> int:
    settings = _settings(ns)
    client = await connect(settings)
    workflow_id = settings.temporal.workflow_id
    if ns.command == "start":
        await client.start_workflow(
            EventScoutWorkflow.run,
            ScoutInput(settings=stage_settings(settings), paused=ns.paused),
            id=workflow_id,
            task_queue=settings.temporal.task_queue,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )
        print(f"entity workflow {workflow_id} is running on task queue {settings.temporal.task_queue}")
        return 0
    handle = client.get_workflow_handle(workflow_id)
    if ns.command == "status":
        print(json.dumps((await handle.query(EventScoutWorkflow.status)).model_dump(), indent=2))
        return 0
    if ns.command == "instruct":
        await handle.signal(EventScoutWorkflow.instruct, ns.text)
    else:
        signal = {
            "run-now": EventScoutWorkflow.run_now,
            "pause": EventScoutWorkflow.pause,
            "resume": EventScoutWorkflow.resume,
            "stop": EventScoutWorkflow.stop,
        }[ns.command]
        await handle.signal(signal)
    print(f"sent {ns.command} to {workflow_id}")
    return 0


async def cmd_ask(ns: argparse.Namespace, target_name: str) -> int:
    settings = _settings(ns)
    print(await admin.read_answer(_target(settings, target_name), ns.question))
    return 0


async def _main_impl(argv: list[str] | None) -> int:
    ns = build_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, ns.log_level), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    loaded = load_dotenv()
    if loaded:
        logger.info("loaded %s from .env", ", ".join(loaded))
    if ns.command == "create-instances":
        return await cmd_create_instances(ns)
    if ns.command == "seed-board":
        return await cmd_seed_board(ns)
    if ns.command == "remember":
        return await cmd_remember(ns)
    if ns.command == "worker":
        await run_worker(_settings(ns))
        return 0
    if ns.command == "queue":
        return await cmd_queue(ns)
    if ns.command in ENTITY_COMMANDS:
        return await cmd_entity(ns)
    if ns.command == "ask":
        return await cmd_ask(ns, "events")
    if ns.command == "board":
        return await cmd_ask(ns, "coordination")
    raise ConfigurationError(f"unknown command {ns.command!r}")


def main(argv: list[str] | None = None) -> int:
    try:
        return asyncio.run(_main_impl(argv))
    except ConfigurationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
