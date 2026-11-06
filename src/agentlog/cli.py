"""agentlog: keep a log of coding-agent sessions (Claude Code + opencode)."""

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

from . import claude, opencode, store
from .common import CONFIG_FILE, DATA_DIR, GUARD_ENV, HOME, Session, is_ignored
from .render import entry as render_entry
from .render import fmt_min, render
from .summarize import summarize

HARNESSES = ("claude", "opencode")
INTEGRATIONS = Path(__file__).parent / "integrations"
# How hooks and plugins call back into agentlog: the interpreter this package is installed in.
SELF_CMD = [sys.executable, "-m", "agentlog.cli"]


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", file=sys.stderr, flush=True)


def collect(
    harness: str, session: str | None, records: dict, rescan: bool, dropped: set[str]
) -> list[tuple[Session, object]]:
    """Load sessions whose source changed since they were last recorded; note ones no longer worth logging."""
    if harness == "claude":
        if session:
            found = [(session, p)] if (p := claude.find(session)) else []
        else:
            found = list(claude.list_sessions())
        items = [(sid, ref, ref.stat().st_mtime) for sid, ref in found]
        loader = claude.load
    else:
        if session:
            found = [(sid := opencode.root_of(session), sid)]
        else:
            found = [(sid, sid) for sid, _ in opencode.list_sessions()]
        stamps = dict(opencode.list_sessions())
        items = [(sid, ref, stamps.get(sid)) for sid, ref in found]
        loader = opencode.load
    out = []
    for sid, ref, stamp in items:
        old = records.get(f"{harness}:{sid}")
        if old and old.get("source_stamp") == stamp and not rescan:
            continue
        s = loader(ref)
        if s is None or is_ignored(s.cwd):
            dropped.add(f"{harness}:{sid}")
        else:
            out.append((s, stamp))
    return out


def cmd_sync(a: argparse.Namespace) -> None:
    harnesses = HARNESSES if a.harness == "all" else (a.harness,)
    records = store.load()
    sessions: list[Session] = []
    dropped: set[str] = set()
    for h in harnesses:
        for s, stamp in collect(h, a.session, records, a.rescan or a.force, dropped):
            if a.since and max(s.times).date() < a.since:
                continue
            sessions.append(s)
            records[s.key] = {**store.record(s, records.get(s.key)), "source_stamp": stamp}
    with store.locked():
        fresh = store.load()
        for s in sessions:
            fresh[s.key] = {**records[s.key], "summary": (fresh.get(s.key) or {}).get("summary")}
        for key in dropped:
            fresh.pop(key, None)
        store.save(fresh)
        records = fresh
    log(f"recorded {len(sessions)} new/changed session(s)")

    todo = [] if a.no_summary else [r for r in records.values() if needs_summary(r, a)]
    if todo:
        log(f"summarising {len(todo)} session(s) with claude -p")
        groups = defaultdict(list)  # sequential within a project so each can see the previous entry
        for r in sorted(todo, key=lambda r: r["start"]):
            groups[r["project"]].append(r)
        with ThreadPoolExecutor(a.jobs) as pool:
            list(pool.map(summarize_group, groups.values()))
    with store.locked():
        render(store.load())


def needs_summary(r: dict, a: argparse.Namespace) -> bool:
    if a.session and r["session_id"] not in (a.session, opencode_root_cached(a.session)):
        return False
    if a.harness != "all" and r["harness"] != a.harness:
        return False
    if a.since and date.fromisoformat(r["end"][:10]) < a.since:
        return False
    summ = r.get("summary")
    if a.force:
        return True
    if not summ:
        return True
    return summ.get("source") != "agent" and summ.get("fingerprint") != r["fingerprint"]


_roots: dict[str, str] = {}


def opencode_root_cached(sid: str) -> str:
    if sid not in _roots:
        _roots[sid] = opencode.root_of(sid) if sid.startswith("ses_") else sid
    return _roots[sid]


def summarize_group(rows: list[dict]) -> None:
    for r in rows:
        s = claude.load(claude.find(r["session_id"])) if r["harness"] == "claude" else opencode.load(r["session_id"])
        if s is None:
            continue
        prev = store.previous_entry(store.load(), r["project"], r["start"])
        try:
            summ = summarize(s, r["project"], r["path"], prev)
        except Exception as e:  # keep going; it is retried on the next sync
            log(f"FAILED {r['key']} ({r['project']}): {e}")
            continue
        summ["fingerprint"] = s.fingerprint
        with store.locked():
            records = store.load()
            if r["key"] in records:
                records[r["key"]]["summary"] = summ
                store.save(records)
        log(f"summarised {r['project']} {r['start'][:16]}: {summ['title']}")


