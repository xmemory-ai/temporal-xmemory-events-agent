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

## Step-by-step guide

All commands run from the repository root. Steps marked *once* are setup and need not be repeated.

### 1. Install (once)

You need Python 3.12+, [uv](https://docs.astral.sh/uv/), the [Temporal CLI](https://docs.temporal.io/cli), an OpenAI API key and an xmemory API key.

```bash
uv sync --dev
uv tool install xmemcli        # the xmemory CLI, used to create the instances in step 4
```

### 2. Credentials in `.env` (once)

Create a gitignored `.env` in the repository root. Every command loads it before anything else and never overrides a variable that is already exported. Each memory can name its own key variable in `config.yml`; `XMEM_API_KEY` is the shared fallback. Nothing secret goes into `config.yml`.

```bash
# .env
export XMEM_API_KEY=xmem_...
export OPENAI_API_KEY=sk-...
```

The tests do not read `.env`; export the variables in the terminal that runs them (see Tests below).

### 3. Configure (once)

Copy the template and set the model. Every value resolves in this order: a CLI flag (`--events-url`, `--events-api-key-env`, `--events-instance-id`, and the same for `--coordination-*`), then `config.yml`, then the environment, then the library default. The two instances may live on different servers or accounts.

```bash
cp config.yml.template config.yml
```

```yaml
xmemory:
  events:
    url: https://api.xmemory.ai          # unset -> XMEM_API_URL -> https://api.xmemory.ai
    api_key_env: XMEM_EVENTS_API_KEY     # unset or empty -> XMEM_API_KEY
    instance_id: ""                       # filled in step 4
  coordination:
    url: https://api.xmemory.ai
    api_key_env: XMEM_COORD_API_KEY
    instance_id: ""
openai:
  model: gpt-5.4-mini                       # verified against the OpenAI models list by `create-instances`
```

The `scout` section sets the cadence and the budgets: cycle interval, events processed per cycle, parallel processing, turns and fetches per stage, fetch window size, politeness delay between requests to one host.

### 4. Create the instances and seed the board (once)

With the xmemory CLI, as the [agent onboarding prompt](https://xmemory.ai/agent-onboarding-prompt.txt) prescribes: it authenticates with the same `XMEM_API_KEY`, validates the XMD, creates each instance with the schema's conventions as its description, and prints connect instructions for agent surfaces. Paste the two ids into `config.yml`.

```bash
xmemcli xmd validate schema/events.yml
xmemcli xmd validate schema/coordination.yml
xmemcli instance create --name "AI Events" --schema-file schema/events.yml
xmemcli instance create --name "Events Agent Coordination" --schema-file schema/coordination.yml
```

The project's own command does the same through the client library and records the ids in `config.yml` for you (it refuses to overwrite an id already there unless `--force`):

```bash
uv run temporal-xmemory-events-agent create-instances --write-config
```

Then seed the board, a starting list of sources for the Discovery agent (re-runnable):

```bash
uv run temporal-xmemory-events-agent seed-board
```

### 5. Team members and attendance (optional)

People enter these, one sentence per fact, with the event in its canonical name and the day as an ISO date; the agents never write them. `seeds/team.md` shows the sentences to use.

```bash
uv run temporal-xmemory-events-agent remember --target events "Alexander Gusak is a member of the xmemory team, role engineer."
uv run temporal-xmemory-events-agent remember --target events "Alexander Gusak attends NeurIPS 2026 on 2026-12-07."
```

### 6. Temporal dev server (terminal 1)

The UI is at http://localhost:8233. By default the dev server keeps its state in memory, so a restart forgets the entity workflow and you run `start` again afterwards. For durable runs give it a database file: workflow histories then survive server restarts, the entity keeps its cadence, cycle counter and pending instructions, and a worker that comes back simply continues the in-flight cycle.

```bash
temporal server start-dev --db-filename temporal.db
```

`temporal.db` and its sidecar files are gitignored. Delete the file to start from a clean slate.

### 7. Worker (terminal 2)

Runs the workflows, the fetch and board activities, and both memory plugins. Ctrl-C drains it and stops.

```bash
uv run temporal-xmemory-events-agent worker
```

### 8. Start the entity (terminal 3)

`start` runs a first cycle at once and then one every `cycle_interval_hours`. `start --paused` waits for `run-now` instead. A cycle spends OpenAI tokens: a few Discovery turns plus one Processor run per queued event, capped by `max_events_processed_per_cycle`.

```bash
uv run temporal-xmemory-events-agent start
```

### 9. Steer and watch

| Command | What it does |
| --- | --- |
| `instruct "…"` | Queues an operator instruction for the next cycle's Discovery brief. One containing `process only` skips discovery that cycle. |
| `run-now` | Runs a cycle immediately, also while paused. |
| `status` | State, cycle number, last run id and summary, next due time, pending instructions. |
| `queue` | The unprocessed events, read exactly the way the workflow reads them. |
| `ask "…"` | A plain-language question to the events memory. |
| `board "…"` | A plain-language question to the coordination memory. |
| `pause` / `resume` | Suspends or restores the cadence after the current cycle. |
| `stop` | Ends the entity after the current cycle; `start` brings it back. |

```bash
uv run temporal-xmemory-events-agent instruct "Focus on AI meetups in Berlin and London this month"
uv run temporal-xmemory-events-agent run-now
uv run temporal-xmemory-events-agent status
uv run temporal-xmemory-events-agent queue
uv run temporal-xmemory-events-agent ask "Which AI conferences in Europe have a CFP deadline in the next 90 days?"
uv run temporal-xmemory-events-agent board "What did the latest runs do, and which sources are good?"
```

In the Temporal UI each cycle shows the `events-scout` run, one Discovery child, one processing child per event, and inside them the model, fetch, board and xmemory activities. Deep memory writes take tens of seconds each, so a cycle with several events takes a few minutes. The xmemory console shows Event and Run rows as they land.

## How memory is written

The agents never emit schema JSON. They write prose and xmemory extracts the records, so the conventions in `src/temporal_xmemory_events_agent/agents/common.py` matter: the canonical event name (short name plus year) in every sentence, ISO dates, one write per event or small group, additive wording. The instance descriptions in the schema files repeat these conventions for any other agent connected to the same instances.

## Tests

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run pyright src tests
uv run pytest -m "not live"
```

There is no fake xmemory. Unit tests (cleaner, robots, fetch activity, parsing, briefs, config, schema structure) need no backend. Memory-backed tests need `XMEM_API_KEY` exported (pytest does not read `.env`) and `XMEM_API_URL` unless the default server is meant: a session fixture creates throwaway instances from the two schemas, the tests run the real activities and workflows against them with a scripted model and fixture-backed web pages, and the instances are deleted afterwards (`--keep-instances` keeps them). Deep writes take tens of seconds, so that tier runs in minutes.

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
