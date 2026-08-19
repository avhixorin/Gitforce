# DEMO — Gitforce for a Product Manager

> **Audience:** Product Manager (e.g. Atlan, SWE intern interview)
> **Goal:** Show you can think like an engineer **and** a product person.
> **Length target:** 8–10 minutes live, with 5 minutes of questions.

A PM doesn't want to see lines of code — they want to see a **product**: who
it's for, what problem it solves, why it's trustworthy, and how it behaves in
the real world. This script walks you through Gitforce that way.

---

## 0. The 30-second pitch (open with this)

> "Gitforce is an autonomous software-engineering agent. You give it a GitHub
> repository and an issue, and it analyzes the codebase, plans the change,
> writes it, tests it, security-scans it, and opens a pull request — then
> watches reviewer feedback and re-iterates. The key decision I made: it's
> **human-governed**. It never merges anything by itself. Engineers stay in
> control — the agent does the work, the human makes the call."

Why this lands: **trust + control** is exactly the message data-platform PMs
(at Atlan especially) care about for AI. AI that acts *with* governance.

---

## 1. The problem (30 sec)

"Writing a code change is only 20% of the work. The other 80% is understanding
the codebase, planning, testing, fixing what breaks, reviewing, and keeping a
human in the loop. Gitforce automates that whole pipeline, not just the
'diff generation' part."

**Talking point:** most demo projects are toys — single agent, one prompt.
This is a **full workflow with tests, retries, review, and human approval**.
That's the difference between a demo and a product.

---

## 2. The demo script (5–6 min)

> **Before the interview:** run these two commands so the app is live and a
> task is already running — you'll show *in-progress* state, not just an empty
> form.

```bash
# terminal 1
source .venv/bin/activate
docker compose up -d db redis
alembic upgrade head
uvicorn gitforce.app.main:app --reload

# terminal 2 (kick off a task you can show mid-flight)
curl -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"repository_url":"https://github.com/octocat/Hello-World",
       "issue_url":"https://github.com/octocat/Hello-World/issues/1"}'
```

### Step A — Show the product (1 min)
Open `http://localhost:8000/`. Show the **New Task** page.

> "Here's the entry point. A user pastes a GitHub repo and an issue URL —
> optionally picking the target branch, model, iteration budget, or test
> mode. Notice the validation happens before anything is created. This is the
> *start of a workflow*, not a one-shot prompt."

### Step B — Show a task already running (1.5 min)
Open the task you started earlier (`#/tasks/<id>`).

> "This task is mid-flight right now. The dashboard shows the **live
> workflow**: repository analysis → requirements → planning → implementation
> → testing → security → review → judge → PR delivery. Green is done, the
> highlighted one is what's running right now. This updates over a WebSocket
> — the event log below is streaming real events as they happen."

**PM trigger:** "how do you know an agent is actually working vs stuck?" →
"Every stage emits events; there are retries and timeouts, and each step has a
budget. That's the observability story."

### Step C — The engineering-quality story (1.5 min)
Switch to the **Metrics** tab (`#/metrics`), or open
`/api/evaluation/summary`.

> "Because agents consume tokens and cost money, I track usage per agent —
> tokens and estimated cost per stage. I also run an evaluation pass per task:
> success rate, test pass rate, security, reviewer acceptance, cost per task,
> time per task. So this isn't a black box — you can measure whether the
> agent is getting better. That measurement loop is what turns a demo into a
> reliable system."

**PM trigger:** "what happens when it fails?" → "Tests run in an isolated
sandbox. If they fail, a failure analyzer names the root cause and the coder
retries, capped so it can't loop forever. If it exhausts the loop, the task is
marked failed with the reason — it never falsely claims success."

### Step D — The "human in the loop" moment (1 min)
Show the create form again and point at **Approval mode → manual**.

> "This is the governance feature. The default is automatic delivery, but a
> team can require manual approval before anything is pushed. And the agent
> pauses for clarification if requirements are ambiguous. The principle: the
> agent proposes, the human disposes."

### Step E — Close the loop (30 sec)
> "So to recap: this isn't 'an AI writes a function'. It's an **accountable
> engineering pipeline** — plan, implement, test, review, deliver, iterate on
> feedback — with humans in control, and with metrics so you can trust and
> measure it."

---

## 3. The architecture slide (for reference, not the demo)

Keep this in your back pocket for questions:

```
Web UI (SPA) ── REST + WebSocket ── FastAPI
                                       │
                                 LangGraph workflow
      repository → requirements → planner → coder → tester
        → failure/fix loop → security → review → judge
        → PR delivery → reviewer-feedback loop (capped)
                                       │
            ┌──────────────┬──────────┴───────────┬──────────────┐
            │              │                      │              │
      Agent Harness    RAG indexer           Sandbox        Evaluation
    (permissions,     (repo retrieval      (Docker/local,   (metrics,
     budgets, retries,  for context)       CPU/mem/network   cost, judge)
     audit, redaction)                     isolation)
```

