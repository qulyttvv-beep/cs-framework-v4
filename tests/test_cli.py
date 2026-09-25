"""Integration tests that drive the CLI as a subprocess (headless)."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_version_flag(run_cli):
    r = run_cli("--version")
    assert r.returncode == 0
    assert "4.1.0" in r.stdout


def test_version_subcommand(run_cli):
    r = run_cli("version")
    assert r.returncode == 0
    assert "CS Framework" in r.stdout and "4.1.0" in r.stdout


def test_help_lists_many_commands(run_cli):
    r = run_cli("--help")
    assert r.returncode == 0
    for cmd in ("chat", "serve", "connect", "health", "hex", "rig", "stop", "ps"):
        assert cmd in r.stdout, f"{cmd} missing from --help"


def test_selftest_passes(run_cli):
    r = run_cli("selftest")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "passed" in r.stdout


def test_list_headless_no_forced_setup(run_cli):
    # `list` must run without triggering the interactive first-run wizard.
    r = run_cli("list")
    assert r.returncode == 0
    assert "first launch" not in r.stdout
    assert "RUNTIMES" in r.stdout


def test_scan_headless(run_cli):
    r = run_cli("scan")
    assert r.returncode == 0


def test_doctor_runs(run_cli):
    r = run_cli("doctor")
    assert r.returncode == 0
    assert "summary" in r.stdout.lower() or "cli" in r.stdout.lower()


def test_platforms_lists_connectors(run_cli):
    r = run_cli("platforms")
    assert r.returncode == 0
    for name in ("openai", "anthropic", "ollama"):
        assert name in r.stdout


def test_unknown_command_errors(run_cli):
    r = run_cli("definitely-not-a-command")
    assert r.returncode == 2
    assert "invalid choice" in (r.stdout + r.stderr)


def test_serve_health_and_models(cs_script: Path, tmp_path: Path):
    port = _free_port()
    env = dict(os.environ)
    env["CS_HOME"] = str(tmp_path / "home")
    env["CS_NO_COLOR"] = "1"
    # Capture server output to a file (not a PIPE) so a chatty startup can never
    # fill the OS pipe buffer and deadlock the server process.
    log_path = tmp_path / "serve.log"
    log_fh = open(log_path, "w", encoding="utf-8")

    def _log() -> str:
        try:
            return Path(log_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return "(no log)"

    proc = subprocess.Popen(
        [sys.executable, str(cs_script), "serve", "--host", "127.0.0.1",
         "--port", str(port)],
        stdout=log_fh, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, env=env, text=True,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        deadline = time.time() + 40
        health = None
        while time.time() < deadline:
            if proc.poll() is not None:
                pytest.fail("serve exited early:\n" + _log())
            try:
                with urllib.request.urlopen(base + "/health", timeout=2) as fh:
                    health = json.loads(fh.read().decode())
                    break
            except Exception:
                time.sleep(0.4)
        assert health and health.get("ok") is True, "no /health response:\n" + _log()
        assert health.get("version") == "4.1.0"

        with urllib.request.urlopen(base + "/v1/models", timeout=5) as fh:
            models = json.loads(fh.read().decode())
        assert models.get("object") == "list"
        assert isinstance(models.get("data"), list)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_fh.close()
