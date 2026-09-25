"""Spark X bridge — lets the Spark X app build and edit scenes in this Blender.

Install: Spark X → Connectors → Blender → "Install bridge", or in Blender
Edit → Preferences → Add-ons → Install from Disk… and pick this file.

While enabled it listens on 127.0.0.1 only (default port 9876) and runs the
Python that Spark X sends, on Blender's main thread. Every request must carry
a random token that is written to ~/.sparkx/blender-bridge.json (readable by
your user only), so other programs on the network can't use it.
"""

bl_info = {
    "name": "Spark X Bridge",
    "author": "Spark X",
    "version": (1, 0, 0),
    "blender": (3, 2, 0),
    "location": "Runs in the background",
    "description": "Lets the Spark X app build and edit scenes in this Blender session",
    "category": "Development",
}

import contextlib
import io
import json
import os
import queue
import secrets
import socket
import tempfile
import threading
import time
import traceback

import bpy

PORT = int(os.environ.get("SPARKX_BRIDGE_PORT", "9876"))
_state = {"running": False, "thread": None, "token": None, "sock": None}
_jobs = queue.Queue()
_ns = {}


def _info_path():
    return os.path.join(os.path.expanduser("~"), ".sparkx", "blender-bridge.json")


def _write_info():
    path = _info_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"port": PORT, "token": _state["token"], "pid": os.getpid(),
                   "blender": bpy.app.version_string}, f)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _viewport_shot():
    """Screenshot of the 3D viewport (or the whole window) as a PNG path."""
    path = os.path.join(tempfile.gettempdir(), "sparkx_view_%d.png" % int(time.time() * 1000))
    wm = bpy.context.window_manager
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                try:
                    with bpy.context.temp_override(window=win, area=area):
                        bpy.ops.screen.screenshot_area(filepath=path)
                    return path
                except Exception:
                    pass
    for win in wm.windows:
        try:
            with bpy.context.temp_override(window=win):
                bpy.ops.screen.screenshot(filepath=path)
            return path
        except Exception:
            pass
    return None


def _run(req):
    """Execute one request on the main thread."""
    import bmesh
    import mathutils
    ns = _ns
    ns.update({"bpy": bpy, "bmesh": bmesh, "mathutils": mathutils,
               "Vector": mathutils.Vector, "C": bpy.context, "D": bpy.data})
    ns.pop("result", None)
    out = io.StringIO()
    res = {"ok": True}
    try:
        with contextlib.redirect_stdout(out):
            exec(compile(req.get("code") or "", "<spark-x>", "exec"), ns)
        if "result" in ns:
            res["result"] = repr(ns["result"])[:4000]
    except Exception:
        res["ok"] = False
        res["error"] = traceback.format_exc()[-6000:]
    res["output"] = out.getvalue()[-20000:]
    if req.get("screenshot"):
        try:
            bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
        except Exception:
            pass
        res["image"] = _viewport_shot()
    return res


def _pump():
    """bpy.app.timers callback: runs queued requests on Blender's main thread."""
    while True:
        try:
            req, done, box = _jobs.get_nowait()
        except queue.Empty:
            break
        try:
            box.update(_run(req))
        except Exception:
            box.update({"ok": False, "error": traceback.format_exc()[-4000:]})
        done.set()
    return 0.05 if _state["running"] else None


def _handle(conn):
    with conn:
        conn.settimeout(10)
        buf = b""
        try:
            while not buf.endswith(b"\n") and len(buf) < 8 * 1024 * 1024:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
            req = json.loads(buf.decode("utf-8") or "{}")
        except Exception as e:
            conn.sendall((json.dumps({"ok": False, "error": "bad request: %s" % e}) + "\n").encode())
            return
        if not secrets.compare_digest(str(req.get("token", "")), _state["token"] or "x"):
            conn.sendall((json.dumps({"ok": False, "error": "bad token"}) + "\n").encode())
            return
        done, box = threading.Event(), {}
        _jobs.put((req, done, box))
        if not done.wait(float(req.get("timeout", 180))):
            box = {"ok": False, "error": "Blender is busy (timed out)"}
        conn.settimeout(30)
        conn.sendall((json.dumps(box) + "\n").encode())


def _serve(srv):
    while _state["running"]:
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        threading.Thread(target=_handle, args=(conn,), daemon=True).start()
    srv.close()


def start():
    """Bind (raising OSError if the port is taken), publish the token, serve."""
    if _state["running"]:
        return
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", PORT))
    srv.listen(4)
    srv.settimeout(0.5)
    _state.update(sock=srv, token=secrets.token_hex(16), running=True)
    _write_info()
    t = threading.Thread(target=_serve, args=(srv,), name="spark-x-bridge", daemon=True)
    _state["thread"] = t
    t.start()
    if not bpy.app.timers.is_registered(_pump):
        bpy.app.timers.register(_pump, first_interval=0.2, persistent=True)


def stop():
    _state["running"] = False
    try:
        if bpy.app.timers.is_registered(_pump):
            bpy.app.timers.unregister(_pump)
    except Exception:
        pass
    try:
        with open(_info_path(), encoding="utf-8") as f:
            if json.load(f).get("pid") == os.getpid():
                os.remove(_info_path())
    except Exception:
        pass


def register():
    if bpy.app.background:          # nothing to bridge in a headless Blender
        return
    try:
        start()
    except OSError as e:            # port taken (another Blender has it)
        print("Spark X bridge: not started:", e)


def unregister():
    stop()
