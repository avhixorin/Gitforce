# ForgeAI --- Autonomous, Human-Governed Software Engineering Agent

## 1. Project Overview

**ForgeAI** is a backend-first, multi-agent AI software engineering
platform that accepts a GitHub repository URL and GitHub issue URL,
analyzes the repository and issue, plans and implements the requested
change, runs tests and security checks, creates a pull request from a
controlled fork/workspace, monitors reviewer feedback, and can re-run
the engineering workflow when a reviewer provides actionable reasons for
requesting changes.

The system is intentionally **backend-heavy**. The frontend is a thin
control and observability layer whose primary responsibilities are:

1.  Accept a GitHub repository URL.
2.  Accept a GitHub issue URL.
3.  Start an engineering task.
4.  Display real-time task progress.
5.  Display the final PR and task report.
6.  Surface reviewer feedback and workflow status.

The core intelligence, orchestration, retrieval, tool execution, state
management, evaluation, security, and GitHub integration live in the
Python backend.

------------------------------------------------------------------------

# 2. Core Product Goal

Given:

-   a GitHub repository URL
-   a GitHub issue URL

ForgeAI should autonomously perform:

``` text
Repository Discovery
        ↓
Issue Understanding
        ↓
Repository RAG / Code Understanding
        ↓
Requirements Extraction
        ↓
Architecture Analysis
        ↓
Implementation Planning
        ↓
Code Generation / Modification
        ↓
Testing
        ↓
Security Analysis
        ↓
Code Review
        ↓
LLM-as-Judge Evaluation
        ↓
PR Generation
        ↓
Human Review
        ↓
Feedback Analysis
        ↓
Re-plan / Re-implement if required
        ↓
PR Update
```

The system must remain **human-governed**. ForgeAI must never merge a
pull request automatically.

------------------------------------------------------------------------

# 3. Design Principles

## 3.1 Backend First

The backend is the primary product. The frontend should remain
intentionally lightweight.

## 3.2 Agent Specialization

Do not use one monolithic agent for every operation. Use specialized
agents with explicit responsibilities.

## 3.3 Controlled Autonomy

Agents may inspect, reason, modify code in an isolated workspace,
execute tests, and create/update PRs, but repository merge authority
remains with humans.

## 3.4 Tool-Mediated Access

Agents should interact with external systems through a controlled tool
layer, preferably exposed through MCP servers.

## 3.5 Persistent State

Long-running agent workflows must survive failures, restarts, retries,
and human-review delays.

## 3.6 Evidence-Based Decisions

Agents should use repository code, issue requirements, documentation,
test results, tool outputs, and reviewer feedback rather than relying
exclusively on model-generated assumptions.

## 3.7 Observable Agent Execution

Every important agent step, tool call, model call, retrieval operation,
decision, retry, and state transition should be traceable.

------------------------------------------------------------------------

# 4. High-Level Architecture

``` text
                         ┌──────────────────────┐
                         │      Frontend        │
                         │                      │
                         │ Repo URL             │
                         │ Issue URL             │
                         │ Progress Dashboard   │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │      FastAPI         │
                         │      Backend         │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │   Task Manager       │
                         │   API / WebSocket    │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │   Agent Harness      │
                         │                      │
                         │ Permissions           │
                         │ Budgets               │
                         │ Retries               │
                         │ Timeouts              │
                         │ Guardrails            │
                         │ Context               │
                         │ Tool Access           │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │      LangGraph       │
                         │  Workflow Supervisor │
                         └──────────┬───────────┘
                                    │
             ┌──────────────────────┼──────────────────────┐
             │                      │                      │
             ▼                      ▼                      ▼
       Repository Agent       Requirements Agent      Planning Agent
             │                      │                      │
             └──────────────────────┼──────────────────────┘
                                    │
                                    ▼
                             Coding Agent
                                    │
                                    ▼
                            Testing Agent
                                    │
                                    ▼
                           Security Agent
                                    │
                                    ▼
                            Review Agent
                                    │
                                    ▼
                             Judge Agent
                                    │
                                    ▼
                             Delivery Agent
                                    │
                                    ▼
                               GitHub PR
                                    │
                                    ▼
                              Human Review
                                    │
                         ┌──────────┴──────────┐
                         │                     │
                     Approved              Changes
                         │                     │
                        DONE                   ▼
                                    Feedback Analyzer
                                              │
                                   ┌──────────┴──────────┐
                                   │                     │
                                Minor                 Re-plan
                                Change                   │
                                   │                     ▼
                                   └──────────────→ Workflow
```

