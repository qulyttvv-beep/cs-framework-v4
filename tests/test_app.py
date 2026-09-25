"""Tests for CS Studio: the secured local API, providers, the agentic chat
stream (including tool approvals), the code-workspace sandbox and the static
frontend. A tiny mock OpenAI-compatible server stands in for a cloud provider.
"""
from __future__ import annotations

import contextlib
import json
import os
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import cs

TOKEN = "test-studio-token"
ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


# ── mock OpenAI-compatible provider ──────────────────────────────────────────
class _Mock(BaseHTTPRequestHandler):
    """A tiny OpenAI-compatible provider. mock-a supports native function
    calling (streamed in pieces, like real providers); mock-b rejects `tools`
    with HTTP 400 so Spark X has to fall back to the text protocol."""
    requests: list = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.endswith("/models"):
            body = json.dumps({"data": [{"id": "mock-a"}, {"id": "mock-b"},
                                        {"id": "text-embedding-x"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404); self.end_headers()

    def _sse(self, deltas):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for d in deltas:
            ev = {"choices": [{"delta": d, "index": 0}]}
            self.wfile.write(b"data: " + json.dumps(ev).encode() + b"\n\n")
        self.wfile.write(b"data: [DONE]\n\n")

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        _Mock.requests.append(req)
        msgs = req.get("messages", [])
        if req.get("tools") and req.get("model") == "mock-b":
            body = json.dumps({"error": {"message": "mock-b does not support tools"}}).encode()
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        got_result = any(m.get("role") == "tool" or (m.get("role") == "user" and str(m.get("content", "")).startswith("<tool_result"))
                         for m in msgs)
        last = next((str(m.get("content", "")) for m in reversed(msgs) if m.get("role") == "user"), "")
        if got_result:
            reply = "All done."
        elif "use a tool" in last and req.get("tools"):
            self._sse([{"content": "Checking."},
                       {"tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                                        "function": {"name": "bash", "arguments": ""}}]},
                       {"tool_calls": [{"index": 0, "function": {"arguments": '{"cmd": "echo '}}]},
                       {"tool_calls": [{"index": 0, "function": {"arguments": 'hello-from-tool"}'}}]}])
            return
        elif "use a tool" in last:
            reply = 'Checking.\n<tool>{"name":"bash","args":{"cmd":"echo hello-from-tool"}}</tool>'
        else:
            reply = "mock says hi"
        self._sse([{"content": reply[i:i + 5]} for i in range(0, len(reply), 5)])


class _MockServer(ThreadingHTTPServer):
    def server_bind(self):          # skip the slow reverse-DNS lookup (macOS)
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


@pytest.fixture(scope="module")
def mock_openai():
    port = _free_port()
    srv = _MockServer(("127.0.0.1", port), _Mock)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}/v1"
    srv.shutdown()


# ── a running studio ─────────────────────────────────────────────────────────
class Studio:
    def __init__(self, base):
        self.base = base

    def req(self, path, body=None, token=TOKEN, headers=None, method=None):
        h = {"Content-Type": "application/json"}
        if token:
            h["X-CS-Token"] = token
        h.update(headers or {})
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(self.base + path, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(r, timeout=30) as fh:
                return fh.status, fh.read(), dict(fh.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def get(self, path, **kw):
        code, raw, _ = self.req(path, **kw)
        return code, (json.loads(raw) if raw[:1] in (b"{", b"[") else raw)

    def post(self, path, body, **kw):
        code, raw, _ = self.req(path, body=body, **kw)
        return code, json.loads(raw or b"{}")

    def chat(self, body, on_event=None):
        """Run /api/chat and return the list of SSE events."""
        r = urllib.request.Request(self.base + "/api/chat", data=json.dumps(body).encode(),
                                   headers={"Content-Type": "application/json", "X-CS-Token": TOKEN})
        events = []
        with urllib.request.urlopen(r, timeout=60) as fh:
            for line in fh:
                line = line.decode().strip()
                if not line.startswith("data:"):
                    continue
                ev = json.loads(line[5:])
                events.append(ev)
                if on_event:
                    on_event(ev)
                if ev.get("type") == "done":
                    break
        return events


@contextlib.contextmanager
def _studio(home: Path, extra_env=None):
    port = _free_port()
    home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, CS_HOME=str(home), CS_NO_COLOR="1", CS_STUDIO_TOKEN=TOKEN, **(extra_env or {}))
    log = open(home / "studio.log", "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(ROOT / "cs.py"), "studio", "--no-open",
                             "--host", "127.0.0.1", "--port", str(port)],
                            stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env)
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 40
        while True:
            if proc.poll() is not None:
                raise RuntimeError("studio exited early:\n" + (home / "studio.log").read_text())
            try:
                urllib.request.urlopen(base + "/health", timeout=2); break
            except Exception as e:
                if time.time() > deadline:
                    raise RuntimeError(f"studio never became healthy ({e}):\n"
                                       + (home / "studio.log").read_text())
                time.sleep(0.3)
        yield Studio(base)
    finally:
        proc.terminate()
        try: proc.wait(timeout=10)
        except subprocess.TimeoutExpired: proc.kill()
        log.close()


@pytest.fixture
def studio(tmp_path):
    with _studio(tmp_path / "home") as s:
        yield s


# ── static frontend ──────────────────────────────────────────────────────────
def test_static_frontend_is_packaged():
    static = ROOT / "cs_studio" / "static"
    for f in ("index.html", "studio.css", "studio.js", "icon.png", "favicon.png"):
        assert (static / f).is_file(), f
    html = (static / "index.html").read_text(encoding="utf-8")
    assert "__CS_TOKEN__" in html and "studio.js" in html


def test_ui_has_no_gradients():
    css = (ROOT / "cs_studio" / "static" / "studio.css").read_text(encoding="utf-8")
    assert "gradient(" not in css


def test_index_served_with_token_and_frame_protection(studio):
    code, raw, headers = studio.req("/", token=None)
    assert code == 200
    body = raw.decode()
    assert f'content="{TOKEN}"' in body and "__CS_TOKEN__" not in body
    assert headers.get("X-Frame-Options") == "DENY"


def test_static_path_traversal_blocked(studio):
    code, _, _ = studio.req("/static/..%2F..%2Fcs.py", token=None)
    assert code == 404


# ── API security ─────────────────────────────────────────────────────────────
def test_api_requires_token(studio):
    assert studio.req("/api/state", token=None)[0] == 403
    assert studio.req("/api/state", token="wrong")[0] == 403


def test_api_rejects_cross_origin(studio):
    code, _, _ = studio.req("/api/state", headers={"Origin": "https://evil.example"})
    assert code == 403


def test_api_rejects_foreign_host_header(studio):
    code, _, _ = studio.req("/api/state", headers={"Host": "evil.example"})
    assert code == 403


def test_browse_requires_browse_token(studio):
    # the main API token is not accepted by the sandboxed browser proxy
    code, _, _ = studio.req(f"/api/browse?url=example.com&t={TOKEN}", token=None)
    assert code == 403


# ── state / models / providers ───────────────────────────────────────────────
def test_state(studio):
    code, st = studio.get("/api/state")
    assert code == 200
    assert st["version"] == cs.VERSION
    assert cs.DEMO_MODEL_ID in [m["id"] for m in st["models"]]
    assert any(p["id"] == "groq" and p["free"] for p in st["providers"])


def test_provider_requires_key(studio):
    code, r = studio.post("/api/providers/connect", {"id": "groq"})
    assert code == 400 and "key" in r["error"].lower()


def test_custom_provider_models_and_streaming(studio, mock_openai):
    code, r = studio.post("/api/providers/connect",
                          {"id": "custom", "name": "Mock", "base_url": mock_openai, "key": "sk-secret-1234567890"})
    assert code == 200 and r["id"] == "mock"
    assert r["models"] == ["mock-a", "mock-b"]            # embedding model filtered out
    code, st = studio.get("/api/state")
    assert "sk-secret-1234567890" not in json.dumps(st)   # keys are never sent to the UI
    assert "mock/mock-a" in [m["id"] for m in st["models"]]
    events = studio.chat({"model": "mock/mock-a", "messages": [{"role": "user", "content": "hello"}]})
    text = "".join(e["text"] for e in events if e["type"] == "token")
    assert text == "mock says hi"
    assert events[-1]["type"] == "done"


def test_unreachable_custom_endpoint_is_rejected(studio):
    code, r = studio.post("/api/providers/connect",
                          {"id": "custom", "name": "Nope", "base_url": "http://127.0.0.1:9/v1"})
    assert code == 400


# ── the agentic loop + approvals ─────────────────────────────────────────────
def _tool_chat(studio, allow):
    def on_event(ev):
        if ev["type"] == "approval":
            studio.post("/api/approve", {"id": ev["id"], "allow": allow})
    return studio.chat({"model": "mock/mock-a", "tools": {"code": True},
                        "messages": [{"role": "user", "content": "please use a tool"}]}, on_event)


def test_tool_call_requires_and_honours_approval(studio, mock_openai):
    studio.post("/api/providers/connect", {"id": "custom", "name": "Mock", "base_url": mock_openai})
    events = _tool_chat(studio, allow=True)
    kinds = [e["type"] for e in events]
    assert "approval" in kinds
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["name"] == "bash" and "hello-from-tool" in result["result"]
    assert "All done." in "".join(e["text"] for e in events if e["type"] == "token")


def test_denied_tool_does_not_run(studio, mock_openai):
    studio.post("/api/providers/connect", {"id": "custom", "name": "Mock", "base_url": mock_openai})
    events = _tool_chat(studio, allow=False)
    result = next(e for e in events if e["type"] == "tool_result")
    assert "declined" in result["result"] and "hello-from-tool" not in result["result"]


def test_native_tool_call_sends_schemas(studio, mock_openai):
    studio.post("/api/providers/connect", {"id": "custom", "name": "Mock", "base_url": mock_openai})
    _Mock.requests.clear()
    _tool_chat(studio, allow=True)
    first = _Mock.requests[0]
    names = [t["function"]["name"] for t in first.get("tools", [])]
    assert "bash" in names and "read" in names
    bash = next(t for t in first["tools"] if t["function"]["name"] == "bash")
    assert bash["function"]["parameters"]["required"] == ["cmd"]
    second = _Mock.requests[1]["messages"]
    assert any(m.get("role") == "assistant" and m.get("tool_calls") for m in second)
    assert any(m.get("role") == "tool" and "hello-from-tool" in m.get("content", "") for m in second)


def test_text_protocol_fallback_when_tools_unsupported(studio, mock_openai):
    studio.post("/api/providers/connect", {"id": "custom", "name": "Mock", "base_url": mock_openai})
    events = studio.chat({"model": "mock/mock-b", "tools": {"code": True}, "allowed": ["bash"],
                          "messages": [{"role": "user", "content": "please use a tool"}]})
    result = next(e for e in events if e["type"] == "tool_result")
    assert "hello-from-tool" in result["result"]
    assert "All done." in "".join(e["text"] for e in events if e["type"] == "token")
    assert not any(e["type"] == "error" for e in events)


def test_tools_off_means_no_execution(studio, mock_openai):
    studio.post("/api/providers/connect", {"id": "custom", "name": "Mock", "base_url": mock_openai})
    events = studio.chat({"model": "mock/mock-a", "messages": [{"role": "user", "content": "please use a tool"}]})
    assert not any(e["type"] in ("tool_call", "tool_result", "approval") for e in events)


def test_demo_chat_streams(studio):
    events = studio.chat({"model": "cs-echo", "messages": [{"role": "user", "content": "ping"}]})
    assert "ping" in "".join(e.get("text", "") for e in events if e["type"] == "token")
    assert events[-1]["type"] == "done"


# ── code workspace sandbox ───────────────────────────────────────────────────
def test_fs_sandbox(studio, tmp_path):
    proj = tmp_path / "proj"; (proj / "src").mkdir(parents=True)
    (proj / "src" / "a.py").write_text("print('hi')\n")
    code, r = studio.post("/api/project/open", {"root": str(proj)})
    assert code == 200 and [e["name"] for e in r["entries"]] == ["src"]
    code, r = studio.get(f"/api/fs/read?root={proj}&path=src/a.py")
    assert code == 200 and "print" in r["content"]
    code, r = studio.get(f"/api/fs/read?root={proj}&path=../../etc/passwd")
    assert code == 400 and "outside" in r["error"]
    code, r = studio.post("/api/fs/write", {"root": str(proj), "path": "src/b.txt", "content": "ok"})
    assert code == 200 and (proj / "src" / "b.txt").read_text() == "ok"
    code, r = studio.post("/api/fs/write", {"root": str(proj), "path": "../escape.txt", "content": "x"})
    assert code == 400 and not (tmp_path / "escape.txt").exists()


# ── routines, connectors, chats ──────────────────────────────────────────────
def test_routine_crud(studio):
    studio.post("/api/routines", {"routine": {"name": "T", "model": "cs-echo", "prompt": "hi",
                                              "every_minutes": 60, "enabled": True}})
    rs = studio.get("/api/routines")[1]["routines"]
    assert len(rs) == 1
    run = studio.post("/api/routines/run", {"id": rs[0]["id"]})[1]
    assert run["ok"] and "Spark Echo" in run["output"]
    studio.post("/api/routines/delete", {"id": rs[0]["id"]})
    assert studio.get("/api/routines")[1]["routines"] == []


def test_mcp_unreachable_server_is_graceful(studio):
    studio.post("/api/mcp", {"server": {"name": "nope", "command": "definitely-not-a-real-cmd", "args": []}})
    assert studio.get("/api/mcp")[1]["servers"][0]["id"] == "nope"
    code, r = studio.post("/api/mcp/tools", {"ids": None})
    assert code == 200 and r["tools"] == []


def test_chat_save_list_delete(studio):
    code, r = studio.post("/api/chats", {"chat": {"title": "Hello", "messages": [{"role": "user", "content": "x"}]}})
    cid = r["id"]
    assert [c["id"] for c in studio.get("/api/chats")[1]["chats"]] == [cid]
    assert studio.get(f"/api/chats/{cid}")[1]["title"] == "Hello"
    studio.post("/api/chats/delete", {"id": cid})
    assert studio.get("/api/chats")[1]["chats"] == []


# ── unit-level helpers ───────────────────────────────────────────────────────
def test_demo_reply_variants():
    html = cs._demo_reply([{"role": "user", "content": "make me a landing page"}])
    assert "```html" in html
    py = cs._demo_reply([{"role": "user", "content": "write a python function"}])
    assert "```python" in py
    plain = cs._demo_reply([{"role": "user", "content": "a quick guide please"}])  # 'ui' inside a word
    assert "```" not in plain and "Spark Echo" in plain


def test_fs_resolve_rejects_escape(tmp_path):
    with pytest.raises(PermissionError):
        cs._fs_resolve(str(tmp_path), "../outside")
    with pytest.raises(ValueError):
        cs._fs_resolve("relative/path", "x")


def test_platform_records_one_per_model(monkeypatch):
    monkeypatch.setitem(cs.CFG, "platforms", {"p1": {"base_url": "http://x/v1", "no_key": True,
                                                    "models": ["m1", "m2"]}})
    recs = cs.platform_records()
    assert [r.name for r in recs] == ["p1/m1", "p1/m2"]
    assert recs[0].meta == {"platform": "p1", "model": "m1"}


def test_html_to_text_strips_scripts():
    title, text = cs._html_to_text("<html><title>T</title><script>evil()</script><p>Hello <b>world</b></p></html>")
    assert title == "T" and "Hello world" in text and "evil" not in text
