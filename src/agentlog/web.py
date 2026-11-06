"""Single-page HTML view of the log, served with http.server (`agentlog serve`)."""

import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import store
from .render import fmt_min

CSS = """
:root { --bg:#fbfaf8; --fg:#1f1f1d; --mut:#6b6a66; --line:#e6e3dd; --card:#fff; --acc:#c2611f; --bar:#d9a27a;
  --claude:#c2611f; --opencode:#2f6fb0; }
@media (prefers-color-scheme: dark) { :root { --bg:#181816; --fg:#e8e6e1; --mut:#9a978f; --line:#2e2d2a;
  --card:#211f1d; --acc:#e08a4f; --bar:#8a5a38; --claude:#e08a4f; --opencode:#6aa3dc; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:14px/1.45 system-ui, sans-serif; }
header { padding:16px 20px 8px; display:flex; gap:24px; align-items:baseline; flex-wrap:wrap; }
h1 { font-size:18px; margin:0; }
.stat { color:var(--mut); } .stat b { color:var(--fg); }
#strip { display:flex; align-items:flex-end; gap:2px; height:56px; padding:0 20px; margin:8px 0 4px; }
#strip a { flex:1; background:var(--bar); min-height:1px; border-radius:2px 2px 0 0; }
#strip a.zero { background:var(--line); }
#strip a:hover { background:var(--acc); }
.axis { display:flex; justify-content:space-between; padding:0 20px; color:var(--mut); font-size:11px; }
.wrap { display:grid; grid-template-columns:260px 1fr; gap:20px; padding:16px 20px; }
main, aside { min-width:0; } .e { overflow-wrap:anywhere; }
@media (max-width: 760px) { .wrap { grid-template-columns:1fr; padding:12px 16px; }
  aside { position:static; max-height:none; } #projs { max-height:30vh; overflow:auto; }
  header, #strip, .axis { padding-left:16px; padding-right:16px; } }
aside { position:sticky; top:12px; align-self:start; max-height:calc(100vh - 24px); overflow:auto; }
input, select { width:100%; padding:6px 8px; border:1px solid var(--line); border-radius:6px;
  background:var(--card); color:var(--fg); font:inherit; margin-bottom:8px; }
.proj { display:flex; justify-content:space-between; gap:8px; padding:4px 6px; border-radius:5px; cursor:pointer; }
.proj:hover { background:var(--line); } .proj.on { background:var(--acc); color:#fff; }
.proj span:first-child { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.proj span:last-child { color:inherit; opacity:.7; white-space:nowrap; }
h2 { font-size:13px; color:var(--mut); font-weight:600; margin:18px 0 6px; border-bottom:1px solid var(--line);
  padding-bottom:3px; }
.e { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:8px 12px; margin:6px 0; }
.meta { color:var(--mut); font-size:12px; display:flex; gap:10px; flex-wrap:wrap; }
.meta .p { color:var(--fg); font-weight:600; cursor:pointer; }
.h { font-size:11px; padding:0 6px; border-radius:9px; color:#fff; }
.h.claude { background:var(--claude); } .h.opencode { background:var(--opencode); }
.t { font-weight:600; margin:2px 0; }
dl { display:grid; grid-template-columns:52px 1fr; gap:1px 8px; margin:4px 0 0; }
dt { color:var(--mut); font-size:12px; } dd { margin:0; }
"""

JS = """
const q = document.getElementById('q'), h = document.getElementById('h');
let proj = '';
function apply() {
  const s = q.value.toLowerCase();
  document.querySelectorAll('.e').forEach(e => {
    e.hidden = (proj && e.dataset.p !== proj) || (h.value && e.dataset.h !== h.value)
      || (s && !e.textContent.toLowerCase().includes(s));
  });
  document.querySelectorAll('section').forEach(d => d.hidden = !d.querySelector('.e:not([hidden])'));
  document.querySelectorAll('.proj').forEach(p => p.classList.toggle('on', p.dataset.p === proj));
}
const spent = document.getElementById('spent'), costs = JSON.parse(spent.dataset.costs);
function money(x) { return '$' + x.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}); }
function showSpent() {
  spent.innerHTML = proj
    ? `<b>${money(costs[proj] || 0)}</b> spent on ${proj.replace(/[<>&]/g, '')}`
    : `<b>${money(costs[''])}</b> spent (all projects)`;
}
function pick(p) { proj = proj === p ? '' : p; apply(); showSpent(); }
showSpent();
document.querySelectorAll('[data-pick]').forEach(el => el.onclick = () => pick(el.dataset.pick));
q.oninput = h.onchange = apply;
"""


