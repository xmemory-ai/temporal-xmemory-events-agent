# temporal-xmemory-events-agent

Long-running agents on [Temporal](https://temporal.io) that research AI conferences, meetups and other events on the internet and keep everything they learn, and everything they are doing, in [xmemory](https://xmemory.ai).

## How it works

Two agents share the work through memory:

- The **Discovery** agent searches the web and directories for upcoming AI events, checks the events memory so it does not re-add known ones, and writes each new event there as `unprocessed` with its canonical name, website and a one-line discovery note.
- The **Processor** agent takes one unprocessed event, crawls its pages, writes the details (dates, venue, call for papers, registration, prices, topics) and marks the event `processed`, or `failed` with a note.

Both agents run on the OpenAI Agents SDK. Every model call, web fetch and memory operation is a durable Temporal activity, so a crashed or redeployed worker resumes where it stopped. Inside a stage the model decides what to do; the only fixed structure is the cycle.

Two xmemory instances hold the state, and both are written as plain prose that xmemory's extraction engine turns into records:

- `events`: `Event` (with its processing status), `Topic`, `TeamMember`, `CalendarDay`, and the `attendance` relation, which links a team member to an event on a day and is keyed on `(date, attendee)` so a person can attend only one event per day.
- `coordination`: `Source` notes (which sources are good or poor) and `Run` logs for every cycle and stage.

An always-alive `EventScoutWorkflow` entity wakes on a cadence or on demand and runs one cycle: open a `Run` on the board, run Discovery as a child workflow, read the unprocessed queue with one structured read, run one `ProcessEventWorkflow` child per event with bounded parallelism, close the `Run`, and continue as new so its history stays small. Signals: `run_now`, `instruct <text>` (queued into the next Discovery brief), `pause`, `resume`, `stop`. Query: `status`.

## Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/).
- The Temporal CLI for a local server: `temporal server start-dev` (UI on http://localhost:8233).
- An OpenAI API key in `OPENAI_API_KEY`.
- An xmemory API key for each instance (or one shared key), see below.

```bash
uv sync --dev
```

## Configuration

Copy `config.yml.template` to `config.yml` (gitignored). Secrets never live in the file: each memory target names the environment variable that holds its key.

```yaml
xmemory:
  events:
    url: https://api.stg.xmemory.ai      # unset -> XMEM_API_URL -> https://api.xmemory.ai
    api_key_env: XMEM_EVENTS_API_KEY     # unset or empty -> XMEM_API_KEY
    instance_id: ""                       # filled by `create-instances --write-config`
  coordination:
    url: https://api.stg.xmemory.ai
    api_key_env: XMEM_COORD_API_KEY
    instance_id: ""
openai:
  model: gpt-5.4-mini                       # verified against the OpenAI models list by `create-instances`
```

Every value resolves in this order: a CLI flag (`--events-url`, `--events-api-key-env`, `--events-instance-id`, and the same for `--coordination-*`), then `config.yml`, then the environment, then the library default. The two instances may live on different servers or accounts.

The `scout` section sets the cadence and the budgets: cycle interval, events processed per cycle, parallel processing, turns and fetches per stage, fetch window size, politeness delay between requests to one host.

## Setup

```bash
export OPENAI_API_KEY=...
export XMEM_API_KEY=...                    # shared fallback for both instances
uv run temporal-xmemory-events-agent create-instances --write-config
uv run temporal-xmemory-events-agent seed-board
```

`create-instances` creates both instances from `schema/events.yml` and `schema/coordination.yml`, with each schema's description as the instance description, and refuses to overwrite an id already in `config.yml` unless `--force`. `seed-board` writes `seeds/seed_board.md`, a starting list of sources for the Discovery agent, and can be re-run.

Team members and attendance are entered by people, never by the agents. `seeds/team.md` shows the sentences to use:

```bash
uv run temporal-xmemory-events-agent remember --target events "Alexander Gusak is a member of the xmemory team, role engineer."
uv run temporal-xmemory-events-agent remember --target events "Alexander Gusak attends NeurIPS 2026 on 2026-12-07."
```

## Running

```bash
temporal server start-dev                                   # terminal 1
uv run temporal-xmemory-events-agent worker                 # terminal 2
uv run temporal-xmemory-events-agent start                  # runs a first cycle at once, then every cycle_interval_hours
uv run temporal-xmemory-events-agent instruct "Focus on AI meetups in Berlin and London this month"
uv run temporal-xmemory-events-agent run-now
uv run temporal-xmemory-events-agent status
uv run temporal-xmemory-events-agent queue                  # the unprocessed events, as the workflow reads them
uv run temporal-xmemory-events-agent board "What did the latest runs do, and which sources are good?"
uv run temporal-xmemory-events-agent ask "Which AI conferences in Europe have a CFP deadline in the next 90 days?"
uv run temporal-xmemory-events-agent pause | resume | stop
```

`start --paused` starts the entity without a first cycle; `run-now` then runs one on demand. An instruction containing "process only" skips discovery for that cycle. In the Temporal UI each cycle shows the entity run, one Discovery child, the processing children, and the model, fetch, board and xmemory activities.

## How memory is written

The agents never emit schema JSON. They write prose and xmemory extracts the records, so the conventions in `src/temporal_xmemory_events_agent/agents/common.py` matter: the canonical event name (short name plus year) in every sentence, ISO dates, one write per event or small group, additive wording. The instance descriptions in the schema files repeat these conventions for any other agent connected to the same instances.

## Tests

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run pyright src tests
uv run pytest -m "not live"
```

There is no fake xmemory. Unit tests (cleaner, robots, fetch activity, parsing, briefs, config, schema structure) need no backend. Memory-backed tests need `XMEM_API_KEY` (and `XMEM_API_URL` unless the default server is meant): a session fixture creates throwaway instances from the two schemas, the tests run the real activities and workflows against them with a scripted model and fixture-backed web pages, and the instances are deleted afterwards (`--keep-instances` keeps them). Deep writes take tens of seconds, so that tier runs in minutes.

The `live` test additionally needs `OPENAI_API_KEY` and `OPENAI_MODEL`, runs a real model against the real web on throwaway instances, and costs money:

```bash
OPENAI_MODEL=gpt-5.4-mini uv run pytest -m live
```

## Sharp edges

- Do not run the worker with `async with Worker(...)`. With a plugin that closes an HTTP client in its run context, the SDK cancels the worker's run task while that close is still in flight and then cancels the caller. `worker.py` and the test harness start `worker.run()` in a task, await `worker.shutdown()`, then await the run task.
- The entity initialises its state in an `@workflow.init` constructor, because Temporal runs signal handlers that arrive with the first workflow task before `run` starts.
- The `xmemory-temporal` plugin registers fixed activity names, so one worker can bind it to one instance. The coordination instance uses the small `board_read` / `board_write` activities in `memory/board_activities.py` instead.

## Layout

```
schema/            XMD schemas of the two instances
seeds/             seed knowledge for the board and the team-member template
src/temporal_xmemory_events_agent/
  run.py           CLI entrypoint
  config.py        config.yml + environment + flags -> Settings
  memory/          targets, instance admin, board activities and handle, structured-read parsing, queries
  web/             page cleaning (JSON-LD event data, main text, feeds) and robots.txt
  activities/      the web fetch activity and the activity names
  agents/          instructions, briefs, tools and the two agent definitions
  workflows/       the entity, the Discovery stage and the per-event Processing stage
  worker.py        client with both plugins, worker with all workflows and activities
tests/             unit tests, real-backend tests with throwaway instances, the live test
```