------------------------------------------------------------------------

# 5. Frontend Requirements

The frontend should deliberately remain small.

## 5.1 Task Creation

The frontend must provide:

-   GitHub repository URL input
-   GitHub issue URL input
-   Start Task button
-   Validation for URLs
-   Optional configuration fields

Optional configuration:

-   target branch
-   model selection
-   maximum agent iterations
-   test execution mode
-   approval mode

## 5.2 Progress Dashboard

Display:

-   current task status
-   current agent
-   current workflow stage
-   elapsed time
-   completed stages
-   failed stages
-   retry count
-   tool calls
-   LLM calls
-   token usage
-   retrieved documents
-   test status
-   security status
-   PR status

Example:

``` text
ForgeAI Task #1024

Repository     my-org/my-project
Issue          #1842

Status         Running
Current Agent  Coding Agent
Elapsed        03:42

✓ Repository Analysis
✓ Requirements
✓ Architecture
✓ Planning
→ Implementation
○ Testing
○ Security
○ Review
○ PR
```

## 5.3 Live Updates

The frontend should receive task updates through:

-   WebSocket preferred
-   Server-Sent Events as fallback

The backend remains the source of truth.

## 5.4 Final Result

Display:

-   PR URL
-   PR title
-   PR status
-   summary of changes
-   tests
-   security findings
-   evaluation scores
-   task execution metrics
-   reviewer feedback
-   workflow iteration history

------------------------------------------------------------------------

# 6. Backend Requirements

The entire backend must be implemented in **Python**.

Recommended backend framework:

-   FastAPI
-   Pydantic
-   asyncio

The backend should be modular and service-oriented internally.

------------------------------------------------------------------------

# 7. Backend Technology Stack

## Core

-   Python 3.12+
-   FastAPI
-   Pydantic v2
-   Uvicorn
-   asyncio
-   httpx

## Agent Orchestration

-   LangChain
-   LangGraph
-   LangChain Core
-   Pydantic structured outputs

## MCP

-   MCP Python SDK
-   MCP clients
-   Custom ForgeAI MCP servers

## LLM

The application must use a provider abstraction rather than hard-coding
a single model.

Support should be designed for:

-   OpenAI
-   Anthropic
-   Google Gemini
-   Groq
-   OpenAI-compatible APIs
-   local models where practical

A model router should select models according to task complexity.

## Retrieval / RAG

-   PostgreSQL
-   pgvector
-   full-text/BM25 search
-   embedding model
-   reranker

Potential embedding models:

-   OpenAI embeddings
-   BGE
-   sentence-transformers

## Data

-   PostgreSQL
-   pgvector
-   Redis

Redis should be used for:

-   task coordination
-   caching
-   distributed locks
-   temporary state
-   event streaming where appropriate

## Execution

-   Docker
-   isolated containers
-   sandboxed execution
-   resource limits

## GitHub

-   GitHub REST API / GraphQL where useful
-   GitHub App authentication preferred
-   GitHub MCP server
-   Git operations through controlled execution

## Observability

-   OpenTelemetry
-   LangSmith and/or Arize Phoenix
-   structured logging
-   Prometheus-compatible metrics
-   Grafana optional

## Testing

-   pytest
-   pytest-asyncio
-   Ruff
-   mypy
-   coverage
-   integration tests
-   agent evaluation suite

## Infrastructure

Development:

-   Docker Compose

Production target:

-   Docker
-   Kubernetes optional
-   managed PostgreSQL
-   managed Redis

------------------------------------------------------------------------

# 8. Agent Architecture

ForgeAI must contain specialized agents.

## 8.1 Supervisor Agent

Responsibilities:

-   initialize the task
-   manage the workflow
-   delegate to specialized agents
-   evaluate agent outputs
-   decide transitions
-   handle retries
-   terminate failed workflows safely

The Supervisor should be implemented primarily using LangGraph.

------------------------------------------------------------------------

# 9. Repository Analysis Agent

Responsibilities:

-   clone/access the repository
-   identify language and framework
-   inspect project structure
-   identify entry points
-   identify configuration
-   identify testing framework
-   identify build system
-   identify architecture
-   identify important modules
-   identify relevant files
-   identify coding conventions

Output:

