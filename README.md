# Gitforce

**Autonomous, Human-Governed Software Engineering Agent**

Gitforce is a multi-agent AI software engineering platform. Point it at a
GitHub repository and an issue, and it autonomously runs an engineering
workflow: it analyzes the codebase and the issue, plans and implements the
requested change, runs tests, linting, type checking and security scans, opens
a pull request from a controlled fork/workspace, and monitors reviewer feedback
to re-run the workflow when a reviewer requests changes.

The system is **human-governed**: Gitforce never merges a pull request
automatically — a human always reviews and merges.

## Features

- **Multi-agent workflow (LangGraph)** — repository analysis, requirements,
  planning, coding, testing, failure analysis, security review, code review,
  judge, PR delivery, and a reviewer-feedback re-engineering loop.
- **Sandboxed execution** — generated code runs in a Docker sandbox (or a local
  fallback for development) with CPU/memory/network isolation and a command
  allowlist.
- **Retrieval-Augmented Generation (RAG)** — indexes the cloned repository and
  retrieves relevant context for the planner.
- **Agent harness** — every agent run is wrapped with permissions, token/iteration
  budgets, retries, timeouts, secret redaction, and an audit trail.
- **Human-in-the-loop** — pauses for clarification on ambiguous requirements and
  requires manual approval before any delivery.
- **Observability** — OpenTelemetry tracing, Prometheus metrics, and a live
  progress dashboard.
- **Web UI** — submit a task, watch progress live over WebSocket, and review the
  final result from the browser.

## How it works

```
You paste a GitHub repo + issue URL
        │
        ▼
   Gitforce analyzes the repo & issue
        │
        ▼
   Plans → Implements → Tests (sandbox) → Fixes → Reviews → Judges
        │
        ▼
   Opens a Pull Request from a fork/workspace
        │
        ▼
   Monitors reviewer feedback → re-engineering loop (capped)
```

## Architecture

A thin web frontend (vanilla JS SPA served by FastAPI) talks to a FastAPI +
LangGraph backend over REST and WebSocket. The backend is the source of truth;
agents are gated by an execution harness and run code inside sandboxes.

## Development Status

Following the phased plan in `Requirement.md`:

- [x] **Phase 1 — Core Backend**
  - FastAPI application
  - Task creation with GitHub URL validation
  - GitHub issue / repository retrieval
  - Basic persistent task state
  - WebSocket progress streaming
- [x] **Phase 2 — Single Agent**
  - LLM provider abstraction (OpenAI / Anthropic / Gemini / Groq / local / mock)
  - Model router by task complexity and type
  - Versioned prompt management
  - Repository analysis agent (clone + structure scan)
  - Issue / requirements analysis agent
  - Sandboxed execution (Docker + local fallback, command allowlist)
  - Basic coding workflow (analysis → plan → sandbox smoke)
- [x] **Phase 3 — LangGraph**
  - LangGraph supervisor graph with persistent checkpoints
  - Structured `ForgeState` (section 34) threaded through nodes
  - Conditional routing (ambiguous requirements → human clarification)
  - Retry policy for transient failures + categorized failure handling
  - Human-in-the-loop `interrupt()` + resume with clarification answer
- [x] **Phase 4 — Multi-Agent System**
  - Coding Agent writes real file changes into the workspace
  - Testing Agent runs pytest/ruff/mypy inside a sandbox (section 19)
  - Failure/fix loop: failed tests → failure analyzer → re-code, capped at 5 (section 20)
  - Security Agent: static scan + LLM interpretation (section 21)
  - Review Agent: independent code review (section 22)
  - Judge Agent: LLM-as-Judge gates delivery, loops back to coder on failure (sections 23, 43)
- [x] **Phase 5 — RAG**
  - Repository indexing into version-aware `document_chunks` (sections 11.1, 39)
  - Code-aware chunking: Python AST splits classes/functions/methods; line-based fallback (11.2)
  - Embedding provider abstraction — OpenAI API or deterministic hash provider (offline/dev)
  - Hybrid retrieval: vector search + BM25-lite keyword search merged by reciprocal rank fusion, then reranked with symbol boosts (11.3)
  - Metadata filtering (path/chunk type/language/symbol) + context assembly for prompts
  - Wired into the graph: repo indexed after clone, planner receives retrieved context
