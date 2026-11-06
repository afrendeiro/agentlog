# agentlog

[![CI](https://github.com/afrendeiro/agentlog/actions/workflows/ci.yml/badge.svg)](https://github.com/afrendeiro/agentlog/actions/workflows/ci.yml)

> [!NOTE]
> **Built by AI agents.** agentlog was written almost entirely by LLM agents,
> directed by one person. Use at your own risk.

A running log of every coding-agent session you have with
[Claude Code](https://claude.com/claude-code) and [opencode](https://opencode.ai): which project, when, for
how long, and a one-line **before / did / after** for each.

It answers questions like *"what did I actually do on Tuesday?"*, *"where did I leave project X?"* and
*"how much time went into Y this month?"* without you having to write anything down. Sessions are recorded
automatically when they end, and summarised from the transcript by Claude.

Run `agentlog` to bring the log up to date and browse it in a local web page with search, project and
harness filters, and a daily activity chart:

```console
$ agentlog
[14:12:03] recorded 1 new/changed session(s)
[14:12:03] summarising 1 session(s) with claude -p
[14:12:09] summarised my-webapp 2026-11-05T14:02: Add CSV export to reports page
agentlog: http://127.0.0.1:8765
```

The same log is available in the terminal:

```console
$ agentlog show -n 1
- **my-webapp** · 2026-11-05 14:02–15:10 · 52m active · claude · Add CSV export to reports page
  - before: Continued the reports refactor from the previous session; export button was a stub.
  - did: Implemented streaming CSV export with column selection, added tests, fixed a timezone bug in dates.
  - after: Export works and tests pass; large-report performance still untested, next step is pagination.

$ agentlog report --by week
project        2026-W44  2026-W45
my-webapp        6h20m    4h05m
dotfiles           45m    1h10m
thesis-figures   2h30m
```

## Features

- **Automatic**: a Claude Code `SessionEnd` hook and an opencode plugin record sessions as they end;
  `agentlog sync` catches up on anything missed, including sessions from before you installed it.
- **Summaries that link up**: each session gets a before/did/after, written with the previous entry for
  the same project as context, so a project's file reads as a running story.
- **Agent-written entries**: `/log-session` inside a session makes the agent write its own entry, which is
  usually better than one written afterwards from the transcript.
- **Honest time accounting**: active time ignores breaks (gaps over 15 min) and is split across days for
  sessions that run past midnight.
- **Several views**: a searchable local web page, Markdown files (by day and per project), terminal
  `show`/`report`, and the raw JSONL.
- **Local and simple**: one JSONL file, no daemon, no database, no dependencies beyond the Python standard
  library.

## Quick start

Requirements: Linux or macOS, Python ≥ 3.11, [uv](https://docs.astral.sh/uv/), and the `claude` CLI on
`PATH` for summaries (you can skip summaries with `--no-summary`).

```sh
uv tool install git+https://github.com/afrendeiro/agentlog   # puts `agentlog` on PATH
agentlog install    # Claude hook, opencode plugin, /log-session commands
agentlog            # record existing sessions, then open the web view
```

The first run summarises every past session it finds, one `claude -p --model haiku` call each. Limit that
with `agentlog sync --since 2026-10-01` (or skip it with `--no-summary`) if you have a long history.

`agentlog install` adds a `SessionEnd` hook to `~/.claude/settings.json` (backup in
`settings.json.bak-agentlog`) and writes `~/.claude/commands/log-session.md`,
`~/.config/opencode/plugins/agentlog.js` and `~/.config/opencode/commands/log-session.md`. It refuses to
overwrite files it didn't write. Re-run it after upgrading or reinstalling agentlog, because the hook and
plugin call the Python interpreter agentlog is installed in.

## Commands

```sh
agentlog                      # sync, then open the web view
agentlog sync                 # scan both harnesses, record new/changed sessions, summarise them
agentlog show [project]       # last entries (optionally for one project)
agentlog report --by week     # active time per project per week (or month, total)
agentlog serve --open         # web view at http://127.0.0.1:8765 (search, project/harness filters)
agentlog html -o log.html     # the same page as a static file
agentlog install              # (re)install the hooks/plugin/commands
```

See `agentlog <command> --help` for all options. `sync` is idempotent and incremental: sessions whose
source hasn't changed are skipped, and a summary is only rewritten when its session has grown. Useful
flags: `--since YYYY-MM-DD`, `--session ID`, `--harness claude|opencode`, `--no-summary`, `--force`
(re-summarise everything).

## Where things are stored

- `~/.local/share/agentlog/sessions.jsonl`: the data, one JSON record per session
- `~/.local/share/agentlog/LOG.md`: all sessions by day, plus a project index (generated)
- `~/.local/share/agentlog/projects/`: one chronological Markdown file per project (generated)
- `~/.config/agentlog/config.toml`: optional settings (see [config.example.toml](config.example.toml))

`$XDG_DATA_HOME`/`$XDG_CONFIG_HOME` are respected. Set `AGENTLOG_HOME` to keep config and data together in
one directory instead, e.g. a private git repo of your own log.

## Configuration

All settings are optional; see [config.example.toml](config.example.toml) for the defaults.

- `idle_minutes`: gaps longer than this count as breaks (default 15)
- `summary_model`: model for `claude -p` summaries (default `haiku`)
- `ignore_paths`: sessions started under these directories aren't logged (default `/tmp`)
- `not_project_roots`: directories never treated as a project, e.g. a home dir that is a git repo
- `[aliases]`: map a path prefix to a project name, e.g. after renaming a project

## How it works

### Recording

| | automatic | by hand, from inside the session |
|---|---|---|
| Claude Code | `SessionEnd` hook runs `agentlog hook claude`, which detaches a `sync` of that session | `/log-session` |
| opencode | plugin records metadata whenever the agent goes idle, and writes the summary after 20 min without activity (opencode has no "session ended" event) | `/log-session` |

Anything missed (a killed terminal, sessions from before agentlog was installed) is picked up by the next
`agentlog sync`. Entries written with `/log-session` (`"source": "agent"`) aren't overwritten by `sync`
unless you pass `--force`.

### Sources

- **Claude Code**: `~/.claude/projects/<dir>/<session>.jsonl` (respects `CLAUDE_CONFIG_DIR`). Subagent
  transcripts and `claude -p`/SDK runs are ignored. The harness's own title and "recap" are kept.
- **opencode**: `~/.local/share/opencode/opencode.db`, opened read-only. Subagent sessions are folded into
  their root session.

### Summaries

Summaries come from `claude -p` with structured JSON output, no tools and no saved session. The summariser
gets a condensed transcript (your prompts, the agent's replies, the tool calls it made) plus the previous
entry for the same project. Its environment sets `AGENTLOG_SUMMARIZING=1`, so the hooks never recurse.

### Fields

- **project**: the matching alias from the config; otherwise the git root of the session's starting
  directory (never `~`); otherwise the directory itself.
- **active time**: gaps between events of `idle_minutes` or less count as work. It measures agent-plus-you
  activity, so long autonomous runs count in full. Time is split per day (`days`).
- also `wall_min`, `prompts`, `model`, `cost_usd`, `branch`, `first_prompt`, harness `title` and `recap`.

## Privacy

The log contains the start of your first prompt, working directories, and summaries of what you did, so
treat `~/.local/share/agentlog` as private. Summaries are written by sending a condensed transcript of each
session to Claude through your own `claude` CLI, the same service the session itself used. Nothing else
leaves your machine. `agentlog serve` binds to `127.0.0.1` by default and has no authentication, so don't
expose it with `--host` on an untrusted network.

## Development

```sh
git clone https://github.com/afrendeiro/agentlog && cd agentlog
uv tool install -e .     # the global `agentlog` runs your checkout
uv sync
uv run pytest --cov=agentlog   # tests never touch your real log, ~/.claude or opencode DB
uvx ruff check . && uvx ruff format --check .
```

The `task` shortcuts in `pyproject.toml` ([taskipy](https://github.com/taskipy/taskipy); `uv run task --list`)
run `uv run agentlog <command>` from the checkout.

Adding another harness means a reader module like `src/agentlog/claude.py` (list sessions, load one into
a `Session`) plus a way to trigger `sync` when a session ends.

## License

[MIT](LICENSE)
