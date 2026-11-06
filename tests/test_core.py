import json
import os
from datetime import datetime, timedelta

import pytest
from conftest import claude_rows, write_claude

from agentlog import claude, cli, common, render, store
from agentlog.summarize import MAX_CHARS, digest

START = datetime(2026, 1, 1, 23, 0).astimezone()


def session(*minutes: float) -> common.Session:
    s = common.Session("claude", "abc", cwd="/x")
    s.times = [START + timedelta(minutes=m) for m in minutes]
    s.prompts = ["hello"]
    s.transcript = ["USER: hello", "AGENT: hi"]
    return s


def test_active_time_skips_idle_gaps():
    # 0-10 min work, 60 min break, 10 more min
    assert session(0, 5, 10, 70, 80).active_seconds() == 20 * 60


def test_active_time_is_split_across_days():
    # 23:00-23:10, break, 23:50-00:10 (a gap counts on the day it ends)
    days = session(0, 10, 50, 60, 70).active_by_day()
    assert days == {"2026-01-01": 10 * 60.0, "2026-01-02": 20 * 60.0}


def test_idle_threshold_from_config(isolated):
    (isolated / "config.toml").write_text("idle_minutes = 120\n")
    assert session(0, 60).active_seconds() == 60 * 60


def test_resolve_project_git_root_and_alias(isolated, tmp_path):
    repo = tmp_path / "code" / "myrepo"
    (repo / ".git").mkdir(parents=True)
    (repo / "sub").mkdir()
    assert common.resolve_project(str(repo / "sub")) == ("myrepo", str(repo))
    (isolated / "config.toml").write_text(f'[aliases]\n"{repo}" = "renamed"\n')
    common.config.cache_clear()
    assert common.resolve_project(str(repo / "sub"))[0] == "renamed"


def test_is_ignored(isolated):
    (isolated / "config.toml").write_text('ignore_paths = ["/scratch"]\n')
    assert common.is_ignored("/scratch/a/b")
    assert not common.is_ignored("/home/x")


def test_digest_keeps_user_prompts_when_long():
    lines = [f"AGENT: {'x' * 500}" for _ in range(300)]
    lines.insert(150, "USER: the important middle prompt")
    out = digest(lines)
    assert len(out) < MAX_CHARS * 1.2
    assert "the important middle prompt" in out
    assert "omitted" in out


def test_claude_transcript_parsing(tmp_path):
    rows = [
        {"type": "user", "timestamp": "2026-01-01T10:00:00Z", "cwd": "/w", "gitBranch": "main",
         "message": {"content": "<system-reminder>noise</system-reminder>fix the bug"}},
        {"type": "assistant", "timestamp": "2026-01-01T10:01:00Z",
         "message": {"model": "claude-x", "content": [{"type": "text", "text": "on it"},
                                                       {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}},
        {"type": "user", "timestamp": "2026-01-01T10:02:00Z", "toolUseResult": {},
         "message": {"content": [{"type": "tool_result", "content": "out"}]}},
        {"type": "ai-title", "aiTitle": "Bug fix"},
    ]  # fmt: skip
    path = tmp_path / "sid.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows))
    s = claude.load(path)
    assert s is not None
    assert s.prompts == ["fix the bug"]
    assert (s.cwd, s.branch, s.model, s.title) == ("/w", "main", "claude-x", "Bug fix")
    assert s.transcript == ["USER: fix the bug", "AGENT: on it", "TOOL Bash: ls"]


def test_claude_skips_sdk_runs(tmp_path):
    rows = [
        {"type": "user", "timestamp": "2026-01-01T10:00:00Z", "entrypoint": "sdk-cli", "message": {"content": "x"}},
        {"type": "assistant", "timestamp": "2026-01-01T10:01:00Z", "entrypoint": "sdk-cli",
         "message": {"content": [{"type": "text", "text": "y"}]}},
    ]  # fmt: skip
    path = tmp_path / "sid.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows))
    assert claude.load(path) is None


def test_store_roundtrip_and_render(isolated):
    s = session(0, 5)
    rec = store.record(s, None)
    rec["summary"] = {"title": "T", "before": "b", "did": "d", "after": "a"}
    store.save({rec["key"]: rec})
    assert store.load() == {rec["key"]: rec}
    render.render(store.load())
    log = (isolated / "LOG.md").read_text()
    assert "- did: d" in log
    assert (isolated / "projects" / f"{render.slug(rec['project'])}.md").exists()


def test_put_refuses_foreign_files(tmp_path):
    dst = tmp_path / "cmd.md"
    cli.put("from agentlog", dst)
    cli.put("from agentlog v2", dst)  # ours: replaced
    assert dst.read_text() == "from agentlog v2"
    dst.write_text("someone else's")
    with pytest.raises(SystemExit):
        cli.put("from agentlog", dst)


def test_claude_edge_cases(tmp_path):
    rows = [
        {"type": "user", "timestamp": "2026-01-01T09:59:00Z", "isMeta": True, "message": {"content": "meta"}},
        {"type": "user", "timestamp": "2026-01-01T09:59:30Z",
         "message": {"content": "<command-name>/review</command-name><command-args>PR 7</command-args>"}},
        {"type": "user", "timestamp": "2026-01-01T09:59:40Z",
         "message": {"content": "<local-command-stdout>ok</local-command-stdout>"}},
        {"type": "user", "timestamp": "2026-01-01T09:59:50Z", "origin": {"kind": "task-notification"},
         "message": {"content": "agent finished"}},
        {"type": "user", "timestamp": "2026-01-01T09:59:55Z", "isSidechain": True, "message": {"content": "sub"}},
        *claude_rows("/w"),
        {"type": "system", "subtype": "away_summary", "timestamp": "2026-01-01T10:03:00Z",
         "content": "Left at step 2 (disable recaps in /config)"},
        {"type": "custom-title", "customTitle": "My name"},
        {"type": "ai-title", "aiTitle": "AI name"},
        {"type": "cost-state", "totalCostUSD": 0.42},
    ]  # fmt: skip
    path = write_claude("s1", rows)
    path.write_text(path.read_text() + "{not json\n")
    s = claude.load(path)
    assert s.prompts == ["/review PR 7", "fix the bug"]
    assert (s.recap, s.title, s.cost_usd) == ("Left at step 2", "My name", 0.42)

    # the same session id in two project dirs (e.g. a renamed dir): the newest file wins
    newer = write_claude("s1", claude_rows("/renamed"), project_dir="-renamed")
    os.utime(newer, (newer.stat().st_atime, path.stat().st_mtime + 10))
    assert dict(claude.list_sessions()) == {"s1": newer}
    assert claude.find("s1") == newer
    assert claude.find("nope") is None


def test_render_multi_day_session(isolated):
    s = session(0, 10, 50, 60, 70)  # 23:00 -> 00:10 next day
    rec = store.record(s, None)
    render.render({rec["key"]: rec})
    log = (isolated / "LOG.md").read_text()
    assert "(session continues until 2026-01-02)" in log
    assert "30m active total" in log