- [x] **Phase 6 — MCP**
  - Four MCP servers: GitHub, Repository, Execution, Documentation (section 17)
  - Tool registry (`MCPRegistry`) with a permission-gated dispatch — no call bypasses it
  - Permission model: per-category levels (read/execute/write) restricted by agent, plus an always-blocked denylist for high-impact tools (push, PR, fork) (section 44)
  - `MCPClient` facade agents use; coder node lists files through it
  - `build_registry()` assembles servers over the cloned workspace
- [x] **Phase 7 — Agent Harness**
  - `AgentHarness` wraps every agent execution: permissions, budgets, retries, timeouts, guardrails, audit (section 15)
  - String permission system (`harness/permissions.py`, section 16); dangerous perms (merge/secret/production/db-write) denied by default (44)
  - Token + iteration + wall-clock budgets (`budgets.py`); exponential-backoff retry policy (`retries.py`, 46)
  - Guardrails: secret redaction, path-traversal prevention, command allowlist (`guardrails.py`, 44)
  - `HarnessProvider` wraps LLM calls to enforce budgets and redact secrets before they reach the model
  - Audit logging persisted to `audit_logs` (`harness/audit.py`); MCP grants derived from harness permissions (17)
  - Coder node runs plan/implement through the harness; `AgentContext.harness_for()` builds task-bound harnesses
- [x] **Phase 8 — PR Delivery**
  - `GitWorktree` runner: branch creation, `git add -A`, commits, diff stat/body (`app/github/git.py`)
  - GitHubClient extended: `create_fork`, `create_branch` (from default branch SHA), `create_pull_request`, `get_pull_request`
  - `DeliveryAgent` builds the PR description from the section 25 template (LLM + deterministic fallback)
  - `TaskReport` generator (`app/services/report.py`) consolidates all agent outputs for the PR + dashboard
  - `delivery_node` (Phase 8) runs fork → branch → commit → push → PR through the harness under `GIT_PUSH` permission; non-fatal on GitHub failure
  - Graph routing: judge-ready → `delivery` → `finalize`
- [x] **Phase 9 — Reviewer Feedback Loop**
  - `FeedbackAnalysis` model + `FeedbackCategory` enum (approval, general_discussion, question, minor_requested_change, implementation_bug, security_concern, architecture_concern, requirement_change, unrelated_suggestion) — section 26
  - `FeedbackAnalyzer` agent (`app/agents/feedback.py`) classifies PR reviewer comments; `requires_replanning` flags a fundamental design problem (section 27)
  - GitHubClient extended: `list_pull_request_comments`, `list_issue_comments_for_pr`, `update_pull_request`, `comment_on_pull_request` for PR polling/updates
  - `GitWorktree` extended: `ensure_branch` (resumes an existing branch on re-planning cycles), `has_changes`, `current_sha`
  - `feedback_node` polls PR comments, classifies feedback, records `pr_iterations` history (section 29), and emits `feedback.*` events
  - Re-engineering loop: `delivery` → `feedback` → `route_after_feedback` → re-plan (`repository`) or `finalize`; capped by `max_feedback_iterations` (default 3) — routes through full re-planning, never a blind patch (section 28)
  - Requirements node merges reviewer feedback into the regenerated requirements
- [x] Phase 10 — Evaluation
  - Cost tracking: harness records per-call `Usage` (model/provider/tokens/cost/latency) through `HarnessProvider`; `UsageService` persists into `task.state["usage"]` with its own DB session; agents are constructed with a harness-wrapped provider (`AgentContext.wrapped_provider_for`) so every LLM call is budgeted + accounted
  - `app/evaluation/` package: `TaskEvaluation`/`EvaluationSummary` models covering section 42 metrics (task success rate, test pass rate, planning/code quality, security, reviewer acceptance, iteration count, cost per task, time per task)
  - `EvaluationService` derives per-task metrics from persisted state/report/event trace and aggregates summaries; trajectory evaluation reconstructs agent step ordering from events
  - RAG evaluation (`evaluate_retrieval`) computes recall@k / precision@k against known relevant files
  - LLM-as-Judge (`JudgeEvaluator`) + `BenchmarkCase`/`BenchmarkRun` for task benchmarks scored against acceptance criteria (section 43)
  - Evaluation API: `GET /api/evaluation/summary`, `GET /api/evaluation/{task_id}`, `GET /api/evaluation?task_ids=a,b`