``` json
{
  "languages": [],
  "frameworks": [],
  "package_manager": "",
  "build_system": "",
  "test_framework": "",
  "architecture_summary": "",
  "important_files": [],
  "relevant_modules": [],
  "conventions": []
}
```

------------------------------------------------------------------------

# 10. Issue / Requirements Agent

Responsibilities:

-   retrieve the GitHub issue
-   understand the issue description
-   inspect issue comments
-   identify acceptance criteria
-   identify constraints
-   identify ambiguities
-   identify expected behavior
-   distinguish requirements from suggestions

Output:

``` json
{
  "problem": "",
  "requirements": [],
  "acceptance_criteria": [],
  "constraints": [],
  "assumptions": [],
  "ambiguities": [],
  "risk_factors": []
}
```

If requirements are too ambiguous, the workflow should be able to stop
and request human clarification.

------------------------------------------------------------------------

# 11. Repository RAG

ForgeAI must implement repository-aware RAG.

## 11.1 Indexing

The system should index:

-   source files
-   tests
-   README
-   documentation
-   configuration
-   API definitions
-   package manifests
-   architecture documents
-   issue history
-   relevant PRs

## 11.2 Code-Aware Chunking

Where possible, chunks should correspond to:

-   classes
-   functions
-   methods
-   interfaces
-   modules
-   configuration sections

Metadata should include:

``` json
{
  "repository": "",
  "commit_sha": "",
  "path": "",
  "language": "",
  "symbol": "",
  "chunk_type": "",
  "start_line": 0,
  "end_line": 0
}
```

## 11.3 Retrieval

Use hybrid retrieval:

``` text
Query
  ↓
Vector Search
  +
Keyword Search
  ↓
Merge
  ↓
Reranking
  ↓
Metadata Filtering
  ↓
Context Assembly
```

------------------------------------------------------------------------

# 12. Knowledge Graph

ForgeAI should maintain a lightweight repository knowledge graph.

Entities:

-   files
-   modules
-   classes
-   functions
-   tests
-   APIs
-   dependencies
-   configuration
-   issues
-   PRs

Relationships:

-   imports
-   calls
-   implements
-   tests
-   depends_on
-   exposes
-   modifies
-   related_to

The graph should help answer:

-   What depends on this function?
-   Which tests cover this module?
-   Which APIs use this class?
-   What could be affected by this change?

The knowledge graph may initially be represented in PostgreSQL rather
than requiring a dedicated graph database.

------------------------------------------------------------------------

# 13. Architecture / Planning Agent

Responsibilities:

-   combine issue requirements with repository understanding
-   inspect relevant code
-   identify affected components
-   propose implementation strategies
-   compare alternatives
-   choose an implementation strategy
-   create a detailed execution plan

Output:

``` json
{
  "summary": "",
  "approach": "",
  "alternatives_considered": [],
  "files_to_modify": [],
  "files_to_create": [],
  "files_to_delete": [],
  "implementation_steps": [],
  "testing_strategy": [],
  "risks": [],
  "rollback_strategy": ""
}
```

The plan becomes part of persistent task state.

------------------------------------------------------------------------

# 14. Coding Agent

Responsibilities:

-   implement the approved plan
-   inspect files before modifying them
-   make minimal changes
-   preserve existing conventions
-   avoid unrelated refactoring
-   write/update tests
-   explain implementation decisions

The Coding Agent must operate inside a controlled workspace.

It must not receive unrestricted production access.

------------------------------------------------------------------------

# 15. Agent Harness

ForgeAI must implement an Agent Harness around every agent execution.

Responsibilities:

-   tool registration
-   tool permission enforcement
-   token budgets
-   execution budgets
-   timeout handling
-   retry policies
-   context limits
-   state persistence
-   safety checks
-   structured outputs
-   tracing
-   audit logging

Example:

``` python
result = harness.execute(
    agent=coding_agent,
    task=task,
    permissions=[
        "repo.read",
        "workspace.read",
        "workspace.write",
        "tests.execute"
    ],
    max_iterations=20,
    timeout_seconds=600
)
```

------------------------------------------------------------------------

# 16. Tool Permission System

Tools must have explicit permissions.

Example:

``` text
repo.read
repo.issue.read
repo.pr.read
workspace.read
workspace.write
workspace.execute
git.branch.create
git.commit
git.push
pr.create
pr.update
pr.comment
```

Dangerous permissions:

``` text
repo.merge
production.execute
secret.read
database.write
```

must be denied by default.

------------------------------------------------------------------------