- **Agent harness** — every agent call is gated: permissions, token budget,
  retries, timeout, secret redaction, audit trail.
- **Sandbox** — generated code runs isolated (CPU/memory/network limits, no
  arbitrary commands), so a bad agent output can't hurt the host.
- **LangGraph** — the workflow is a real stateful graph with checkpoints; it
  can pause, resume, and be restarted.

---

## 4. Talking points mapped to what a PM cares about

| PM concern | What you say | Where it lives |
| ---------- | ------------ | -------------- |
| **Trust** | "Human-governed: never auto-merges; manual approval mode; pauses for clarification." | `approval_mode`, `needs_clarification` node |
| **Reliability** | "Fix loop with failure analysis, capped; retries on transient errors; timeouts + budgets." | `failure_analyzer`, `RetryPolicy`, harness |
| **Observability** | "Live WebSocket progress, event log, traces, Prometheus metrics, per-task evaluation." | `/api/dashboard/*`, `/metrics`, WebSocket |
| **Safety** | "Sandboxed execution with network isolation; command allowlist; secret redaction." | `execution/`, harness guardrails |
| **Cost** | "Per-agent token/cost tracking, iteration budgets, evaluation cost-per-task." | `/api/dashboard/metrics`, `UsageService` |
| **Product quality** | "Thin SPA on a real API — not a Jupyter toy; URL validation; idempotent task creation." | `frontend/`, `POST /api/tasks` |
| **Extensibility** | "Provider abstraction (OpenAI/Anthropic/Gemini/Groq/local), versioned prompts, RAG retrieval." | `llm/`, `prompts/`, `rag/` |

---

## 5. Likely PM questions — and answers

**Q: What problem does this solve for a real team?**
> The 80/20 problem: most effort in shipping a change is context, planning,
> testing, and review — not writing the diff. Gitforce automates the pipeline
> and hands the human a ready-to-review PR with test results and an audit
> trail, so a team can spend review time on judgment, not mechanics.

**Q: Why did you make it "human-governed" instead of fully autonomous?**
> Full autonomy is risky: agents hallucinate, and they have no social context
> a human has. The safest design is an agent that does the whole pipeline but
> *never* makes the final call. That's also what makes it adoptable — teams
> trust it because they stay in control.

**Q: How do you know the agent's output is actually correct?**
> Three layers: (1) tests run in a sandbox and must pass before anything
> proceeds; (2) a security scan and an independent review agent + LLM judge
> gate delivery; (3) a per-task evaluation captures test pass rate, security,
> and judge scores so you can measure quality over time rather than assume it.

**Q: What happens when the AI fails or produces a bad PR?**
> It retries intelligently — a failure analyzer diagnoses the root cause and
> the coder re-attempts, up to a cap. If it still can't pass tests, the task
> is marked failed with the reason; it never claims success falsely. And since
> delivery requires `GIT_PUSH` permission, a bad output can't reach the repo
> without passing the gates.

**Q: How did you think about scale / production concerns?**
> I treated it as a real service: idempotent task creation, rate limiting,
> structured logging, secret redaction, GitHub App auth instead of PATs,
> Docker-isolated execution, and an Alembic-migrated Postgres schema. Those
> decisions are about deployability, not just demo-ability.

**Q: What would you build next / what's the biggest limitation?**
> Honest answer: the biggest gap is a reliable evaluation set — "does the
> agent actually fix real issues?" — which needs a benchmark of real issues
> with known-good fixes. Next I'd add: GitHub webhooks for automatic
> discovery (currently it's manual or scheduled), user auth/roles, and a
> queue/worker so long tasks don't depend on a single process.

---

## 6. Demo-day checklist

- [ ] `.env` configured (DB, GitHub, LLM), `alembic upgrade head` run
- [ ] Postgres + Redis up (`docker compose up -d db redis`)
- [ ] Server running (`uvicorn gitforce.app.main:app --reload`)
- [ ] One task already started so you can show *live in-progress* state
- [ ] Browser: `http://localhost:8000/` → New Task → open the running task → Metrics
- [ ] Practice the pitch out loud once (30s intro + Step A–E)
- [ ] Have `pytest` ready in a terminal in case they ask "does it have tests?" (155 passing)

**If the internet is unreliable during the interview:** the workflow also runs
fully offline with `GITFORCE_LLM_PROVIDER=mock` and
`GITFORCE_SANDBOX_BACKEND=local` — deterministic, no API keys, no Docker
required.