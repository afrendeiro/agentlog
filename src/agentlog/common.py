"""Shared types and helpers: the Session model, config, project resolution."""

import os
import re
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from functools import cache
from itertools import pairwise
from pathlib import Path

HOME = Path.home()


def _xdg(var: str, default: str) -> Path:
    return Path(os.environ.get(var) or HOME / default) / "agentlog"


# AGENTLOG_HOME puts config and data in one directory; otherwise follow XDG.
_HOME_OVERRIDE = os.environ.get("AGENTLOG_HOME")
CONFIG_DIR = Path(_HOME_OVERRIDE) if _HOME_OVERRIDE else _xdg("XDG_CONFIG_HOME", ".config")
DATA_DIR = Path(_HOME_OVERRIDE) if _HOME_OVERRIDE else _xdg("XDG_DATA_HOME", ".local/share")
CONFIG_FILE = CONFIG_DIR / "config.toml"

# Set in the environment of the summarizer subprocess so that hooks of nested
# agent runs don't recurse into agentlog.
GUARD_ENV = "AGENTLOG_SUMMARIZING"


@cache
def config() -> dict:
    cfg = tomllib.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
    cfg.setdefault("idle_minutes", 15)
    cfg.setdefault("summary_model", "haiku")
    cfg.setdefault("ignore_paths", ["/tmp"])
    cfg.setdefault("not_project_roots", ["~"])
    cfg.setdefault("aliases", {})
    return cfg


def expand(p: str) -> Path:
    return Path(p).expanduser()


@dataclass
class Session:
    harness: str
    session_id: str
    cwd: str
    times: list[datetime] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)
    # Condensed transcript lines: "USER: ...", "AGENT: ...", "TOOL ...: ..."
    transcript: list[str] = field(default_factory=list)
    title: str | None = None
    branch: str | None = None
    model: str | None = None
    cost_usd: float | None = None
    # Harness-generated note on where things were left (Claude "recap").
    recap: str | None = None

    @property
    def key(self) -> str:
        return f"{self.harness}:{self.session_id}"

    @property
    def fingerprint(self) -> str:
        return f"{len(self.times)}@{max(self.times).isoformat()}"

    def is_empty(self) -> bool:
        """No prompt, or the agent never answered (e.g. a lone /clear)."""
        return not self.prompts or not self.times or not any(x.startswith(("AGENT", "TOOL")) for x in self.transcript)

    def active_seconds(self) -> float:
        return sum(self.active_by_day().values())

    def active_by_day(self) -> dict[str, float]:
        """Seconds of activity per local date; gaps longer than idle_minutes are breaks."""
        idle = config()["idle_minutes"] * 60
        ts = sorted(self.times)
        days: dict[str, float] = {ts[0].date().isoformat(): 0.0}
        for a, b in pairwise(ts):
            if (g := (b - a).total_seconds()) <= idle:
                d = b.date().isoformat()
                days[d] = days.get(d, 0.0) + g
        return days


def is_ignored(cwd: str) -> bool:
    p = Path(cwd)
    return any(p.is_relative_to(expand(i)) for i in config()["ignore_paths"])


def resolve_project(cwd: str) -> tuple[str, str]:
    """Return (project name, project root path) for a working directory."""
    p = Path(cwd)
    aliases = sorted(((expand(k), v) for k, v in config()["aliases"].items()), key=lambda kv: -len(str(kv[0])))
    for prefix, name in aliases:
        if p.is_relative_to(prefix):
            return name, str(prefix)
    blocked = {expand(x) for x in config()["not_project_roots"]}
    for d in [p, *p.parents]:
        if d in blocked:
            break
        if (d / ".git").exists():
            return d.name, str(d)
    return ("home" if p == HOME else p.name or str(p)), str(p)


def clip(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def tool_line(name: str, inp: dict | None) -> str:
    inp = inp or {}
    for k in ("file_path", "filePath", "path", "command", "pattern", "url", "description", "query", "prompt"):
        if isinstance(inp.get(k), str):
            return f"TOOL {name}: {clip(inp[k], 160)}"
    return f"TOOL {name}"
