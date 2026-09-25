"""Spark X features: Ollama start/revive/pull/delete, free models with
failover, the computer tool's coordinate mapping, Blender plumbing and the
model catalog. External services are replaced by local fakes."""
from __future__ import annotations

import json
import os
import stat
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

import cs
from test_app import TOKEN, _free_port, _MockServer, _studio  # noqa: F401

HERE = Path(__file__).resolve().parent
POSIX = os.name != "nt"


def _wait(fn, timeout=30.0, step=0.25):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


# ── Ollama ───────────────────────────────────────────────────────────────────
@pytest.fixture
def fake_ollama_env(tmp_path):
    """PATH with an `ollama` shim running tests/fake_ollama.py, on a free port."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    shim = bindir / "ollama"
    shim.write_text(f"#!/bin/sh\nexec {sys.executable} {HERE / 'fake_ollama.py'} \"$@\"\n")
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    port = _free_port()
    return {"PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
            "OLLAMA_HOST": f"127.0.0.1:{port}", "OLLAMA_MODELS": str(tmp_path / "ollama-models"),
            "SPARKX_WATCHDOG_S": "1"}


@pytest.mark.skipif(not POSIX, reason="the ollama shim is a POSIX shell script")
def test_ollama_autostart_revive_pull_delete(tmp_path, fake_ollama_env):
    import signal
    with _studio(tmp_path / "home", fake_ollama_env) as s:
        # Spark X starts Ollama on launch
        st = _wait(lambda: (lambda d: d if d["running"] else None)(s.get("/api/ollama")[1]))
        assert st and st["installed"] and st["version"] == "0.99.0-fake"
        # kill it: the watchdog revives it
        import urllib.request
        req = urllib.request.Request(f"http://{fake_ollama_env['OLLAMA_HOST']}/api/version")
        pid = json.loads(cs._urlopen(req, 3).read())["pid"]      # the fake reports its pid
        os.kill(pid, signal.SIGKILL)
        revived = _wait(lambda: (lambda d: d if d["running"] and d["revived"] >= 1 else None)(s.get("/api/ollama")[1]),
                        timeout=40)
        assert revived, "Ollama was not revived"
        # pull with progress, then the model shows up in the model menu
        job = s.post("/api/ollama/pull", {"model": "qwen3:4b"})[1]
        done = _wait(lambda: (lambda j: j if j["status"] != "running" else None)(s.get(f"/api/jobs/{job['id']}")[1]))
        assert done["status"] == "done" and done["progress"] == 1.0
        st = s.get("/api/ollama")[1]
        assert [m["name"] for m in st["models"]] == ["qwen3:4b"]
        assert "tools" in st["models"][0]["caps"]
        ids = [m["id"] for m in s.get("/api/state")[1]["models"]]
        assert "ollama/qwen3:4b" in ids
        # chat through the local model
        events = s.chat({"model": "ollama/qwen3:4b", "messages": [{"role": "user", "content": "hi"}]})
        assert "".join(e["text"] for e in events if e["type"] == "token") == "hi from fake ollama"
        # a failed pull reports the error
        bad = s.post("/api/ollama/pull", {"model": "missing-model"})[1]
        bad = _wait(lambda: (lambda j: j if j["status"] != "running" else None)(s.get(f"/api/jobs/{bad['id']}")[1]))
        assert bad["status"] == "error" and "does not exist" in bad["error"]
        # delete
        assert s.post("/api/ollama/delete", {"model": "qwen3:4b"})[0] == 200
        assert s.get("/api/ollama")[1]["models"] == []
        # Ollama outlives Spark X by design; stop the fake so it doesn't linger
        pid = json.loads(cs._urlopen(req, 3).read())["pid"]
        os.kill(pid, signal.SIGKILL)


def test_ollama_base_url(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0")
    assert cs._ollama_base() == "http://127.0.0.1:11434"
    monkeypatch.setenv("OLLAMA_HOST", "http://gpu-box:8000")
    assert cs._ollama_base() == "http://gpu-box:8000"


def test_pull_rejects_bad_names():
    with pytest.raises(ValueError):
        cs._ollama_pull("qwen3; rm -rf /")


# ── free models ──────────────────────────────────────────────────────────────
class _FreeMock(BaseHTTPRequestHandler):
    """A keyless provider. `broken` answers /models but fails chats with 503."""
    broken = False
    delay = 0.0
    label = "?"

    def log_message(self, *a):
        pass

    def do_GET(self):
        time.sleep(self.delay)
        body = json.dumps([{"name": "openai", "output_modalities": ["text"], "vision": True},
                           {"name": "flux", "output_modalities": ["image"]}]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.broken:
            self.send_response(503)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        ev = {"choices": [{"delta": {"content": f"free reply from {self.label}"}, "index": 0}]}
        self.wfile.write(b"data: " + json.dumps(ev).encode() + b"\n\ndata: [DONE]\n\n")


def _serve(handler_cls):
    srv = _MockServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def test_free_model_fails_over_to_a_working_service(tmp_path):
    down = type("Down", (_FreeMock,), {"broken": True, "label": "down"})
    up = type("Up", (_FreeMock,), {"delay": 0.3, "label": "up"})    # slower, so it's tried second
    s1, u1 = _serve(down)
    s2, u2 = _serve(up)
    provs = [{"id": "down", "name": "Down", "base_url": u1, "probe": u1 + "/models", "prefer": ["openai"]},
             {"id": "up", "name": "Up", "base_url": u2, "probe": u2 + "/models", "prefer": ["openai"]}]
    try:
        with _studio(tmp_path / "home", {"SPARKX_FREE_PROVIDERS": json.dumps(provs)}) as s:
            free = s.get("/api/free?force=1")[1]
            assert [p["id"] for p in free["providers"]] == ["down", "up"]
            assert all(p["ok"] and p["model"] == "openai" for p in free["providers"])
            r = s.post("/api/free/enable", {})[1]
            assert r["working"]
            st = s.get("/api/state")[1]
            assert st["free_enabled"]
            m = next(m for m in st["models"] if m["id"] == "free/auto")
            assert m["group"] == "Free" and m["free"]
            assert st["prefs"]["default_model"] == "free/auto"
            events = s.chat({"model": "free/auto", "messages": [{"role": "user", "content": "hello"}]})
            assert next(e for e in events if e["type"] == "provider")["name"] == "Up"
            assert "free reply from up" in "".join(e.get("text", "") for e in events if e["type"] == "token")
            assert s.post("/api/free/disable", {})[0] == 200
            assert "free/auto" not in [m["id"] for m in s.get("/api/state")[1]["models"]]
    finally:
        s1.shutdown(); s2.shutdown()


def test_free_model_reports_when_nothing_answers(tmp_path):
    provs = [{"id": "gone", "name": "Gone", "base_url": "http://127.0.0.1:9/v1",
              "probe": "http://127.0.0.1:9/v1/models"}]
    with _studio(tmp_path / "home", {"SPARKX_FREE_PROVIDERS": json.dumps(provs)}) as s:
        assert not s.post("/api/free/enable", {})[1]["working"]
        events = s.chat({"model": "free/auto", "messages": [{"role": "user", "content": "hello"}]})
        err = next(e for e in events if e["type"] == "error")["error"]
        assert "No free AI service is reachable" in err


# ── computer control ─────────────────────────────────────────────────────────
class _FakePG:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def rec(*a, **k):
            self.calls.append((name, a, k))
        return rec

    def size(self):
        return (2560, 1440)

    def position(self):
        return (1280, 720)


def test_computer_maps_screenshot_coordinates_to_the_screen(monkeypatch):
    pg = _FakePG()
    monkeypatch.setattr(cs, "_pyautogui", lambda: pg)
    monkeypatch.setitem(cs._CU_STATE, "geom", (1280, 720, 2560, 1440))   # shot is half size
    out = cs._t_computer({"action": "click", "x": 640, "y": 360, "screenshot": False})
    assert pg.calls[-1][0] == "click" and pg.calls[-1][1][:2] == (1280, 720)
    assert "click" in out["text"]
    cs._t_computer({"action": "double_click", "x": 10, "y": 5000, "screenshot": False})   # clamped
    name, args, kw = pg.calls[-1]
    assert args[:2] == (20, 1438) and kw["clicks"] == 2
    cs._t_computer({"action": "drag", "x": 0, "y": 0, "to_x": 100, "to_y": 50, "screenshot": False})
    assert pg.calls[-1][0] == "dragTo" and pg.calls[-1][1][:2] == (200, 100)
    cs._t_computer({"action": "key", "keys": "ctrl+shift+t", "screenshot": False})
    assert pg.calls[-1] == ("hotkey", ("ctrl", "shift", "t"), {})
    cs._t_computer({"action": "key", "keys": "Return", "screenshot": False})
    assert pg.calls[-1] == ("press", ("enter",), {})
    assert "unknown action" in cs._t_computer({"action": "teleport"})["text"]


def test_key_names_follow_the_platform(monkeypatch):
    monkeypatch.setattr(cs.sys, "platform", "darwin")
    assert cs._norm_keys("cmd+space") == ["command", "space"]
    assert cs._norm_keys("win+d") == ["command", "d"]
    monkeypatch.setattr(cs.sys, "platform", "win32")
    assert cs._norm_keys("cmd+c") == ["ctrl", "c"]
    assert cs._norm_keys(["Control", "Esc"]) == ["ctrl", "escape"]


def test_screenshots_are_pruned_from_history_but_attachments_kept():
    shot = lambda: {"role": "user", "content": [{"type": "text", "text": cs._SHOT_MARK},
                                               {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AA"}}]}
    attached = {"role": "user", "content": [{"type": "text", "text": "what is this?"},
                                            {"type": "image_url", "image_url": {"url": "data:image/png;base64,BB"}}]}
    msgs = [attached, shot(), {"role": "assistant", "content": "ok"}, shot()]
    cs._drop_old_images(msgs, keep=1)
    kinds = [[p["type"] for p in m["content"]] for m in msgs if isinstance(m["content"], list)]
    assert kinds == [["text", "image_url"], ["text", "text"], ["text", "image_url"]]


def test_native_tool_args_are_parsed_tolerantly():
    assert cs._parse_tool_args("") == {}
    assert cs._parse_tool_args('{"a": 1}') == {"a": 1}
    assert cs._parse_tool_args({"a": 2}) == {"a": 2}
    assert cs._parse_tool_args('{"a": 1}{"a": 1, "b": 2}') == {"a": 1, "b": 2}   # repeated chunks
    with pytest.raises(ValueError):
        cs._parse_tool_args("not json")


def test_tool_schemas_cover_every_studio_tool():
    names = sorted({t for ts in cs._TOOLSETS.values() for t in ts})
    tools, name_map = cs._tool_schemas(names, [{"qualified": "fs server__read file", "name": "read file",
                                                "schema": {"type": "object", "properties": {"p": {"type": "string"}}}}])
    declared = [t["function"]["name"] for t in tools]
    assert set(names) <= set(declared)
    assert "fs_server__read_file" in declared and name_map["fs_server__read_file"] == "fs server__read file"
    for t in tools:
        assert t["function"]["parameters"]["type"] == "object"


def test_approval_rules_per_action():
    assert not cs._needs_approval("computer", {"action": "screenshot"}, False)
    assert cs._needs_approval("computer", {"action": "click", "x": 1, "y": 1}, False)
    assert not cs._needs_approval("blender", {"action": "status"}, False)
    assert cs._needs_approval("blender", {"action": "run", "code": "pass"}, False)
    assert cs._needs_approval("open", {"target": "x"}, False)
    assert not cs._needs_approval("read", {"path": "x"}, False)


# ── Blender ──────────────────────────────────────────────────────────────────
FAKE_BLENDER = r'''#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
if "--version" in args:
    print("Blender 9.9.9 (fake)"); sys.exit(0)
script = args[args.index("--python") + 1]
src = open(script, encoding="utf-8").read()
assert "def render(" in src and "def save(" in src          # the prelude is there
out = os.environ["SPARKX_OUT"]
code = src.split("# ── model code ──", 1)[1]
if "boom" in code:
    print("Traceback (most recent call last):\nNameError: name 'boom' is not defined"); sys.exit(1)
if "render(" in code:
    import base64
    png = os.path.join(out, "render_1.png")
    open(png, "wb").write(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="))
    print("SPARKX_IMAGE:" + png)
print("Fra:1 Mem:10M | noise that should be filtered")
print("built the scene")
'''


@pytest.mark.skipif(not POSIX, reason="the fake blender is a POSIX script")
def test_blender_run_returns_log_and_render(tmp_path, monkeypatch):
    fake = tmp_path / "blender"
    fake.write_text(FAKE_BLENDER.replace("#!/usr/bin/env python3", "#!" + sys.executable))
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("BLENDER_PATH", str(fake))
    cs._BLENDER_VER.clear()
    assert "9.9.9" in cs._t_blender({"action": "status"})
    out = cs._t_blender({"action": "run", "code": "clear_scene()\nbpy.ops.mesh.primitive_monkey_add()\nrender()"})
    assert "exited with code 0" in out["text"] and "built the scene" in out["text"]
    assert "Fra:1" not in out["text"]
    assert out["image"] and Path(out["image"]).is_file()
    bad = cs._t_blender({"action": "run", "code": "boom()"})
    assert "exited with code 1" in bad["text"] and "NameError" in bad["text"]


def test_blender_live_without_bridge_explains(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "_bridge_file", lambda: tmp_path / "none.json")
    with pytest.raises(RuntimeError, match="isn't connected"):
        cs._t_blender({"action": "live", "code": "pass"})


# ── catalog ──────────────────────────────────────────────────────────────────
def test_catalog_marks_what_fits_this_machine(monkeypatch):
    monkeypatch.setitem(cs._HW, "ram_gb", 16.0)
    monkeypatch.setitem(cs._HW, "vram_gb", 0.0)
    monkeypatch.setitem(cs._HW, "apple_silicon", False)
    view = cs._catalog_view()
    by_id = {m["id"]: m for m in view["models"]}
    assert by_id["qwen3:8b"]["fits"] and not by_id["gpt-oss:120b"]["fits"]
    picks = {tag for m in view["models"] for tag in m.get("best_for", [])}
    assert {"general", "coding", "vision"} <= picks
    assert all(m["fits"] for m in view["models"] if m.get("best_for"))


def test_catalog_file_is_valid():
    data = json.loads((Path(cs.__file__).parent / "cs_studio" / "static" / "catalog.json").read_text())
    ids = [m["id"] for m in data["models"]]
    assert len(ids) == len(set(ids))
    for m in data["models"]:
        assert {"id", "name", "size_gb", "min_ram", "tags", "blurb", "score"} <= set(m)
    for p in data["free_providers"]:
        assert p["base_url"].startswith("https://") and p["probe"].startswith("https://")


# ── the see-and-act loop ─────────────────────────────────────────────────────
class _ScriptedRT:
    """A fake runtime that asks for two computer actions, then answers."""
    def __init__(self):
        self.seen = []
        self.turn = 0

    def chat(self, rec, msgs, ctx, tools=None):
        self.seen.append(json.loads(json.dumps(msgs)))
        self.turn += 1
        if self.turn == 1:
            yield ("text", "Let me look.")
            yield ("tool_calls", [{"id": "c1", "name": "computer", "arguments": '{"action": "screenshot"}'}])
        elif self.turn == 2:
            yield ("tool_calls", [{"id": "c2", "name": "computer", "arguments": '{"action": "click", "x": 5, "y": 6}'}])
        else:
            yield ("text", "Clicked the button.")


def test_vision_agent_sees_each_new_screenshot(tmp_path, monkeypatch):
    shots = []

    def fake_computer(a, cwd=None):
        p = tmp_path / f"shot{len(shots)}.jpg"
        p.write_bytes(b"\xff\xd8\xff\xe0 fake jpeg %d" % len(shots))   # only passed through as base64
        shots.append(a.get("action"))
        return {"text": f"did {a.get('action')}", "image": str(p)}

    monkeypatch.setitem(cs.TOOLS_IMPL, "computer", fake_computer)
    rt, events = _ScriptedRT(), []
    rec = cs.ModelRec("x/y", Path("x"), "platform", 0, "remote-api", "platform", meta={"platform": "x", "model": "y"})
    run = {"rec": rec, "rt": rt, "ctx": {"system": "s"}, "enabled": ["computer"], "mcp_tools": [], "cwd": str(tmp_path),
           "send": events.append, "state": {"cancel": False, "output": False}, "allowed": {"computer"},
           "vision": True, "is_api": True, "rounds": 10}
    cs._agent_native([{"role": "user", "content": "click the button"}], run)
    assert shots == ["screenshot", "click"]
    # the model saw the screenshot taken after each of its actions, as an image
    second, third = rt.seen[1], rt.seen[2]
    assert second[-1]["content"][0]["text"] == cs._SHOT_MARK and second[-1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    imgs_in_third = [p for m in third if isinstance(m.get("content"), list) for p in m["content"] if p["type"] == "image_url"]
    assert len(imgs_in_third) == 1                                  # only the newest screenshot is kept
    assert [m["role"] for m in third if m["role"] == "tool"] == ["tool", "tool"]
    assert "Clicked the button." in "".join(e.get("text", "") for e in events if e["type"] == "token")
    assert [e["type"] for e in events if e["type"].startswith("tool")] == ["tool_call", "tool_result", "tool_call", "tool_result"]


# ── the Blender bridge add-on (with a stand-in bpy) ──────────────────────────
def _load_bridge(monkeypatch, port):
    import importlib.util
    import types
    timers = types.SimpleNamespace(register=lambda *a, **k: None, unregister=lambda *a: None,
                                   is_registered=lambda f: False)
    bpy = types.SimpleNamespace(app=types.SimpleNamespace(timers=timers, version_string="5.0.1", background=False),
                                data=types.SimpleNamespace(objects=["Cube"]), context=None, ops=None)
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    monkeypatch.setitem(sys.modules, "bmesh", types.ModuleType("bmesh"))
    mu = types.ModuleType("mathutils"); mu.Vector = tuple
    monkeypatch.setitem(sys.modules, "mathutils", mu)
    monkeypatch.setenv("SPARKX_BRIDGE_PORT", str(port))
    spec = importlib.util.spec_from_file_location(
        "spark_x_bridge_test", Path(cs.__file__).parent / "cs_studio" / "blender" / "spark_x_bridge.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_blender_bridge_runs_code_and_checks_the_token(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path)); monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(cs, "_bridge_file", lambda: tmp_path / ".sparkx" / "blender-bridge.json")
    br = _load_bridge(monkeypatch, _free_port())
    br.start()
    try:
        assert cs._blender_status()["bridge"]["connected"]
        out = {}
        t = threading.Thread(target=lambda: out.update(
            ok=cs._bridge_call("print('hi from blender'); result = len(D.objects)", timeout=10),
            bad=cs._bridge_call("1/0", timeout=10)))
        t.start()
        while t.is_alive():
            br._pump(); time.sleep(0.01)
        assert out["ok"]["ok"] and out["ok"]["output"] == "hi from blender\n" and out["ok"]["result"] == "1"
        assert not out["bad"]["ok"] and "ZeroDivisionError" in out["bad"]["error"]
        import socket
        with socket.create_connection(("127.0.0.1", br.PORT)) as s:
            s.sendall(b'{"token": "nope", "code": "print(1)"}\n')
            assert json.loads(s.recv(1000))["error"] == "bad token"
        with pytest.raises(OSError):                                  # port taken: fails loudly
            _load_bridge(monkeypatch, br.PORT).start()
    finally:
        br.stop()


# ── packaging ────────────────────────────────────────────────────────────────
def test_installed_builds_keep_data_in_the_user_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    app = tmp_path / "Spark X"
    app.mkdir()
    monkeypatch.setattr(sys, "executable", str(app / "Spark X.exe"))
    assert not cs._installed_layout()                      # portable folder: data next to it
    (app / "INSTALLED").write_text("x")
    assert cs._installed_layout()                          # Windows installer marker
    mac = tmp_path / "Spark X.app" / "Contents" / "MacOS"
    mac.mkdir(parents=True)
    monkeypatch.setattr(sys, "executable", str(mac / "Spark X"))
    assert cs._installed_layout()                          # a macOS .app is always installed
    assert cs._user_data_dir().name.lower().replace(" ", "-") == "spark-x"


def test_the_app_executable_opens_the_window_and_cs_stays_a_cli(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    for exe, gui in (("Spark X.exe", True), ("Spark X", True), ("spark-x", True),
                     ("cs.exe", False), ("cs", False), ("cs-windows-x86_64.exe", False)):
        monkeypatch.setattr(sys, "executable", str(Path("/opt/app") / exe))
        assert cs._is_gui_exe() is gui, exe
    monkeypatch.setattr(sys, "frozen", False)
    assert not cs._is_gui_exe()                            # running from source: always the CLI


def test_starts_without_a_console(tmp_path):
    """The windowed app has no stdin/stdout/stderr at all; importing and running
    must not touch them (it used to crash on sys.stdout.isatty())."""
    import subprocess
    code = ("import sys; sys.stdin = sys.stdout = sys.stderr = None; "
            f"sys.path.insert(0, {str(Path(cs.__file__).parent)!r}); "
            "sys.argv = ['cs', 'version']; import cs; cs.main(); "
            f"open({str(tmp_path / 'ok')!r}, 'w').write(cs.VERSION)")
    r = subprocess.run([sys.executable, "-c", code], env=dict(os.environ, CS_HOME=str(tmp_path / "home")),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "ok").read_text() == cs.VERSION


def test_build_files_point_at_real_files():
    import re
    root = Path(cs.__file__).parent
    for spec in ("cs.spec", "sparkx.spec"):
        text = (root / spec).read_text(encoding="utf-8")
        for rel in set(re.findall(r'"(assets/[^"]+)"', text)):
            assert (root / rel).is_file(), f"{spec} → {rel}"
        for rel in set(re.findall(r'app_files\("([^"]+)"\)', text)):
            assert (root / rel).is_dir(), f"{spec} → {rel}"
    iss = (root / "packaging" / "sparkx.iss").read_text(encoding="utf-8")
    assert (root / "assets" / "sparkx.ico").is_file() and "SetupIconFile=..\\assets\\sparkx.ico" in iss
    assert (root / "packaging" / "INSTALLED").is_file()
    wf = (root / ".github" / "workflows" / "package.yml").read_text(encoding="utf-8")
    name = re.search(r"OutputBaseFilename=(\S+)", iss).group(1)
    assert f"app: {name}.exe" in wf                        # the release ships what Inno builds


def test_mouse_in_a_corner_stops_the_whole_task(monkeypatch):
    class FailSafeException(Exception):                     # what pyautogui raises
        pass

    def boom(a, cwd=None):
        raise FailSafeException("PyAutoGUI fail-safe triggered from mouse moving to a corner")
    monkeypatch.setitem(cs.TOOLS_IMPL, "computer", boom)
    monkeypatch.setitem(cs.CFG.setdefault("prefs", {}), "tool_approval", "auto")
    monkeypatch.setattr(cs, "_self_window", lambda action: False)
    sent, state = [], {"cancel": False}
    with pytest.raises(cs._Cancelled):
        cs._studio_run_tool("computer", {"action": "click", "x": 1, "y": 1}, None, {"computer"}, [], set(),
                            sent.append, state)
    assert state["cancel"] and "corner" in sent[-1]["text"]
    # any other failure is just reported back to the model
    monkeypatch.setitem(cs.TOOLS_IMPL, "computer", lambda a, cwd=None: 1 / 0)
    out, img = cs._studio_run_tool("computer", {"action": "click", "x": 1, "y": 1}, None, {"computer"}, [], set(),
                                   sent.append, {"cancel": False})
    assert out.startswith("[tool error") and img is None
