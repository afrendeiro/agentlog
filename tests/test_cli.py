import io
import json
import os
import sys

import pytest
from conftest import claude_rows, write_claude

from agentlog import cli, store


def run(monkeypatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["agentlog", *args])
    cli.main()


@pytest.fixture
def repo(tmp_path):
    d = tmp_path / "code" / "webapp"
    (d / ".git").mkdir(parents=True)
    return d


def test_sync_records_and_summarises(monkeypatch, repo, isolated, fake_summarizer):
    write_claude("s1", claude_rows(str(repo)))
    run(monkeypatch, "sync")
    (r,) = store.load().values()
    assert (r["key"], r["project"], r["path"], r["branch"]) == ("claude:s1", "webapp", str(repo), "main")
    assert r["summary"]["did"] == "d:fix the bug"
    assert r["summary"]["fingerprint"] == r["fingerprint"]
    assert "webapp" in (isolated / "LOG.md").read_text()
    assert (isolated / "projects" / "webapp.md").exists()


def test_sync_is_incremental(monkeypatch, repo, fake_summarizer):
    path = write_claude("s1", claude_rows(str(repo)))
    run(monkeypatch, "sync")
    run(monkeypatch, "sync")
    assert len(fake_summarizer) == 1  # unchanged: not re-read, not re-summarised

    rows = claude_rows(str(repo)) + claude_rows(str(repo), prompt="and the tests", start="2026-01-01T10:05")
    path.write_text("\n".join(json.dumps(x) for x in rows))
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 10))
    run(monkeypatch, "sync")
    assert len(fake_summarizer) == 2  # grown: re-summarised
    assert store.load()["claude:s1"]["summary"]["did"] == "d:and the tests"


def test_summariser_gets_previous_entry_of_same_project(monkeypatch, repo, fake_summarizer):
    write_claude("s1", claude_rows(str(repo), start="2026-01-01T10:00"))
    write_claude("s2", claude_rows(str(repo), start="2026-01-02T10:00"))
    run(monkeypatch, "sync")
    (k1, prev1), (k2, prev2) = fake_summarizer
    assert (k1, prev1) == ("claude:s1", None)
    assert k2 == "claude:s2" and prev2["key"] == "claude:s1" and prev2["summary"]["title"] == "T1"


def test_sync_no_summary_and_since(monkeypatch, repo, fake_summarizer):
    write_claude("old", claude_rows(str(repo), start="2025-06-01T10:00"))
    write_claude("new", claude_rows(str(repo), start="2026-01-01T10:00"))
    run(monkeypatch, "sync", "--since", "2025-12-01", "--no-summary")
    recs = store.load()
    assert list(recs) == ["claude:new"]
    assert recs["claude:new"]["summary"] is None
    assert fake_summarizer == []


def test_ignored_and_empty_sessions_are_dropped(monkeypatch, tmp_path, isolated, fake_summarizer):
    (isolated / "config.toml").write_text(f'ignore_paths = ["{tmp_path / "scratch"}"]\n')
    write_claude("ign", claude_rows(str(tmp_path / "scratch" / "x")))
    write_claude("empty", claude_rows(str(tmp_path))[:1])  # the agent never answered
    run(monkeypatch, "sync")
    assert store.load() == {}


def test_failed_summary_is_retried_next_sync(monkeypatch, repo, capsys):
    write_claude("s1", claude_rows(str(repo)))

    def boom(*a):
        raise RuntimeError("no network")

    monkeypatch.setattr(cli, "summarize", boom)
    run(monkeypatch, "sync")
    assert "FAILED claude:s1" in capsys.readouterr().err
    assert store.load()["claude:s1"]["summary"] is None
    assert cli.needs_summary(store.load()["claude:s1"], cli.main.__globals__["argparse"].Namespace(
        session=None, harness="all", since=None, force=False))  # fmt: skip


def test_agent_note_is_kept_until_forced(monkeypatch, repo, fake_summarizer, capsys):
    path = write_claude("s1", claude_rows(str(repo)))
    run(monkeypatch, "note", "--harness", "claude", "--cwd", str(repo),
        "--title", "Mine", "--before", "B", "--did", "D", "--after", "A")  # fmt: skip
    assert "**webapp**" in capsys.readouterr().out
    assert store.load()["claude:s1"]["summary"]["source"] == "agent"

    path.write_text(path.read_text() + json.dumps(claude_rows(str(repo), start="2026-01-01T10:05")[1]) + "\n")
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 10))
    run(monkeypatch, "sync")
    assert fake_summarizer == []
    assert store.load()["claude:s1"]["summary"]["title"] == "Mine"

    run(monkeypatch, "sync", "--force")
    assert store.load()["claude:s1"]["summary"]["source"] == "fake"


def test_note_without_session_fails_cleanly(monkeypatch, tmp_path):
    with pytest.raises(SystemExit, match="no claude session found"):
        run(monkeypatch, "note", "--harness", "claude", "--cwd", str(tmp_path),
            "--title", "t", "--before", "b", "--did", "d", "--after", "a")  # fmt: skip


def test_show_and_report(monkeypatch, repo, tmp_path, fake_summarizer, capsys):
    other = tmp_path / "other"
    (other / ".git").mkdir(parents=True)
    write_claude("s1", claude_rows(str(repo), start="2026-01-01T10:00"))
    write_claude("s2", claude_rows(str(other), start="2026-02-01T10:00"))
    run(monkeypatch, "sync")
    capsys.readouterr()

    run(monkeypatch, "show", "web")
    out = capsys.readouterr().out
    assert "**webapp**" in out and "**other**" not in out

    run(monkeypatch, "report", "--by", "month")
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["project", "2026-01", "2026-02"]
    assert {line.split()[0] for line in lines[1:]} == {"webapp", "other"}


def test_hook_spawns_sync_unless_summarising(monkeypatch):
    spawned = []
    monkeypatch.setattr(cli, "spawn_sync", spawned.append)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"session_id": "abc"})))
    run(monkeypatch, "hook", "claude")
    assert spawned == [["--harness", "claude", "--session", "abc"]]

    monkeypatch.setenv("AGENTLOG_SUMMARIZING", "1")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"session_id": "def"})))
    run(monkeypatch, "hook", "claude")
    assert len(spawned) == 1


def test_install_updates_old_hook_and_keeps_others(monkeypatch):
    settings = cli.HOME / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    other = {"type": "command", "command": "notify-send bye"}
    old = {"type": "command", "command": "/usr/bin/uv run --quiet --project /old/agentlog agentlog hook claude"}
    settings.write_text(json.dumps({"model": "x", "hooks": {"SessionEnd": [{"hooks": [other]}, {"hooks": [old]}]}}))

    run(monkeypatch, "install")
    s = json.loads(settings.read_text())
    cmds = [h["command"] for e in s["hooks"]["SessionEnd"] for h in e["hooks"]]
    assert cmds == ["notify-send bye", f"{sys.executable} -m agentlog.cli hook claude"]
    assert s["model"] == "x"
    assert json.loads(settings.with_suffix(".json.bak-agentlog").read_text())["hooks"]["SessionEnd"][1]["hooks"] == [
        old
    ]

    plugin = (cli.HOME / ".config/opencode/plugins/agentlog.js").read_text()
    assert f"const AGENTLOG = {json.dumps([sys.executable, '-m', 'agentlog.cli'])};" in plugin
    assert (cli.HOME / ".claude/commands/log-session.md").exists()
    assert (cli.HOME / ".config/opencode/commands/log-session.md").exists()