# 17. MCP Architecture

ForgeAI should use MCP as the standardized interface between agents and
external capabilities.

Potential MCP servers:

## GitHub MCP

Tools:

-   get_repository
-   get_issue
-   get_issue_comments
-   search_code
-   get_file
-   get_branch
-   create_fork
-   create_branch
-   push_changes
-   create_pull_request
-   get_pull_request
-   get_pull_request_reviews
-   get_review_comments
-   reply_to_comment
-   update_pull_request

## Repository MCP

Tools:

-   list_files
-   read_file
-   search_files
-   inspect_symbols
-   get_dependencies

## Execution MCP

Tools:

-   run_tests
-   run_linter
-   run_typecheck
-   run_build
-   run_security_scan

## Documentation MCP

Tools:

-   search_documentation
-   fetch_documentation

The MCP layer must not bypass the Agent Harness permission system.

------------------------------------------------------------------------

# 18. Sandbox Execution

All generated code must be tested in an isolated environment.

Requirements:

-   Docker isolation
-   CPU limits
-   memory limits
-   execution timeout
-   network restrictions
-   filesystem isolation
-   no access to production secrets

The sandbox should be disposable.

------------------------------------------------------------------------

# 19. Testing Agent

The Testing Agent must:

-   discover existing tests
-   run relevant tests first
-   run full test suite when appropriate
-   add missing tests
-   run unit tests
-   run integration tests where available
-   run lint
-   run type checking
-   run build

Output:

``` json
{
  "passed": true,
  "tests_run": 0,
  "tests_passed": 0,
  "tests_failed": 0,
  "coverage": 0,
  "lint_passed": true,
  "typecheck_passed": true,
  "build_passed": true,
  "failures": []
}
```

------------------------------------------------------------------------

# 20. Failure / Fix Loop

When tests fail:

``` text
Test Failure
    ↓
Failure Analyzer
    ↓
Identify Root Cause
    ↓
Coding Agent
    ↓
Run Tests Again
```

The loop must have a maximum iteration count.

Example:

``` text
MAX_FIX_ITERATIONS = 5
```

If the limit is reached, the workflow should stop and produce a failure
report.

------------------------------------------------------------------------

# 21. Security Agent

The Security Agent should inspect:

-   authentication
-   authorization
-   secrets
-   injection vulnerabilities
-   unsafe dependencies
-   command execution
-   path traversal
-   SSRF
-   insecure configuration
-   sensitive data handling
-   dependency vulnerabilities

Use static analysis tools where practical.

The LLM should interpret findings rather than being the sole security
mechanism.

------------------------------------------------------------------------

# 22. Code Review Agent

The Review Agent independently reviews the generated changes.

It should inspect:

-   correctness
-   maintainability
-   architecture
-   tests
-   edge cases
-   security
-   performance
-   consistency with existing code
-   scope creep

The reviewer should not blindly trust the Coding Agent.

------------------------------------------------------------------------

# 23. Judge Agent

The Judge Agent determines whether the task is ready for delivery.

Evaluation dimensions:

``` text
Requirements
Correctness
Code Quality
Tests
Security
Architecture
Scope
Regression Risk
```

Example:

``` json
{
  "ready": true,
  "requirements_score": 0.96,
  "correctness_score": 0.93,
  "quality_score": 0.91,
  "security_score": 0.98,
  "test_score": 0.95,
  "overall_score": 0.95,
  "blocking_issues": [],
  "recommendations": []
}
```

A failed Judge result sends the workflow back into the appropriate agent
rather than automatically continuing to PR creation.

------------------------------------------------------------------------

# 24. Delivery Agent

The Delivery Agent is responsible for delivering a completed change to
GitHub.

It should:

1.  Create/use a controlled fork or authorized workspace.
2.  Create a branch.
3.  Commit changes.
4.  Push the branch.
5.  Create a pull request.
6.  Generate the PR title.
7.  Generate the PR description.
8.  Attach test results.
9.  Attach security results.
10. Attach evaluation results.
11. Link the original issue.

The Delivery Agent must never merge the PR.

------------------------------------------------------------------------

# 25. Pull Request Documentation

Every PR generated by ForgeAI should contain:

``` text
## Summary

## Problem

## Requirements

## Implementation

## Architecture / Design

## Files Changed

## Tests

## Security Review

## Risks

## Alternatives Considered

## Agent Evaluation

## Validation Results

## Related Issue

## ForgeAI Task Report
```

