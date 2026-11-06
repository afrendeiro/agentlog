---
description: Record this session in the agent session log (before / did / after)
---

Write the entry for this session in my agent session log. Based on the whole conversation, write ONE short
plain-text sentence (max ~30 words) for each field:

- title: 3-8 word name of the work
- before: state at the start (e.g. "new project from scratch", "continued X", "built on existing Y")
- did: what was worked on and achieved, concretely
- after: how it was left: finished / what remains open / the next step

Then run with the bash tool (single-quote the values, escaping any single quotes):

```
agentlog note --harness opencode --cwd "$PWD" \
  --title '…' --before '…' --did '…' --after '…'
```

Show me the printed entry. $ARGUMENTS
