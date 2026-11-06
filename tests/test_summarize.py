import json
import os
import stat
from datetime import datetime, timedelta

import pytest

from agentlog import summarize
from agentlog.common import Session

FAKE_CLAUDE = """#!/usr/bin/env python3
import json, os, sys
open(os.environ["FAKE_LOG"], "w").write(json.dumps({"argv": sys.argv[1:], "stdin": sys.stdin.read(),
                                                     "guard": os.environ.get("AGENTLOG_SUMMARIZING")}))
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "crash":
    sys.stderr.write("boom"); sys.exit(3)
out = {"is_error": mode == "error", "result": "nope",
       "structured_output": None if mode == "error" else {"title": "t", "before": "b", "did": "d", "after": "a"}}
print(json.dumps(out))
"""


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "claude"
    exe.write_text(FAKE_CLAUDE)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    log = tmp_path / "call.json"
    monkeypatch.setenv("FAKE_LOG", str(log))
    return log


def session() -> Session:
    t = datetime(2026, 1, 1, 10).astimezone()
    return Session("claude", "s1", "/w", times=[t, t + timedelta(minutes=5)], prompts=["hi"],
                   transcript=["USER: hi", "AGENT: hello"], recap="left at step 2")  # fmt: skip


def test_summarize_calls_claude_headless(fake_claude):
    prev = {"start": "2025-12-31T09:00:00", "summary": {"title": "Earlier work", "after": "tests failing"}}
    out = summarize.summarize(session(), "app", "/w", prev)
    assert out == {"title": "t", "before": "b", "did": "d", "after": "a", "source": "claude:haiku"}
    call = json.loads(fake_claude.read_text())
    assert call["guard"] == "1"
    assert call["argv"][:3] == ["-p", "--model", "haiku"]
    assert "--no-session-persistence" in call["argv"]
    assert "Earlier work. Left as: tests failing" in call["stdin"]
    assert "left at step 2" in call["stdin"]
    assert "USER: hi\nAGENT: hello" in call["stdin"]


def test_summarize_errors(fake_claude, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "crash")
    with pytest.raises(RuntimeError, match="boom"):
        summarize.summarize(session(), "app", "/w", None)
    monkeypatch.setenv("FAKE_MODE", "error")
    with pytest.raises(RuntimeError, match="no summary"):
        summarize.summarize(session(), "app", "/w", None)