The PR should be understandable to a human reviewer without opening the
ForgeAI dashboard.

------------------------------------------------------------------------

# 26. Reviewer Feedback Loop

ForgeAI should monitor the created PR for human feedback.

The system must distinguish:

-   approval
-   general discussion
-   question
-   minor requested change
-   implementation bug
-   security concern
-   architecture concern
-   requirement change
-   unrelated suggestion

------------------------------------------------------------------------

# 27. Feedback Analyzer Agent

The Feedback Analyzer must determine:

``` json
{
  "actionable": true,
  "category": "architecture_change",
  "severity": "high",
  "requires_replanning": true,
  "affected_requirements": [],
  "affected_files": [],
  "summary": "",
  "reason": ""
}
```

------------------------------------------------------------------------

# 28. Re-Engineering Workflow

If reviewer feedback requires a meaningful change:

``` text
Reviewer Feedback
       ↓
Feedback Analyzer
       ↓
Update Requirements
       ↓
Repository Re-analysis
       ↓
Architecture Re-planning
       ↓
Implementation
       ↓
Testing
       ↓
Security
       ↓
Review
       ↓
Judge
       ↓
Update PR
```

The system should **not simply patch the previous implementation
blindly** when the reviewer identifies a fundamental design problem.

This is a key requirement.

------------------------------------------------------------------------

# 29. PR Iteration History

Every workflow iteration should be stored.

Example:

``` text
Iteration 1
───────────
Plan A
Implementation A
PR #1842

Reviewer:
"Use existing shared rate limiter."

Iteration 2
───────────
Plan B
Implementation B
PR updated

Reviewer:
"Looks good."

Iteration 2 → Approved
```

The dashboard should expose this history.

------------------------------------------------------------------------

# 30. Agent Memory

ForgeAI should maintain three memory layers.

## Working Memory

Current task state:

-   issue
-   requirements
-   plan
-   retrieved context
-   modifications
-   test results
-   feedback

## Repository Memory

Persistent knowledge:

-   architecture
-   conventions
-   dependencies
-   important modules
-   previous changes

## Episodic Memory

Past engineering experiences:

-   previous failures
-   previous reviewer feedback
-   successful approaches
-   recurring repository-specific issues

Memory retrieval must be scoped to the repository to avoid cross-project
contamination.

------------------------------------------------------------------------

# 31. LLM Model Router

ForgeAI should support multiple LLMs.

The Model Router chooses a model based on:

-   task complexity
-   latency
-   cost
-   context size
-   required reasoning capability

Example:

``` text
Simple classification → Fast/Cheap model
Summarization         → Fast/Cheap model
Code generation       → Strong coding model
Architecture          → Strong reasoning model
Security analysis     → Strong reasoning model
Judge                 → Independent strong model
```

The model selection should be configurable.

------------------------------------------------------------------------

# 32. Prompt Management

Prompts must not be scattered throughout the codebase.

Create:

``` text
prompts/
├── supervisor/
├── repository/
├── requirements/
├── planning/
├── coding/
├── testing/
├── security/
├── review/
├── judge/
├── feedback/
└── delivery/
```

Prompts should be versioned.

------------------------------------------------------------------------

# 33. Structured Outputs

Agent outputs must use Pydantic models whenever practical.

Avoid relying on free-form text for workflow decisions.

Example:

``` python
class ReviewDecision(BaseModel):
    ready: bool
    blocking_issues: list[str]
    score: float
```

LangGraph state should contain structured objects rather than arbitrary
model text.

------------------------------------------------------------------------

# 34. LangGraph State

The workflow should maintain a persistent state similar to:

``` python
class ForgeState(TypedDict):
    task_id: str
    repository_url: str
    issue_url: str
    repository: dict
    issue: dict
    requirements: dict
    repository_context: list
    architecture: dict
    plan: dict
    changes: list
    test_results: dict
    security_results: dict
    review_results: dict
    judge_results: dict
    pr: dict
    reviewer_feedback: list
    iteration: int
    status: str
```

------------------------------------------------------------------------

# 35. Workflow Persistence

LangGraph checkpoints should persist workflow state.

Requirements:

-   restart recovery
-   task resumption
-   human approval interruption
-   reviewer-feedback resumption
-   retry support
-   iteration history

PostgreSQL should be preferred for durable workflow state.

------------------------------------------------------------------------

# 36. API Design

## POST `/api/tasks`

