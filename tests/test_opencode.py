import json
import sqlite3
import sys

from agentlog import cli, opencode, store

T0 = 1_767_261_600_000  # 2026-01-01 10:00 UTC, in ms


def make_db(path) -> None:
    con = sqlite3.connect(path)
    con.executescript("""
        create table session_v2 (id text primary key, parent_id text, directory text, title text,
                                 cost real default 0, time_updated integer);
        create table session_message (session_id text, seq integer, type text, time_created integer, data text);
    """)
    con.executemany("insert into session_v2 values (?, ?, ?, ?, ?, ?)", [
        ("ses_root", None, "/w/app", "Root title", 0.5, T0 + 300_000),
        ("ses_child", "ses_root", "/w/app", "Explore code", 0.25, T0 + 200_000),
        ("ses_grandchild", "ses_child", "/w/app", "Deeper", 0.25, T0 + 200_000),
    ])  # fmt: skip
    msgs = [
        ("ses_root", 1, "user", T0, {"text": "add a feature"}),
        ("ses_root", 2, "assistant", T0 + 60_000, {
            "time": {"completed": T0 + 120_000}, "model": {"id": "gpt-x"},
            "content": [{"type": "text", "text": "done"},
                        {"type": "tool", "name": "bash", "state": {"input": {"command": "pytest"}}}]}),
        ("ses_child", 1, "user", T0 + 70_000, {"text": "subagent prompt"}),
        ("ses_child", 2, "assistant", T0 + 80_000, {"model": {"id": "gpt-mini"},
                                                      "content": [{"type": "text", "text": "child reply"}]}),
    ]  # fmt: skip
    con.executemany("insert into session_message values (?, ?, ?, ?, ?)",
                    [(s, q, t, tc, json.dumps(d)) for s, q, t, tc, d in msgs])  # fmt: skip
    con.commit()
    con.close()


def test_list_and_root_of():
    make_db(opencode.DB)
    assert [sid for sid, _ in opencode.list_sessions()] == ["ses_root"]
    assert opencode.root_of("ses_grandchild") == "ses_root"
    assert opencode.root_of("ses_root") == "ses_root"


def test_missing_db_lists_nothing():
    assert list(opencode.list_sessions()) == []


def test_load_folds_subagents_into_root():
    make_db(opencode.DB)
    s = opencode.load("ses_root")
    assert (s.cwd, s.title, s.model) == ("/w/app", "Root title", "gpt-x")
    assert s.cost_usd == 1.0
    assert s.prompts == ["add a feature"]  # subagent prompts aren't the user's
    assert s.transcript == ["USER: add a feature", "AGENT: done", "TOOL bash: pytest", "SUBAGENT: Explore code"]
    assert max(s.times).timestamp() * 1000 == T0 + 120_000  # includes completion time
    assert opencode.load("ses_nope") is None


def test_sync_of_a_subagent_records_its_root(monkeypatch, fake_summarizer):
    make_db(opencode.DB)
    monkeypatch.setattr(sys, "argv", ["agentlog", "sync", "--harness", "opencode", "--session", "ses_child"])
    cli.main()
    assert list(store.load()) == ["opencode:ses_root"]
    assert fake_summarizer[0][0] == "opencode:ses_root"