def cmd_hook(a: argparse.Namespace) -> None:
    """Claude Code SessionEnd hook: detach a sync of the session that just ended."""
    if os.environ.get(GUARD_ENV):
        return
    payload = json.load(sys.stdin)
    sid = payload.get("session_id")
    if not sid:
        return
    spawn_sync(["--harness", "claude", "--session", sid])


def spawn_sync(args: list[str]) -> None:
    store.DATA.mkdir(parents=True, exist_ok=True)
    with open(store.DATA / "hook.log", "a") as fh:
        subprocess.Popen(
            [sys.executable, "-m", "agentlog.cli", "sync", *args],
            stdin=subprocess.DEVNULL, stdout=fh, stderr=fh, start_new_session=True, cwd=HOME,
        )  # fmt: skip


def latest_session(harness: str, cwd: str) -> str | None:
    if harness == "claude":
        if sid := os.environ.get("CLAUDE_CODE_SESSION_ID"):
            return sid
        cands = [(p.stat().st_mtime, sid) for sid, p in claude.list_sessions()]
        for _, sid in sorted(cands, reverse=True):
            if (s := claude.load(claude.find(sid))) and s.cwd == cwd:
                return sid
        return None
    best = None
    for sid, stamp in opencode.list_sessions():
        if (s := opencode.load(sid)) and s.cwd == cwd and (best is None or stamp > best[0]):
            best = (stamp, sid)
    return best[1] if best else None


def cmd_note(a: argparse.Namespace) -> None:
    """Let the agent itself write the summary of the current session."""
    sid = a.session or latest_session(a.harness, a.cwd)
    if not sid:
        sys.exit(f"no {a.harness} session found for {a.cwd}")
    ns = argparse.Namespace(
        harness=a.harness, session=sid, since=None, rescan=True, force=False, no_summary=True, jobs=1
    )
    cmd_sync(ns)
    key = f"{a.harness}:{opencode_root_cached(sid) if a.harness == 'opencode' else sid}"
    with store.locked():
        records = store.load()
        if key not in records:
            sys.exit(f"session {key} could not be recorded")
        r = records[key]
        r["summary"] = {"title": a.title, "before": a.before, "did": a.did, "after": a.after,
                        "source": "agent", "fingerprint": r["fingerprint"]}  # fmt: skip
        store.save(records)
        render(records)
    print("\n".join(render_entry(r, with_project=True, with_date=True)))


def cmd_show(a: argparse.Namespace) -> None:
    rows = sorted(store.load().values(), key=lambda r: r["start"])
    if a.project:
        rows = [r for r in rows if a.project.lower() in r["project"].lower()]
    if a.since:
        rows = [r for r in rows if r["start"][:10] >= a.since.isoformat()]
    for r in rows[-a.n :]:
        print("\n".join(render_entry(r, with_project=True, with_date=True)))


def cmd_report(a: argparse.Namespace) -> None:
    rows = store.load().values()
    table: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in rows:
        for day, minutes in r["days"].items():
            d = date.fromisoformat(day)
            if a.since and d < a.since:
                continue
            period = {"week": f"{d:%G-W%V}", "month": f"{d:%Y-%m}", "total": "total"}[a.by]
            table[r["project"]][period] += minutes
    periods = sorted({p for v in table.values() for p in v})
    width = max([len(p) for p in table] + [7])
    print(f"{'project':<{width}}  " + "  ".join(f"{p:>8}" for p in periods))
    for proj, v in sorted(table.items(), key=lambda kv: -sum(kv[1].values())):
        print(f"{proj:<{width}}  " + "  ".join(f"{fmt_min(v[p]) if v[p] else '':>8}" for p in periods))


def cmd_render(a: argparse.Namespace) -> None:
    with store.locked():
        render(store.load())


def cmd_serve(a: argparse.Namespace) -> None:
    from . import web

    if a.open:
        import webbrowser

        webbrowser.open(f"http://{a.host}:{a.port}")
    web.serve(a.host, a.port)


def cmd_html(a: argparse.Namespace) -> None:
    from . import web

    Path(a.output).write_text(web.page(store.load()))
    print(f"wrote {a.output}")


def is_ours(dst: Path) -> bool:
    """An earlier agentlog install (a symlink into an agentlog checkout, or a file we wrote)."""
    if dst.is_symlink():
        return "agentlog" in os.readlink(dst)
    return dst.is_file() and "agentlog" in dst.read_text(errors="replace")