Create a task.

Request:

``` json
{
  "repository_url": "https://github.com/org/repo",
  "issue_url": "https://github.com/org/repo/issues/123"
}
```

Response:

``` json
{
  "task_id": "task_123",
  "status": "queued"
}
```

## GET `/api/tasks/{task_id}`

Returns task state.

## GET `/api/tasks/{task_id}/events`

Streams task events.

## GET `/api/tasks/{task_id}/report`

Returns final report.

## GET `/api/tasks/{task_id}/pr`

Returns PR details.

## POST `/api/tasks/{task_id}/resume`

Resume a paused workflow.

## POST `/api/tasks/{task_id}/cancel`

Cancel a running workflow.

------------------------------------------------------------------------

# 37. WebSocket Events

Example event:

``` json
{
  "task_id": "task_123",
  "event": "agent.started",
  "agent": "coding_agent",
  "timestamp": "...",
  "metadata": {}
}
```

Event types:

``` text
task.created
task.started
agent.started
agent.completed
agent.failed
tool.started
tool.completed
retrieval.started
retrieval.completed
test.started
test.completed
security.started
security.completed
judge.completed
pr.created
pr.updated
review.received
feedback.analyzed
workflow.replanned
workflow.completed
workflow.failed
```

------------------------------------------------------------------------

# 38. Database Schema

Core tables:

``` text
users
repositories
tasks
task_iterations
agent_runs
tool_calls
llm_calls
retrieval_runs
documents
document_chunks
repository_entities
repository_relationships
plans
code_changes
test_runs
security_scans
reviews
review_feedback
pull_requests
evaluations
task_events
```

------------------------------------------------------------------------

# 39. RAG Data Model

Store:

-   chunk content
-   embedding
-   repository
-   commit SHA
-   file path
-   language
-   symbol
-   line range
-   chunk type
-   timestamps

Repository indexing must be version-aware.

A task should ideally retrieve context corresponding to the commit being
modified.

------------------------------------------------------------------------

# 40. Observability

Every agent run must be traceable.

Trace:

``` text
Task
 └── Supervisor
      ├── Repository Agent
      │    ├── LLM call
      │    └── MCP calls
      ├── Requirements Agent
      ├── Planner
      ├── Coding Agent
      │    ├── Retrieval
      │    ├── LLM
      │    └── File tools
      ├── Testing Agent
      ├── Security Agent
      ├── Reviewer
      └── Judge
```

Track:

-   latency
-   tokens
-   model
-   estimated cost
-   tool calls
-   errors
-   retries
-   retrieved documents
-   agent transitions

------------------------------------------------------------------------

# 41. Cost Tracking

Every LLM call should record:

``` text
model
input tokens
output tokens
total tokens
estimated cost
latency
task ID
agent
```

The final report should show total estimated AI cost.

------------------------------------------------------------------------

# 42. Agent Evaluation Framework

ForgeAI itself must be evaluated.

Metrics:

## Task Success Rate

Percentage of issues successfully resolved.

## Test Pass Rate

Percentage of generated changes passing tests.

## Retrieval Quality

Whether relevant files were retrieved.

## Planning Quality

Whether the implementation plan correctly identified affected
components.

## Code Quality

LLM + static analysis evaluation.

## Security

Security findings and regressions.

## Reviewer Acceptance Rate

Percentage of PRs accepted without major rework.

## Iteration Count

Number of reviewer-feedback cycles required.

## Cost per Task

Average model/tool cost.

## Time per Task

End-to-end latency.

------------------------------------------------------------------------

# 43. LLM-as-Judge Requirements

Judge prompts must be isolated from the Coding Agent.

Where possible, use a different model or independent evaluation context.

The Judge should evaluate against:

-   original issue
-   acceptance criteria
-   actual diff
-   test results
-   security results
-   reviewer findings

It must not simply evaluate the Coding Agent's explanation.

------------------------------------------------------------------------

# 44. Security Requirements

The platform must:

-   never expose secrets to LLM prompts
-   redact secrets from logs
-   isolate code execution
-   restrict network access
-   use scoped GitHub credentials
-   never grant merge permissions
-   restrict MCP tools by agent
-   enforce command allowlists where appropriate
-   prevent arbitrary host filesystem access
-   enforce resource limits
-   audit tool execution

------------------------------------------------------------------------

# 45. GitHub Authentication

Preferred architecture:

