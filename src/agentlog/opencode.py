"""Read opencode sessions from its SQLite database (session_v2 / session_message)."""

import json
import os
import sqlite3
from collections import Counter
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from .common import Session, clip, tool_line

DB = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "opencode" / "opencode.db"


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _ts(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000).astimezone()


def list_sessions() -> Iterator[tuple[str, str]]:
    if not DB.exists():
        return
    with _connect() as con:
        for r in con.execute("select id, time_updated from session_v2 where parent_id is null"):
            yield r["id"], r["time_updated"]


def root_of(session_id: str) -> str:
    """Subagent sessions are folded into their root session."""
    with _connect() as con:
        while True:
            r = con.execute("select parent_id from session_v2 where id = ?", (session_id,)).fetchone()
            if r is None or r["parent_id"] is None:
                return session_id
            session_id = r["parent_id"]


def load(session_id: str) -> Session | None:
    with _connect() as con:
        root = con.execute("select * from session_v2 where id = ?", (session_id,)).fetchone()
        if root is None:
            return None
        family = con.execute(
            """with recursive f(id) as (select ? union all select s.id from session_v2 s join f on s.parent_id = f.id)
               select s.* from session_v2 s join f using (id)""",
            (session_id,),
        ).fetchall()
        ids = [r["id"] for r in family]
        rows = con.execute(
            f"select session_id, type, time_created, data from session_message "
            f"where session_id in ({','.join('?' * len(ids))}) order by time_created, seq",
            ids,
        ).fetchall()
    titles = {r["id"]: r["title"] for r in family}
    s = Session("opencode", session_id, cwd=root["directory"], title=root["title"])
    s.cost_usd = sum(r["cost"] or 0 for r in family)
    models: Counter[str] = Counter()
    seen_children: set[str] = set()
    for r in rows:
        s.times.append(_ts(r["time_created"]))
        d = json.loads(r["data"])
        is_root = r["session_id"] == session_id
        if not is_root and r["session_id"] not in seen_children:
            seen_children.add(r["session_id"])
            s.transcript.append(f"SUBAGENT: {titles.get(r['session_id']) or ''}")
        if r["type"] == "user" and is_root:
            if text := (d.get("text") or "").strip():
                s.prompts.append(text)
                s.transcript.append(f"USER: {clip(text, 1500)}")
        elif r["type"] == "assistant":
            if done := (d.get("time") or {}).get("completed"):
                s.times.append(_ts(done))
            if m := (d.get("model") or {}).get("id"):
                models[m] += 1
            if not is_root:
                continue
            for b in d.get("content") or []:
                if b.get("type") == "text" and b.get("text", "").strip():
                    s.transcript.append(f"AGENT: {clip(b['text'], 600)}")
                elif b.get("type") == "tool":
                    s.transcript.append(tool_line(b.get("name", "?"), (b.get("state") or {}).get("input")))
    if s.is_empty():
        return None
    s.model = models.most_common(1)[0][0] if models else None
    return s
