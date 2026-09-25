"""Unit tests for pure logic in cs.py (no network, no models)."""
from __future__ import annotations

import argparse
import inspect
import json
import re
from pathlib import Path

import cs


# ── architecture normalization ──────────────────────────────────────────────
def test_normalize_arch_known():
    assert cs.normalize_arch("qwen35") == "Qwen3ForCausalLM"
    assert cs.normalize_arch("qwen2.5") == "Qwen2ForCausalLM"
    assert cs.normalize_arch("bonsai") == "Qwen2ForCausalLM"
    assert cs.normalize_arch("BonsaiForCausalLM") == "Qwen2ForCausalLM"
    assert cs.normalize_arch("llama3.1") == "LlamaForCausalLM"


def test_normalize_arch_empty():
    assert cs.normalize_arch("") == "?"


def test_arch_chain_has_auto_fallback():
    chain = cs.arch_chain("bonsai")
    assert "AutoModelForCausalLM" in chain
    assert chain[0] == "Qwen2ForCausalLM"


# ── small utilities ─────────────────────────────────────────────────────────
def test_human_readable_sizes():
    assert cs.human(2 ** 30) == "1.00GB"
    assert cs.human(0) in ("0.00B", "0B", "0.0B")  # tolerate formatting


def test_fuzzy_match():
    assert cs.fuzzy("bns2", "bonsai-2")
    assert not cs.fuzzy("zzz", "bonsai-2")


def test_sha256_file(tmp_path: Path):
    p = tmp_path / "abc"
    p.write_bytes(b"abc")
    # SHA-256("abc")
    assert cs.sha256_file(p).startswith("ba7816bf")


def test_json_roundtrip(tmp_path: Path):
    p = tmp_path / "c.json"
    cs.jsave(p, {"a": 1, "b": [1, 2, 3]})
    assert cs.jload(p, {}) == {"a": 1, "b": [1, 2, 3]}


def test_jload_missing_returns_default(tmp_path: Path):
    assert cs.jload(tmp_path / "nope.json", {"d": True}) == {"d": True}


# ── model file parsing ──────────────────────────────────────────────────────
def _write_gguf(path: Path, arch: bytes = b"qwen35", name: bytes = b"bonsai-2"):
    def kv(k, v):
        return (len(k).to_bytes(8, "little") + k + (8).to_bytes(4, "little")
                + len(v).to_bytes(8, "little") + v)
    path.write_bytes(
        b"GGUF" + (3).to_bytes(4, "little") + (0).to_bytes(8, "little")
        + (2).to_bytes(8, "little")
        + kv(b"general.architecture", arch) + kv(b"general.name", name)
    )


def test_parse_gguf(tmp_path: Path):
    gg = tmp_path / "t.gguf"
    _write_gguf(gg)
    g = cs.parse_gguf(gg)
    assert g and g["meta"].get("general.architecture") == "qwen35"
    assert cs._arch_from_gguf(g) == "Qwen3ForCausalLM"


def test_parse_safetensors(tmp_path: Path):
    hdr = json.dumps({
        "w": {"dtype": "F32", "shape": [2, 2], "data_offsets": [0, 16]},
        "__metadata__": {"format": "pt"},
    }).encode()
    st = tmp_path / "t.safetensors"
    st.write_bytes(len(hdr).to_bytes(8, "little") + hdr + b"\x00" * 16)
    s = cs.parse_safetensors(st)
    assert s and s["tensors"] == 1 and s["ok"]


def test_verify_gguf(tmp_path: Path):
    gg = tmp_path / "t.gguf"
    _write_gguf(gg)
    rec = cs.ModelRec("t.gguf", gg, "gguf", gg.stat().st_size, "Qwen3ForCausalLM")
    _, ok = cs.verify_rec(rec, deep=True)
    assert ok


# ── code-mode tool spec (regression: descriptions used to be empty) ──────────
def test_tools_spec_all_have_descriptions():
    assert cs.TOOLS_SPEC, "TOOLS_SPEC is empty"
    for t in cs.TOOLS_SPEC:
        assert t["name"]
        assert t["desc"], f"tool {t['name']!r} has an empty description"


def test_tools_header_lists_tools():
    assert "bash" in cs.TOOLS_HEADER
    # a bit of a real description must be present, not just names
    assert "run a shell command" in cs.TOOLS_HEADER
    assert "<tool>" in cs.TOOLS_HEADER


def test_tool_regex_matches_one_call():
    calls = cs._TOOL_RX.findall('x <tool>{"name":"bash","args":{"cmd":"ls"}}</tool> y')
    assert len(calls) == 1


# ── CLI parser integrity (regression: main() dropped many subcommands) ───────
def _subparser_choices(ap: argparse.ArgumentParser) -> set:
    action = next(a for a in ap._actions
                  if isinstance(a, argparse._SubParsersAction))
    return set(action.choices.keys())


def test_every_build_cli_command_is_dispatched():
    ap = cs.build_cli()
    choices = _subparser_choices(ap)
    src = inspect.getsource(cs.main)
    handled = set(re.findall(r'a\.cmd == "([a-z0-9-]+)"', src))
    missing = choices - handled
    assert not missing, f"build_cli commands not handled in main(): {sorted(missing)}"


def test_core_commands_present():
    choices = _subparser_choices(cs.build_cli())
    for expected in ("chat", "code", "serve", "list", "scan", "doctor",
                     "connect", "pull", "rm", "ps", "version", "agents"):
        assert expected in choices, f"missing subcommand: {expected}"


# ── version consistency across code / packaging / docs ───────────────────────
def test_version_matches_pyproject(repo_root: Path):
    text = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    assert m and m.group(1) == cs.VERSION


def test_version_matches_readme_badge(repo_root: Path):
    text = (repo_root / "README.md").read_text(encoding="utf-8")
    assert f"version-{cs.VERSION}" in text, "README version badge is out of date"


def test_default_context_has_core_keys():
    for key in ("n_ctx", "temperature", "max_new_tokens"):
        assert key in cs.DEFAULT_CONTEXT


# ── server startup must not do a reverse-DNS lookup (slow on macOS) ─────────
def test_http_server_skips_reverse_dns(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("socket.getfqdn must not be called on bind")
    monkeypatch.setattr(cs.socket, "getfqdn", boom)
    srv = cs._QuietHTTPServer(("127.0.0.1", 0), cs._ServeHandler)
    try:
        assert srv.server_name == "127.0.0.1" and srv.server_port > 0
    finally:
        srv.server_close()
