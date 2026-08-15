from __future__ import annotations

import os

os.environ.setdefault("GITFORCE_DEBUG", "false")
os.environ.setdefault("GITFORCE_AUTO_DISCOVER", "false")
os.environ.setdefault(
    "GITFORCE_DATABASE_URL", "sqlite+aiosqlite:////tmp/opencode/gitforce_test.db"
)
os.environ.setdefault("GITFORCE_LLM_PROVIDER", "mock")
os.environ.setdefault("GITFORCE_SANDBOX_BACKEND", "local")
os.environ.setdefault("GITFORCE_WORKSPACE_ROOT", "/tmp/opencode/gitforce_ws")