- [x] Phase 11 — Observability
  - OpenTelemetry tracing: `init_tracing()` configures the SDK from `otel_enabled` / `otel_exporter_otlp_endpoint`; in-process `DashboardSpanProcessor` + `SpanRecorder` always capture spans for the dashboard
  - Spans around HTTP requests (`ObservabilityMiddleware`), workflow runs, every graph node (`traced_node`), harnessed agent runs, and LLM calls (`AgentBase`); `record_exception` marks failures
  - Prometheus metrics (`Metrics` registry): tasks, workflow outcomes, agent calls/duration, tokens and estimated cost per agent, HTTP request duration — exposed at `GET /metrics`
  - Token/cost tracking surfaced to the dashboard: `GET /api/dashboard/metrics` (per-agent tokens/cost breakdown)
  - Agent execution visualization: `GET /api/dashboard/traces`, `/api/dashboard/traces/{trace_id}` (span timeline), `GET /api/dashboard/tasks` (per-task evaluation metrics + summary)
  - Tracing/metrics wired into the harness (`AgentHarness.run`, task_id attribute) and the workflow runner (workflow outcome counters)
- [x] Phase 12 — Production Hardening
  - GitHub App authentication (`app/github/app_auth.py`): RS256 app JWT → installation access tokens, cached until expiry, automatic fallback to a classic PAT; `GitHubClient.refresh_auth()` swaps tokens best-effort before delivery push
  - Docker isolation hardening (`app/execution/docker.py`): `--network=none` (or default when enabled), read-only rootfs, `--security-opt=no-new-privileges`, pid limit; CPU/memory limits remain enforced
  - Secret management (`app/security/secrets.py`): registered secrets are redacted from logs/LLM prompts, and `GET /api/security/secrets` lists masked descriptors only
  - Rate limiting (`app/security/rate_limit.py`): per-client-IP token bucket (burst + refill) returning `429` with `Retry-After`
  - Structured logging (`app/security/logging.py`): JSON formatter + secret-scrubbing filter, wired into app startup
  - Failure recovery (`app/security/recovery.py`): transient-error classification with exponential-backoff retries for GitHub discovery; idempotent task creation (same repo+issue returns the existing task)
- [x] Frontend (Requirement section 5) — `frontend/` SPA served by FastAPI
  - Task creation form (5.1): repo URL, issue URL, Start button, and optional target branch / model / max iterations / test execution mode / approval mode via `POST /api/tasks`
  - Live progress dashboard (5.2/5.3): status, current stage, elapsed time, completed/failed stages, retries, and workflow progress over WebSocket (`/ws/tasks/{id}`)
  - Final results view (5.4): PR link, summary, test/security/evaluation scores
  - Routes: `#/create`, `#/tasks`, `#/tasks/:id`, `#/metrics`; static assets under `/static`, app root at `/`

## Installation

### Prerequisites

- Python 3.12+
- [Docker](https://docs.docker.com/get-docker/) (for Postgres + Redis; optional
  for a quick local run with SQLite)
- GitHub credentials (a GitHub App, or a Personal Access Token)
- An LLM API key (OpenAI, Anthropic, Gemini, or Groq)

### 1. Clone and install

```bash
git clone <your-gitforce-repo-url> gitforce
cd gitforce
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure

```bash
cp .env.example .env
# edit .env — set your database, GitHub, and LLM credentials (see below)
```

At minimum you need:

| Variable | Purpose |
| -------- | ------- |
| `GITFORCE_DATABASE_URL` | Postgres connection string |
| `GITFORCE_GITHUB_APP_ID` + private key + installation id (or `GITFORCE_GITHUB_TOKEN`) | GitHub auth for discovery & PRs |
| `GITFORCE_OPENAI_API_KEY` (or Anthropic/Google/Groq) | LLM provider key |
| `GITFORCE_LLM_PROVIDER` | which provider to use (`openai`, `anthropic`, `google`, `groq`, `local`, `mock`) |

> All settings are read with a `GITFORCE_` prefix (e.g. `GITFORCE_MODEL_FAST`).
> For a quick local run without Docker you can point `GITFORCE_DATABASE_URL` at
> SQLite, e.g. `sqlite+aiosqlite:///./gitforce.db`.

### 3. Start the database (Postgres + Redis)

```bash
docker compose up -d db redis
```

### 4. Run migrations

