"""The log itself: <data dir>/sessions.jsonl, one record per session, keyed by "<harness>:<id>"."""

import fcntl
import json
from collections.abc import Generator
from contextlib import contextmanager

from .common import DATA_DIR, Session, resolve_project

DATA = DATA_DIR
SESSIONS = DATA / "sessions.jsonl"


@contextmanager
def locked() -> Generator[None]:
    """Serialise read-modify-write cycles (hooks may run concurrently)."""
    DATA.mkdir(parents=True, exist_ok=True)
    with open(DATA / ".lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield


def load() -> dict[str, dict]:
    if not SESSIONS.exists():
        return {}
    return {(r := json.loads(line))["key"]: r for line in SESSIONS.read_text().splitlines() if line.strip()}


def save(records: dict[str, dict]) -> None:
    tmp = SESSIONS.with_suffix(".tmp")
    with open(tmp, "w") as fh:
        for r in sorted(records.values(), key=lambda r: (r["start"], r["key"])):
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(SESSIONS)


def record(s: Session, old: dict | None) -> dict:
    """Metadata record for a session, keeping any existing summary."""
    project, path = resolve_project(s.cwd)
    start, end = min(s.times), max(s.times)
    r = {
        "key": s.key,
        "harness": s.harness,
        "session_id": s.session_id,
        "project": project,
        "path": path,
        "cwd": s.cwd,
        "branch": s.branch,
        "start": start.isoformat(timespec="seconds"),
        "end": end.isoformat(timespec="seconds"),
        "active_min": round(s.active_seconds() / 60, 1),
        "wall_min": round((end - start).total_seconds() / 60, 1),
        "days": {d: round(sec / 60, 1) for d, sec in s.active_by_day().items() if sec >= 60},
        "prompts": len(s.prompts),
        "first_prompt": s.prompts[0][:300],
        "model": s.model,
        "cost_usd": round(s.cost_usd, 4) if s.cost_usd is not None else None,
        "title": s.title,
        "recap": s.recap,
        "fingerprint": s.fingerprint,
    }
    r["summary"] = (old or {}).get("summary")
    return r


def previous_entry(records: dict[str, dict], project: str, before: str) -> dict | None:
    prior = [r for r in records.values() if r["project"] == project and r["start"] < before]
    return max(prior, key=lambda r: r["start"], default=None)
