"""Tests for the `cs studio` graphical app (server + endpoints + streaming)."""
from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

import cs


def _free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


@contextlib.contextmanager
def _studio(cs_script: Path, home: Path):
    port = _free_port()
    env = dict(os.environ)
    env["CS_HOME"] = str(home)
    env["CS_NO_COLOR"] = "1"
    log = open(home_parent_log(home), "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(cs_script), "studio", "--no-open",
         "--host", "127.0.0.1", "--port", str(port)],
        stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env, text=True,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 40
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError("studio exited early")
            try:
                with urllib.request.urlopen(base + "/health", timeout=2) as fh:
                    if fh.status == 200:
                        break
            except Exception:
                time.sleep(0.4)
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


def home_parent_log(home: Path) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    return home / "studio.log"


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as fh:
        return json.loads(fh.read().decode())


def _post(url, obj):
    data = json.dumps(obj).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as fh:
        return fh.read().decode()


# ---- unit: the embedded SPA is present and coherent ----
def test_app_html_constant():
    html = cs.APP_HTML
    assert "<!DOCTYPE html>" in html
    assert "CS Framework" in html
    assert "/api/chat" in html and "/api/state" in html
    assert "artifact" in html.lower()


def test_demo_stream_yields_text():
    out = "".join(cs._demo_stream([{"role": "user", "content": "hi there"}]))
    assert "CS Echo" in out and "hi there" in out


# ---- integration: the running app ----
def test_studio_serves_html(cs_script: Path, tmp_path: Path):
    with _studio(cs_script, tmp_path / "home") as base:
        with urllib.request.urlopen(base + "/", timeout=5) as fh:
            body = fh.read().decode()
        assert "<!DOCTYPE html>" in body and "CS Framework" in body


def test_studio_state(cs_script: Path, tmp_path: Path):
    with _studio(cs_script, tmp_path / "home") as base:
        st = _get(base + "/api/state")
        assert st["version"] == cs.VERSION
        ids = [m["id"] for m in st["models"]]
        assert cs.DEMO_MODEL_ID in ids
        assert isinstance(st["runtimes"], list) and st["runtimes"]


def test_studio_chat_echo_streams(cs_script: Path, tmp_path: Path):
    with _studio(cs_script, tmp_path / "home") as base:
        data = json.dumps({"model": "cs-echo",
                           "messages": [{"role": "user", "content": "ping"}]}).encode()
        req = urllib.request.Request(base + "/api/chat", data=data,
                                     headers={"Content-Type": "application/json"})
        text_tokens, done = [], False
        with urllib.request.urlopen(req, timeout=15) as fh:
            for raw in fh.read().decode().split("\n\n"):
                if not raw.startswith("data:"):
                    continue
                ev = json.loads(raw[5:].strip())
                if ev.get("type") == "token":
                    text_tokens.append(ev["text"])
                elif ev.get("type") == "done":
                    done = True
        assert done
        assert "ping" in "".join(text_tokens)


def test_studio_routine_crud(cs_script: Path, tmp_path: Path):
    with _studio(cs_script, tmp_path / "home") as base:
        _post(base + "/api/routines",
              {"routine": {"name": "T", "model": "cs-echo", "prompt": "hi",
                           "every_minutes": 60, "enabled": True}})
        rs = _get(base + "/api/routines")["routines"]
        assert len(rs) == 1 and rs[0]["name"] == "T"
        rid = rs[0]["id"]
        run = json.loads(_post(base + "/api/routines/run", {"id": rid}))
        assert run["ok"] and "CS Echo" in run["output"]
        _post(base + "/api/routines/delete", {"id": rid})
        assert _get(base + "/api/routines")["routines"] == []


def test_studio_mcp_config_and_graceful_tools(cs_script: Path, tmp_path: Path):
    with _studio(cs_script, tmp_path / "home") as base:
        _post(base + "/api/mcp",
              {"server": {"name": "nope", "command": "definitely-not-a-real-cmd",
                          "args": [], "enabled": True}})
        cfg = _get(base + "/api/mcp")
        assert cfg["servers"] and cfg["servers"][0]["command"] == "definitely-not-a-real-cmd"
        # listing tools for an unreachable server must not crash the server
        res = json.loads(_post(base + "/api/mcp/tools", {"ids": None}))
        assert res["tools"] == []
