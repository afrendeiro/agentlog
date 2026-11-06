"""Write before/did/after summaries with a headless `claude -p` call."""

import json
import os
import subprocess
import tempfile

from .common import GUARD_ENV, Session, clip, config

MAX_CHARS = 40_000

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "3-8 word name of the work"},
        "before": {"type": "string", "description": "state at the start"},
        "did": {"type": "string", "description": "what was worked on / achieved"},
        "after": {"type": "string", "description": "how it was left: done, open issues, next step"},
    },
    "required": ["title", "before", "did", "after"],
}

PROMPT = """\
You write entries for my personal log of AI coding-agent sessions.

Project: {project} ({path})
Harness: {harness} | {start} -> {end} | ~{active} min active
Previous log entry for this project: {previous}
Harness's own recap of where things were left: {recap}

Transcript digest (USER = me, AGENT = the agent's replies, TOOL = actions it took):
<transcript>
{transcript}
</transcript>

Fill the fields with ONE short sentence each (max ~30 words, plain text, no markdown):
- title: 3-8 word name of the work.
- before: the state at the start, e.g. "new project from scratch", "continued X from previous session",
  "built on existing Y pipeline". Use the previous entry if the transcript continues it.
- did: what was worked on and achieved; be concrete (analyses, files, features).
- after: how it was left: finished / what remains open / the next step.
Only state what the transcript supports."""


def digest(lines: list[str]) -> str:
    """Join transcript lines, eliding the middle (except user prompts) if too long."""
    text = "\n".join(lines)
    if len(text) <= MAX_CHARS:
        return text
    head, tail, budget = [], [], MAX_CHARS // 4
    for line in lines:
        if (budget := budget - len(line)) < 0:
            break
        head.append(line)
    budget = MAX_CHARS // 2
    for line in reversed(lines[len(head) :]):
        if (budget := budget - len(line)) < 0:
            break
        tail.insert(0, line)
    middle = lines[len(head) : len(lines) - len(tail)]
    kept = [clip(x, 300) for x in middle if x.startswith("USER:")]
    return "\n".join([*head, f"[... {len(middle) - len(kept)} agent/tool lines omitted ...]", *kept, *tail])


def summarize(s: Session, project: str, path: str, previous: dict | None) -> dict:
    prev = "none (possibly the first logged session)"
    if previous:
        summ = previous.get("summary") or {}
        prev = f"{previous['start'][:10]}: {summ.get('title') or previous.get('title')}. "
        prev += f"Left as: {summ.get('after') or previous.get('recap') or 'unknown'}"
    prompt = PROMPT.format(
        project=project,
        path=path,
        harness=s.harness,
        start=min(s.times).strftime("%Y-%m-%d %H:%M"),
        end=max(s.times).strftime("%Y-%m-%d %H:%M"),
        active=round(s.active_seconds() / 60),
        previous=prev,
        recap=s.recap or "none",
        transcript=digest(s.transcript),
    )
    model = config()["summary_model"]
    cmd = [
        "claude", "-p",
        "--model", model,
        "--no-session-persistence",
        "--setting-sources", "",
        "--tools", "",
        "--output-format", "json",
        "--json-schema", json.dumps(SCHEMA),
    ]  # fmt: skip
    with tempfile.TemporaryDirectory() as tmp:
        out = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, timeout=300, cwd=tmp,
            env={**os.environ, GUARD_ENV: "1"},
        )  # fmt: skip
    if out.returncode != 0:
        raise RuntimeError(f"claude -p failed ({out.returncode}): {out.stderr.strip() or out.stdout[:500]}")
    res = json.loads(out.stdout)
    if res.get("is_error") or not res.get("structured_output"):
        raise RuntimeError(f"claude -p returned no summary: {str(res.get('result'))[:500]}")
    return {**res["structured_output"], "source": f"claude:{model}"}
