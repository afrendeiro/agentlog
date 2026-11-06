import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta

import pytest

from agentlog import store, web
from agentlog.common import Session


def record(project: str, title: str) -> dict:
    t = datetime.now().astimezone().replace(microsecond=0)
    s = Session("claude", "s1", "/w", times=[t - timedelta(minutes=m) for m in (30, 20, 10, 0)], prompts=["p"],
                transcript=["USER: p", "AGENT: a"])  # fmt: skip
    r = {**store.record(s, None), "project": project, "cost_usd": 1.5}
    r["summary"] = {"title": title, "before": "b", "did": "d", "after": "a"}
    return r


def test_page_renders_and_escapes():
    r = record("<b>proj</b>", "<script>alert(1)</script>")
    html = web.page({r["key"]: r})
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;b&gt;proj&lt;/b&gt;" in html
    assert "<b>1</b> sessions" in html
    assert "30m</b> last 7 days" in html


def test_page_with_no_sessions():
    assert "<b>0</b> sessions" in web.page({})


@pytest.fixture
def server():
    srv = web.ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def test_server_routes(server):
    r = record("app", "Did a thing")
    store.save({r["key"]: r})
    with urllib.request.urlopen(server + "/") as resp:
        assert "Did a thing" in resp.read().decode()
    with urllib.request.urlopen(server + "/api/sessions") as resp:
        assert json.loads(resp.read())[0]["key"] == r["key"]
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(server + "/nope")
    assert e.value.code == 404
    e.value.close()