``` text
GitHub App
    ↓
Installation Token
    ↓
ForgeAI Backend
```

Avoid storing long-lived personal access tokens when possible.

Permissions should be minimal.

------------------------------------------------------------------------

# 46. Failure Handling

Every agent must support:

-   timeout
-   retry
-   model failure
-   malformed output
-   tool failure
-   MCP server failure
-   test failure
-   repository failure
-   GitHub API failure

Use exponential backoff where appropriate.

Failures must be categorized:

``` text
TRANSIENT
PERMANENT
AGENT_ERROR
TOOL_ERROR
USER_ACTION_REQUIRED
SECURITY_BLOCK
```

------------------------------------------------------------------------

# 47. Idempotency

Operations such as:

-   branch creation
-   commit creation
-   PR creation
-   PR update

must be idempotent where possible.

A workflow restart must not create duplicate PRs or duplicate branches
unnecessarily.

------------------------------------------------------------------------

# 48. Project Structure

Recommended backend structure:

``` text
forgeai/
│
├── app/
│   ├── main.py
│   │
│   ├── api/
│   │   ├── routes/
│   │   │   ├── tasks.py
│   │   │   ├── reports.py
│   │   │   └── health.py
│   │   └── websocket.py
│   │
│   ├── agents/
│   │   ├── supervisor.py
│   │   ├── repository.py
│   │   ├── requirements.py
│   │   ├── planner.py
│   │   ├── coder.py
│   │   ├── tester.py
│   │   ├── security.py
│   │   ├── reviewer.py
│   │   ├── judge.py
│   │   ├── feedback.py
│   │   └── delivery.py
│   │
│   ├── orchestration/
│   │   ├── graph.py
│   │   ├── state.py
│   │   ├── nodes.py
│   │   └── routing.py
│   │
│   ├── harness/
│   │   ├── executor.py
│   │   ├── permissions.py
│   │   ├── budgets.py
│   │   ├── retries.py
│   │   └── guardrails.py
│   │
│   ├── mcp/
│   │   ├── client.py
│   │   ├── registry.py
│   │   └── permissions.py
│   │
│   ├── rag/
│   │   ├── indexer.py
│   │   ├── chunker.py
│   │   ├── retriever.py
│   │   ├── reranker.py
│   │   └── embeddings.py
│   │
│   ├── knowledge/
│   │   ├── graph.py
│   │   └── repository_graph.py
│   │
│   ├── execution/
│   │   ├── sandbox.py
│   │   ├── docker.py
│   │   └── commands.py
│   │
│   ├── github/
│   │   ├── client.py
│   │   ├── auth.py
│   │   └── models.py
│   │
│   ├── llm/
│   │   ├── router.py
│   │   ├── providers.py
│   │   └── models.py
│   │
│   ├── memory/
│   │   ├── working.py
│   │   ├── repository.py
│   │   └── episodic.py
│   │
│   ├── evaluation/
│   │   ├── evaluator.py
│   │   ├── metrics.py
│   │   ├── datasets.py
│   │   └── judges.py
│   │
│   ├── observability/
│   │   ├── tracing.py
│   │   ├── metrics.py
│   │   └── logging.py
│   │
│   ├── database/
│   │   ├── models.py
│   │   ├── repositories.py
│   │   └── session.py
│   │
│   └── config/
│       └── settings.py
│
├── mcp_servers/
│   ├── github/
│   ├── repository/
│   ├── execution/
│   └── documentation/
│
├── prompts/
│   ├── supervisor/
│   ├── repository/
│   ├── requirements/
│   ├── planner/
│   ├── coder/
│   ├── tester/
│   ├── security/
│   ├── reviewer/
│   ├── judge/
│   ├── feedback/
│   └── delivery/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── agents/
│   ├── rag/
│   ├── mcp/
│   ├── workflow/
│   └── evaluation/
│
├── frontend/
│
├── docker/
│
├── docker-compose.yml
├── pyproject.toml
├── .env.example
└── README.md
```

------------------------------------------------------------------------

# 49. Development Phases

## Phase 1 --- Core Backend

Implement:

-   FastAPI
-   task creation
-   GitHub URL validation
-   GitHub issue retrieval
-   repository retrieval
-   basic task state
-   WebSocket progress

## Phase 2 --- Single Agent

Implement:

-   repository analysis
-   issue analysis
-   LLM abstraction
-   basic coding workflow
-   sandbox

## Phase 3 --- LangGraph

Implement:

