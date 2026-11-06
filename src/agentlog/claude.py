"""Read Claude Code transcripts (~/.claude/projects/<dir>/<session>.jsonl)."""

import json
import os
import re
from collections import Counter
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from .common import Session, clip, tool_line

PROJECTS = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "projects"

_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
_COMMAND = re.compile(r"<command-name>(.*?)</command-name>.*?(?:<command-args>(.*?)</command-args>)?", re.S)


def list_sessions() -> Iterator[tuple[str, Path]]:
    # Top-level files only: subagent transcripts live in <session>/subagents/.
    # A session id can appear in two project dirs (e.g. after a rename); keep the newest.
    newest: dict[str, Path] = {}
    for f in PROJECTS.glob("*/*.jsonl"):
        if f.stem not in newest or f.stat().st_mtime > newest[f.stem].stat().st_mtime:
            newest[f.stem] = f
    yield from newest.items()


def find(session_id: str) -> Path | None:
    return max(PROJECTS.glob(f"*/{session_id}.jsonl"), key=lambda f: f.stat().st_mtime, default=None)


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone()


def _human_text(d: dict) -> str | None:
    """Text of a prompt typed by the user, or None for tool results/meta."""
    if d.get("isMeta") or d.get("isSidechain") or "toolUseResult" in d:
        return None
    if (d.get("origin") or {}).get("kind", "human") != "human":
        return None
    content = (d.get("message") or {}).get("content")
    if isinstance(content, list):
        if any(b.get("type") == "tool_result" for b in content):
            return None
        content = "\n".join(b.get("text", "") for b in content if b.get("type") == "text")
    if not isinstance(content, str):
        return None
    if content.startswith(("<local-command-stdout>", "<local-command-caveat>", "<local-command-stderr>")):
        return None
    if m := _COMMAND.search(content):
        return f"{m.group(1)} {m.group(2) or ''}".strip()
    content = _REMINDER.sub("", content).strip()
    return content or None


def load(path: Path) -> Session | None:
    s = Session("claude", path.stem, cwd="")
    models: Counter[str] = Counter()
    entrypoints: Counter[str] = Counter()
    custom_title = ai_title = legacy_summary = None
    with open(path) as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = d.get("type")
            if t == "custom-title":
                custom_title = d.get("customTitle") or custom_title
            elif t == "ai-title":
                ai_title = d.get("aiTitle") or ai_title
            elif t == "summary":
                legacy_summary = d.get("summary") or legacy_summary
            elif t == "cost-state":
                s.cost_usd = d.get("totalCostUSD", s.cost_usd)
            if t not in ("user", "assistant", "system") or d.get("isSidechain"):
                continue
            if "timestamp" in d:
                s.times.append(_ts(d["timestamp"]))
            s.cwd = s.cwd or d.get("cwd", "")
            s.branch = d.get("gitBranch") or s.branch
            if ep := d.get("entrypoint"):
                entrypoints[ep] += 1
            if t == "user":
                if text := _human_text(d):
                    s.prompts.append(text)
                    s.transcript.append(f"USER: {clip(text, 1500)}")
            elif t == "assistant":
                msg = d.get("message") or {}
                if (m := msg.get("model")) and not m.startswith("<"):
                    models[m] += 1
                for b in msg.get("content") or []:
                    if b.get("type") == "text" and b.get("text", "").strip():
                        s.transcript.append(f"AGENT: {clip(b['text'], 600)}")
                    elif b.get("type") == "tool_use":
                        s.transcript.append(tool_line(b.get("name", "?"), b.get("input")))
            elif d.get("subtype") == "away_summary":
                s.recap = re.sub(r"\s*\(disable recaps in /config\)\s*$", "", d.get("content", ""))
    # Skip empty sessions and programmatic `claude -p` / SDK runs.
    if s.is_empty():
        return None
    if entrypoints and all(ep.startswith("sdk") for ep in entrypoints):
        return None
    s.title = custom_title or ai_title or legacy_summary
    s.model = models.most_common(1)[0][0] if models else None
    return s
