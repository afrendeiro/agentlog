# agentlog

A log of every coding-agent session (Claude Code and opencode): which project, when, for how long,
and a very brief **before / did / after**.

The log is stored locally:

- `~/.local/share/agentlog/sessions.jsonl`: the data, one JSON record per session
- `~/.local/share/agentlog/LOG.md`: all sessions by day, plus a project index (generated)
- `~/.local/share/agentlog/projects/`: one chronological Markdown file per project (generated)
- `~/.config/agentlog/config.toml`: optional settings (see [config.example.toml](config.example.toml))

`$XDG_DATA_HOME`/`$XDG_CONFIG_HOME` are respected. Set `AGENTLOG_HOME` to keep config and data together in
one directory instead, e.g. a private git repo of your own log.

## Requirements

- Linux or macOS (file locking uses `fcntl`), Python ≥ 3.11, [uv](https://docs.astral.sh/uv/)
- [Claude Code](https://claude.com/claude-code) and/or [opencode](https://opencode.ai) (the harnesses that get logged)
- the `claude` CLI on `PATH` for the summaries (skip them with `--no-summary`)

## Install

```sh
git clone <this repo> && cd agentlog
uv tool install .        # puts `agentlog` on PATH; use `-e .` to hack on it
agentlog install         # Claude hook, opencode plugin, /log-session commands
```

`agentlog install` adds a `SessionEnd` hook to `~/.claude/settings.json` (backup in
`settings.json.bak-agentlog`) and writes `~/.claude/commands/log-session.md`,
`~/.config/opencode/plugins/agentlog.js` and `~/.config/opencode/commands/log-session.md`. It refuses to
overwrite files it didn't write. Re-run it after upgrading or reinstalling agentlog: the hook and plugin call
the Python interpreter agentlog is installed in.

Running `agentlog` with no arguments, from any directory, syncs and then opens the web view.

## Commands

```sh
agentlog sync                 # scan both harnesses, record new/changed sessions, summarise them
agentlog show [project]       # last entries (optionally for one project)
agentlog report --by week     # active time per project per week (or month, total)
agentlog serve --open         # web view at http://127.0.0.1:8765 (search, project/harness filters)
agentlog html -o log.html     # the same page as a static file
agentlog install              # (re)install the hooks/plugin/commands below
```

See `agentlog <command> --help` for all options. `sync` is idempotent and incremental: sessions whose
source hasn't changed are skipped, and a summary is only rewritten when its session has grown. Useful
flags: `--since YYYY-MM-DD`, `--session ID`, `--harness claude|opencode`, `--no-summary`, `--force`
(re-summarise everything).

## How sessions get recorded

| | automatic | by hand, from inside the session |
|---|---|---|
| Claude Code | `SessionEnd` hook in `~/.claude/settings.json` runs `agentlog hook claude`, which detaches a `sync` of that session | `/log-session` |
| opencode | plugin `~/.config/opencode/plugins/agentlog.js`: records metadata on each idle and writes the summary after 20 min without activity (opencode has no "session ended" event) | `/log-session` |

Anything missed (killed terminal, sessions from before this existed) is picked up by the next
`agentlog sync`.

`/log-session` makes the agent write its own before/did/after, which is usually better than the
after-the-fact summary. Entries written that way (`"source": "agent"`) aren't overwritten by `sync`
unless you pass `--force`.

## Where the data comes from

- **Claude Code**: `~/.claude/projects/<dir>/<session>.jsonl`. Subagent transcripts are ignored, and so are
  `claude -p`/SDK runs. The title is `ai-title`/`custom-title`, and the harness's own "recap" (`away_summary`)
  is passed to the summariser.
- **opencode**: `~/.local/share/opencode/opencode.db` (`session_v2`, `session_message`), opened read-only.
  Subagent sessions are folded into their root session.

Summaries come from `claude -p --model haiku` (structured JSON output, no tools, no session saved). The
summariser gets a condensed transcript (prompts, agent replies, tool calls) plus the previous entry for the
same project, so "before" can refer back to it. Its environment sets `AGENTLOG_SUMMARIZING=1`, so the
hooks never recurse.

## What gets recorded

- **project**: the alias from `config.toml` if one matches; otherwise the git root of the session's starting
  directory (never `~`); otherwise the directory itself.
- **active time**: gaps between events of `idle_minutes` (15) or less count as work, longer gaps count as
  breaks. Time is split per day (`days`), so sessions that run over several days are counted on the right
  days. It measures agent-plus-you activity, so long autonomous runs count in full.
- `wall_min`, `prompts`, `model`, `cost_usd`, `branch`, `first_prompt`, harness `title` and `recap`.

Settings (idle threshold, summary model, ignored paths, project aliases) go in `~/.config/agentlog/config.toml`;
see [config.example.toml](config.example.toml) for the options and defaults.

## Privacy

The log contains your prompts' first lines, working directories and summaries of what you did, so treat
`~/.local/share/agentlog` as private. Summaries are written by sending a condensed transcript of each session
to Claude through your own `claude` CLI (`claude -p`), the same way the session itself was. Nothing else
leaves your machine. `agentlog serve` binds to `127.0.0.1` by default and has no authentication, so don't
expose it with `--host` on an untrusted network.

## Development

```sh
uv sync
uv run pytest
uvx ruff check . && uvx ruff format --check .
```

The `task` shortcuts in `pyproject.toml` ([taskipy](https://github.com/taskipy/taskipy); `uv run task --list`)
run `uv run agentlog <command>` from the checkout.

## License

[MIT](LICENSE)