-   Supervisor
-   persistent graph state
-   conditional routing
-   retry loops
-   failure handling

## Phase 4 --- Multi-Agent System

Add:

-   Requirements Agent
-   Planning Agent
-   Coding Agent
-   Testing Agent
-   Security Agent
-   Review Agent
-   Judge Agent

## Phase 5 --- RAG

Add:

-   repository indexing
-   code-aware chunking
-   embeddings
-   vector search
-   hybrid search
-   reranking

## Phase 6 --- MCP

Add:

-   GitHub MCP
-   Repository MCP
-   Execution MCP
-   Documentation MCP

All MCP calls must pass through the permission model.

## Phase 7 --- Agent Harness

Add:

-   permissions
-   budgets
-   retries
-   timeouts
-   context management
-   audit logs
-   guardrails

## Phase 8 --- PR Delivery

Implement:

-   fork/workspace
-   branch creation
-   commits
-   push
-   PR creation
-   automated PR documentation

## Phase 9 --- Reviewer Feedback Loop

Implement:

-   PR polling/webhooks where available
-   feedback analyzer
-   feedback classification
-   requirement updates
-   replanning
-   reimplementation
-   PR updates

## Phase 10 --- Evaluation

Add:

-   LLM-as-Judge
-   task benchmarks
-   RAG evaluation
-   agent trajectory evaluation
-   acceptance-rate metrics
-   cost tracking

## Phase 11 --- Observability

Add:

-   OpenTelemetry
-   tracing
-   metrics
-   dashboard
-   token/cost tracking
-   agent execution visualization

## Phase 12 --- Production Hardening

Add:

-   GitHub App authentication
-   Docker isolation
-   resource limits
-   secret management
-   rate limiting
-   structured logging
-   failure recovery
-   idempotency
-   security testing

------------------------------------------------------------------------

# 50. Non-Goals

ForgeAI must NOT initially attempt to:

-   automatically merge PRs
-   deploy to production
-   modify production databases
-   access arbitrary private infrastructure
-   manage arbitrary cloud resources
-   replace human approval
-   autonomously resolve ambiguous requirements without asking
-   execute unrestricted shell commands on the host

These may be considered future extensions behind explicit permission
boundaries.

------------------------------------------------------------------------

# 51. Success Criteria

The MVP is successful when a user can provide:

``` text
Repository:
https://github.com/example/project

Issue:
https://github.com/example/project/issues/42
```

and ForgeAI can:

1.  Understand the repository.
2.  Understand the issue.
3.  Retrieve relevant code using RAG.
4.  Generate requirements.
5.  Create an implementation plan.
6.  Modify the repository in a sandbox.
7.  Run tests.
8.  Perform security analysis.
9.  Review its own changes.
10. Judge whether the task is complete.
11. Create a documented PR.
12. Display the PR in the dashboard.
13. Detect meaningful reviewer feedback.
14. Analyze the feedback.
15. Re-plan when necessary.
16. Re-implement the change.
17. Re-run tests and reviews.
18. Update the PR.
19. Stop when the reviewer approves or when human intervention is
    required.

------------------------------------------------------------------------

# 52. Final Product Definition

ForgeAI is not intended to be another chatbot, RAG demo, or simple
coding agent.

It is an **autonomous software engineering workflow platform**
combining:

``` text
LLMs
+
Multi-Agent Systems
+
LangChain
+
LangGraph
+
MCP
+
Agent Harness
+
Tool Calling
+
Repository RAG
+
Hybrid Search
+
Reranking
+
Knowledge Graph
+
Agent Memory
+
Sandboxed Code Execution
+
Automated Testing
+
Security Analysis
+
LLM-as-Judge
+
Agent Evaluation
+
Human-in-the-Loop
+
GitHub PR Automation
+
Reviewer Feedback Loops
+
Observability
+
Cost Tracking
+
Persistent Workflow State
```

The central differentiator is the **closed-loop engineering lifecycle**:

``` text
Issue
 ↓
Understand
 ↓
Retrieve
 ↓
Plan
 ↓
Implement
 ↓
Test
 ↓
Review
 ↓
Evaluate
 ↓
PR
 ↓
Human Review
 ↓
Feedback
 ↓
Re-plan
 ↓
Re-implement
 ↓
Re-test
 ↓
Update PR
 ↓
Human Approval
```

The system should optimize for **correctness, safety, traceability, and
human control**, not merely maximum autonomy.
