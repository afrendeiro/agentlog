import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# Must be set before agentlog is imported: paths are resolved at import time.
# Keeps tests away from the real log.
os.environ["AGENTLOG_HOME"] = tempfile.mkdtemp(prefix="agentlog-test-")

from agentlog import claude, cli, common, opencode, render, store  # noqa: E402


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Fresh config, data dir, home, and harness sources for every test; returns the data dir."""
    data = tmp_path / "data"
    data.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(common, "CONFIG_FILE", data / "config.toml")
    monkeypatch.setattr(common, "DATA_DIR", data)
    monkeypatch.setattr(render, "DATA_DIR", data)
    monkeypatch.setattr(store, "DATA", data)
    monkeypatch.setattr(store, "SESSIONS", data / "sessions.jsonl")
    monkeypatch.setattr(claude, "PROJECTS", tmp_path / "claude-projects")
    monkeypatch.setattr(opencode, "DB", tmp_path / "opencode.db")
    monkeypatch.setattr(cli, "HOME", home)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv(common.GUARD_ENV, raising=False)
    cli._roots.clear()
    # pytest's tmp_path is under /tmp, which agentlog ignores by default.
    (data / "config.toml").write_text("ignore_paths = []\n")
    common.config.cache_clear()
    yield data
    common.config.cache_clear()


def claude_rows(cwd: str, prompt: str = "fix the bug", reply: str = "on it", start: str = "2026-01-01T10:00") -> list:
    """A prompt and a reply 2 minutes later."""
    t0 = datetime.fromisoformat(start)
    ts = [f"{t:%Y-%m-%dT%H:%M:%S}Z" for t in (t0, t0 + timedelta(minutes=2))]
    return [
        {"type": "user", "timestamp": ts[0], "cwd": cwd, "gitBranch": "main", "message": {"content": prompt}},
        {"type": "assistant", "timestamp": ts[1], "cwd": cwd,
         "message": {"model": "claude-x", "content": [{"type": "text", "text": reply}]}},
    ]  # fmt: skip


def write_claude(sid: str, rows: list, project_dir: str = "-proj") -> Path:
    path = claude.PROJECTS / project_dir / f"{sid}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return path


@pytest.fixture
def fake_summarizer(monkeypatch):
    """Replace the claude -p call; returns the list of (session key, previous entry) it was called with."""
    calls = []

    def summarize(s, project, path, previous):
        calls.append((s.key, previous))
        return {"title": f"T{len(calls)}", "before": "b", "did": f"d:{s.prompts[-1]}", "after": "a", "source": "fake"}

    monkeypatch.setattr(cli, "summarize", summarize)
    return calls