def put(text: str, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink() or dst.exists():
        if not dst.is_symlink() and dst.read_text(errors="replace") == text:
            return
        if not is_ours(dst):
            sys.exit(f"{dst} exists and is not ours; remove it first")
        dst.unlink()
    dst.write_text(text)
    print(f"wrote {dst}")


def cmd_install(a: argparse.Namespace) -> None:
    hook_cmd = f"{shlex.join(SELF_CMD)} hook claude"
    settings_path = HOME / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    entries = settings.setdefault("hooks", {}).setdefault("SessionEnd", [])
    ours = [
        h
        for e in entries
        for h in e.get("hooks", [])
        if re.search(r"agentlog(\.cli)? hook claude", h.get("command", ""))
    ]
    if not ours or any(h["command"] != hook_cmd for h in ours):
        if settings_path.exists():
            shutil.copy(settings_path, settings_path.with_suffix(".json.bak-agentlog"))
        for h in ours:  # e.g. installed from a different place
            h["command"] = hook_cmd
        if not ours:
            entries.append({"hooks": [{"type": "command", "command": hook_cmd}]})
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(settings, indent=2) + "\n")
        print(f"set SessionEnd hook in {settings_path}: {hook_cmd}")
    put((INTEGRATIONS / "claude" / "log-session.md").read_text(), HOME / ".claude" / "commands" / "log-session.md")
    oc = HOME / ".config" / "opencode"
    plugin = (INTEGRATIONS / "opencode" / "agentlog.js").read_text()
    plugin = re.sub(r"^const AGENTLOG = .*$", f"const AGENTLOG = {json.dumps(SELF_CMD)};", plugin, count=1, flags=re.M)
    put(plugin, oc / "plugins" / "agentlog.js")
    put((INTEGRATIONS / "opencode" / "log-session.md").read_text(), oc / "commands" / "log-session.md")
    print(f"config: {CONFIG_FILE}{'' if CONFIG_FILE.exists() else ' (not present; defaults apply)'}")
    print(f"data:   {DATA_DIR}")


def main() -> None:
    p = argparse.ArgumentParser(prog="agentlog", description=__doc__)
    sub = p.add_subparsers()

    s = sub.add_parser("sync", help="scan harness storage, record sessions, summarise new ones")
    s.add_argument("--harness", choices=[*HARNESSES, "all"], default="all")
    s.add_argument("--session", help="only this session id")
    s.add_argument("--since", type=date.fromisoformat, help="only sessions active on/after YYYY-MM-DD")
    s.add_argument("--no-summary", action="store_true", help="record metadata only (no LLM call)")
    s.add_argument("--force", action="store_true", help="re-summarise even if unchanged / agent-written")
    s.add_argument("--rescan", action="store_true", help="re-read sources even if unchanged")
    s.add_argument("-j", "--jobs", type=int, default=4, help="parallel summariser calls")
    s.set_defaults(func=cmd_sync)

    s = sub.add_parser("hook", help="harness hook entry point (reads hook JSON on stdin)")
    s.add_argument("harness", choices=["claude"])
    s.set_defaults(func=cmd_hook)

    s = sub.add_parser("note", help="write the summary of the current session (used by /log-session)")
    s.add_argument("--harness", choices=HARNESSES, required=True)
    s.add_argument("--session", help="session id (default: current/latest in --cwd)")
    s.add_argument("--cwd", default=os.getcwd())
    for f in ("title", "before", "did", "after"):
        s.add_argument(f"--{f}", required=True)
    s.set_defaults(func=cmd_note)

    s = sub.add_parser("show", help="print log entries")
    s.add_argument("project", nargs="?", help="filter by (part of) project name")
    s.add_argument("--since", type=date.fromisoformat)
    s.add_argument("-n", type=int, default=20, help="last N entries")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("report", help="active time per project")
    s.add_argument("--by", choices=["week", "month", "total"], default="week")
    s.add_argument("--since", type=date.fromisoformat)
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("serve", help="browse the log in a web page (re-read on every load)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--open", action="store_true", help="open it in the browser")
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("html", help="write the web page to a static file")
    s.add_argument("-o", "--output", default="log.html")
    s.set_defaults(func=cmd_html)

    sub.add_parser("render", help="regenerate LOG.md and projects/*.md in the data dir").set_defaults(func=cmd_render)
    sub.add_parser("install", help="install Claude hook, opencode plugin, /log-session commands").set_defaults(
        func=cmd_install
    )

    if len(sys.argv) == 1:  # default: bring the log up to date, then open the web view
        for argv in (["sync"], ["serve", "--open"]):
            a = p.parse_args(argv)
            a.func(a)
        return
    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