```bash
alembic upgrade head
```

### 5. Start the server

```bash
uvicorn gitforce.app.main:app --reload
```

Open <http://localhost:8000/> — the web UI loads here.

## Usage

### Using the web UI

1. Open <http://localhost:8000/>.
2. Go to **New Task** and paste a GitHub **repository URL** and **issue URL**.
   Optionally set the target branch, model, max iterations, test execution
   mode, or approval mode.
3. Click **Start Task**.
4. Watch the **live progress dashboard** — current stage, elapsed time,
   completed/failed stages, retries, and a realtime event log (WebSocket).
5. When the task completes, view the **final result**: PR link, summary,
   test/security/evaluation scores.

### Using the API directly

```bash
# Create a task
curl -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"repository_url":"https://github.com/org/repo",
       "issue_url":"https://github.com/org/repo/issues/12"}'

# → {"task_id":"...","status":"queued"}

# Check status
curl http://localhost:8000/api/tasks/<task_id>

# Final report / PR
curl http://localhost:8000/api/tasks/<task_id>/report
curl http://localhost:8000/api/tasks/<task_id>/pr
```

### Development mode without API keys

Set `GITFORCE_LLM_PROVIDER=mock` and `GITFORCE_SANDBOX_BACKEND=local` in `.env`
to run the workflow end-to-end with a deterministic mock model and no Docker —
useful for local development and tests.

## Tests

```bash
pytest
```

Run lint/typecheck:

```bash
ruff check gitforce alembic
mypy gitforce --ignore-missing-imports
```

## API

| Method | Path                          | Description                    |
| ------ | ----------------------------- | ------------------------------ |
| GET    | `/`                           | Web UI (SPA)                   |
| GET    | `/health`                     | Health check                   |
| POST   | `/api/tasks`                  | Create a task                  |
| GET    | `/api/tasks`                  | List tasks                     |
| GET    | `/api/tasks/{task_id}`        | Task state                     |
| GET    | `/api/tasks/{task_id}/events` | Task event history             |
| GET    | `/api/tasks/{task_id}/report` | Final report                   |
| GET    | `/api/tasks/{task_id}/pr`     | PR details                     |
| POST   | `/api/tasks/{task_id}/resume` | Resume a paused workflow       |
| POST   | `/api/tasks/{task_id}/cancel` | Cancel a running workflow      |
| WS     | `/ws/tasks/{task_id}`         | Stream task events (realtime)  |
| GET    | `/api/evaluation/summary`     | Evaluation summary             |
| GET    | `/api/evaluation/{task_id}`   | Per-task evaluation            |
| GET    | `/api/dashboard/tasks`        | Dashboard task metrics         |
| GET    | `/api/dashboard/traces`       | Recent traces                  |
| GET    | `/api/dashboard/metrics`      | Token/cost per agent           |
| GET    | `/metrics`                    | Prometheus metrics             |
| GET    | `/api/security/secrets`       | Masked secret descriptors      |

## Frontend Routes

| Route            | View                     |
| ---------------- | ------------------------ |
| `#/create`       | Start a new task (5.1)   |
| `#/tasks`        | List tasks               |
| `#/tasks/:id`    | Live progress + result   |
| `#/metrics`      | Token/cost metrics       |

## Project Layout

```
gitforce/
├── app/
│   ├── main.py            # FastAPI entrypoint
│   ├── api/               # REST routes + WebSocket
│   ├── agents/            # repository / requirements / coder / planner agents
│   ├── config/            # pydantic-settings
│   ├── database/          # SQLAlchemy models/session
│   ├── execution/         # sandbox (docker/local) + command allowlist
│   ├── github/            # GitHub client + URL parsing
│   ├── llm/               # providers, model router, LLM models
│   ├── orchestration/     # LangGraph graph, state, nodes, checkpointer, runner
│   ├── services/          # task orchestration services
│   ├── evaluation/        # evaluation metrics + benchmark judge
│   ├── observability/     # OpenTelemetry tracing + Prometheus metrics
│   ├── security/          # rate limiting, secrets, structured logging
│   └── ...                # rag, harness, mcp (phases 5+)
├── frontend/              # Web UI SPA (index.html, styles.css, app.js)
├── prompts/               # versioned prompt templates
├── tests/
├── docker-compose.yml
├── pyproject.toml
└── .env.example
```

## License

Proprietary. See the project license for details.