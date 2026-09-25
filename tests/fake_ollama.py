"""A stand-in for the `ollama` binary, for tests: `fake_ollama.py serve`
serves the parts of the Ollama HTTP API that Spark X uses. Installed models
live in a JSON file next to $OLLAMA_MODELS (or the temp dir)."""
import json
import os
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATE = Path(os.environ.get("OLLAMA_MODELS") or tempfile.gettempdir()) / "fake-ollama-models.json"


def load():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return []


def save(models):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(models))


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self):
        if self.path == "/api/version":
            return self._json({"version": os.environ.get("FAKE_OLLAMA_VERSION", "0.99.0-fake"), "pid": os.getpid()})
        if self.path == "/api/tags":
            return self._json({"models": [{"name": m, "model": m, "size": int(os.environ.get("FAKE_OLLAMA_SIZE", "123456789")),
                                           "details": {"parameter_size": "4B", "quantization_level": "Q4_K_M",
                                                       "family": "fake"}} for m in load()]})
        if self.path == "/v1/models":
            return self._json({"object": "list", "data": [{"id": m, "object": "model"} for m in load()]})
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        body = self._body()
        if self.path == "/api/show":
            name = body.get("model") or body.get("name")
            caps = ["completion", "tools"] + (["vision"] if "vision" in (name or "") else [])
            return self._json({"capabilities": caps})
        if self.path == "/api/pull":
            name = body.get("model") or body.get("name")
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            if name.startswith("missing"):
                self.wfile.write(json.dumps({"error": "pull model manifest: file does not exist"}).encode() + b"\n")
                return
            self.wfile.write(json.dumps({"status": "pulling manifest"}).encode() + b"\n")
            total = 4000
            for done in (1000, 2000, 3000, 4000):
                self.wfile.write(json.dumps({"status": "pulling abc123", "total": total, "completed": done}).encode() + b"\n")
                self.wfile.flush()
                time.sleep(0.05)
            models = load()
            if name not in models:
                models.append(name)
                save(models)
            self.wfile.write(json.dumps({"status": "success"}).encode() + b"\n")
            return
        if self.path == "/v1/chat/completions":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for piece in ("hi ", "from ", "fake ", "ollama"):
                ev = {"choices": [{"delta": {"content": piece}, "index": 0}]}
                self.wfile.write(b"data: " + json.dumps(ev).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
            return
        self._json({"error": "not found"}, 404)

    def do_DELETE(self):
        body = self._body()
        name = body.get("model") or body.get("name")
        models = load()
        if name not in models:
            return self._json({"error": f"model '{name}' not found"}, 404)
        save([m for m in models if m != name])
        self._json({})


def main():
    if sys.argv[1:2] != ["serve"]:
        print("fake ollama: only 'serve' is supported")
        return 2
    host = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434").replace("http://", "")
    h, _, p = host.rpartition(":")
    ThreadingHTTPServer((h or "127.0.0.1", int(p)), H).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