def page(records: dict[str, dict], days_back: int = 90) -> str:
    rows = sorted(records.values(), key=lambda r: r["end"], reverse=True)
    per_day: dict[str, float] = defaultdict(float)
    per_proj: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        for d, m in r["days"].items():
            per_day[d] += m
        per_proj[r["project"]].append(r)
    today = date.today()
    week = sum(m for d, m in per_day.items() if d >= (today - timedelta(days=6)).isoformat())

    # Activity strip: one bar per day, linking to that day's section.
    span = [(today - timedelta(days=i)).isoformat() for i in range(days_back - 1, -1, -1)]
    peak = max([per_day[d] for d in span] + [1])
    bars = "".join(
        f'<a href="#d{d}" class="{"zero" if not per_day[d] else ""}" style="height:{max(per_day[d] / peak * 100, 2):.0f}%"'
        f' title="{d}: {fmt_min(per_day[d])}"></a>'
        for d in span
    )

    projects = "".join(
        f'<div class="proj" data-p="{escape(p)}" data-pick="{escape(p)}" title="{escape(rs[0]["path"])}">'
        f"<span>{escape(p)}</span><span>{fmt_min(sum(r['active_min'] for r in rs))} · {len(rs)}</span></div>"
        for p, rs in sorted(per_proj.items(), key=lambda kv: kv[1][0]["end"], reverse=True)
    )

    sections, by_end = [], defaultdict(list)
    for r in rows:
        by_end[r["end"][:10]].append(r)
    for d, rs in by_end.items():
        total = sum(r["days"].get(d, 0) for r in rs)
        body = "".join(entry(r) for r in rs)
        sections.append(
            f'<section id="d{d}"><h2>{datetime.fromisoformat(d):%a %d %b %Y} · {fmt_min(total)}</h2>{body}</section>'
        )

    total = sum(r["active_min"] for r in rows)
    costs = {p: round(sum(r.get("cost_usd") or 0 for r in rs), 2) for p, rs in per_proj.items()}
    costs[""] = round(sum(r.get("cost_usd") or 0 for r in rows), 2)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Agent log</title>
<style>{CSS}</style></head><body>
<header><h1>Agent log</h1>
<span class="stat"><b>{len(rows)}</b> sessions</span>
<span class="stat"><b>{len(per_proj)}</b> projects</span>
<span class="stat"><b>{fmt_min(total)}</b> active</span>
<span class="stat"><b>{fmt_min(week)}</b> last 7 days</span>
<span class="stat" id="spent" data-costs="{escape(json.dumps(costs))}"></span></header>
<div id="strip">{bars}</div>
<div class="axis"><span>{span[0]}</span><span>active time per day, last {days_back} days</span><span>{span[-1]}</span></div>
<div class="wrap"><aside>
<input id="q" type="search" placeholder="Search…" autofocus>
<select id="h"><option value="">all harnesses</option><option>claude</option><option>opencode</option></select>
<div id="projs">{projects}</div></aside><main>{"".join(sections)}</main></div>
<script>{JS}</script></body></html>"""


def entry(r: dict) -> str:
    start, end = datetime.fromisoformat(r["start"]), datetime.fromisoformat(r["end"])
    when = f"{start:%H:%M}–{end:%H:%M}" if start.date() == end.date() else f"{start:%d %b %H:%M} – {end:%d %b %H:%M}"
    s = r.get("summary") or {}
    title = s.get("title") or r.get("title") or r["first_prompt"][:100]
    fields = [(k, s[k]) for k in ("before", "did", "after") if s.get(k)] or (
        [("after", r["recap"])] if r.get("recap") else []
    )
    dl = "".join(f"<dt>{k}</dt><dd>{escape(v)}</dd>" for k, v in fields)
    extra = " · ".join(
        x
        for x in (r.get("model") or "", f"{r['prompts']} prompts", f"${r['cost_usd']:.2f}" if r.get("cost_usd") else "")
        if x
    )
    tip = escape(f"{r['key']}\n{r['cwd']}\nfirst prompt: {r['first_prompt']}")
    return (
        f'<div class="e" data-p="{escape(r["project"])}" data-h="{r["harness"]}" title="{tip}">'
        f'<div class="meta"><span class="p" data-pick="{escape(r["project"])}">{escape(r["project"])}</span>'
        f"<span>{when}</span><span>{fmt_min(r['active_min'])} active</span>"
        f'<span class="h {r["harness"]}">{r["harness"]}</span><span>{escape(extra)}</span></div>'
        f'<div class="t">{escape(title)}</div>{f"<dl>{dl}</dl>" if dl else ""}</div>'
    )


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.split("?")[0] == "/api/sessions":
            body, ctype = json.dumps(list(store.load().values())).encode(), "application/json"
        elif self.path.split("?")[0] in ("/", "/index.html"):
            body, ctype = page(store.load()).encode(), "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


def serve(host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"agentlog: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
