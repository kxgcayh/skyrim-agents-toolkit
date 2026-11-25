"""A stand-in for DevBench's REST surface, so devbench-cli.sh can be tested
without a running copy of Skyrim.

Run as:  python mock_devbench.py <port> <mode>

Each mode reproduces one state the real server can be in. The liveness shapes
come from DevBench's own /api/health contract: `frame` advancing means the game
is running, a frozen frame with an idle task queue is a pause rather than a
hang, and a frozen frame with work piling up while `lastTaskFrame` stalls is a
genuinely starved main thread.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(sys.argv[1])
MODE = sys.argv[2]

_state = {"n": 0}
_lock = threading.Lock()


def _tick() -> int:
    with _lock:
        _state["n"] += 1
        return _state["n"]


def health_body() -> dict:
    n = _tick()
    common = {"pid": 4242, "port": PORT, "exe": "SkyrimVR.exe", "vr": True}
    if MODE in ("running", "bench"):
        return {"ok": True, "lastLifecycle": "postLoadGame", "frame": 1000 + n * 90,
                "lastTaskFrame": 990 + n * 90, "pendingTasks": 0, **common}
    if MODE == "paused":
        # Frame frozen, but the task queue is draining -- a menu, not a hang.
        return {"ok": True, "lastLifecycle": "postLoadGame", "frame": 5000,
                "lastTaskFrame": 4998, "pendingTasks": 0, **common}
    if MODE == "hung":
        # Frame frozen AND work queued that never completes.
        return {"ok": True, "lastLifecycle": "postLoadGame", "frame": 7777,
                "lastTaskFrame": 7770, "pendingTasks": 3, **common}
    if MODE == "sim":
        loading = _sim_loading()
        if _sim.get("paused_from", 0) <= _time.time() < _sim.get("paused_until", 0):   # frame frozen, queue idle: a pause, not a hang
            return {"ok": True, "lastLifecycle": "postLoadGame", "frame": 4321, "lastTaskFrame": 4320,
                    "pendingTasks": 0, "menus": ["HUD Menu"], **common}
        return {"ok": True, "lastLifecycle": "postLoadGame", "frame": 1000 + n * 7, "lastTaskFrame": 1000 + n * 7,
                "pendingTasks": 0, "menus": ["HUD Menu"] + (["Loading Menu"] if loading else []), **common}
    if MODE == "notingame":
        # Server up, no save loaded: the frame counter is unresolved.
        return {"ok": True, "lastLifecycle": None, "frame": -1,
                "lastTaskFrame": -1, "pendingTasks": 0, **common}
    raise AssertionError(f"unknown mode {MODE}")


# ---- mode "sim": a small stateful game for the coc / goto / msgbox / waitcall / form commands ----------------
# Load order: BSHeartland.esm is full plugin 0x16, "Some Patch.esp" light plugin 0x324. Reference 0x160012F7 is in
# memory (3D unloaded until the player is moved), 0x16000999 is not in memory. `coc GoodCell` loads for 1.5 s;
# `coc NoSuchCell` is rejected. HasSpell answers false twice, then true. A message box "Pray?" [Pray, Leave] is open
# until answered; its answer is recorded in _sim["answer"].
import time as _time

_sim = {"cell": "StartCell", "load_until": 0.0, "pending": None, "moved": False, "hasspell": 0,
        "box": True, "answer": None, "moveto": None}


# Doors for `cellcycle`: activating 0x0000D00A loads CellB, 0x0000D00B loads CellA, 0x0000D0FF does nothing.
# MOCK_CRASH_AFTER=N makes the "game" stop answering (process exits) on the N-th cell arrival.
_DOORS = {"0x0000D00A": "CellB", "0x0000D00B": "CellA"}
_NEIGHBOUR = {"ExteriorCell": "NeighbourCell"}  # `coc ExteriorCell` lands one cell over
_sim["arrivals"] = 0
_sim["god"] = False   # `tgm` toggles it; inspect kind "player" reports it as godMode


def _sim_loading() -> bool:
    if _sim["pending"] and _time.time() >= _sim["load_until"]:
        _sim["cell"], _sim["pending"] = _sim["pending"], None
        _sim["arrivals"] += 1
        if int(os.environ.get("MOCK_PAUSE_AFTER") or 0) == _sim["arrivals"]:   # a pause/menu after this arrival
            # starts MOCK_PAUSE_DELAY s after the arrival, once coc has seen the frame advance
            _sim["paused_from"] = _time.time() + float(os.environ.get("MOCK_PAUSE_DELAY") or 0)
            _sim["paused_until"] = _sim["paused_from"] + float(os.environ.get("MOCK_PAUSE_SECONDS") or 4)
        crash = int(os.environ.get("MOCK_CRASH_AFTER") or 0)
        if crash and _sim["arrivals"] >= crash:
            threading.Timer(0.2, lambda: os._exit(0)).start()
    return _sim["pending"] is not None


def _sim_post(path: str, body: dict):
    if path == "/api/tool/inspect":
        kind = body.get("kind")
        if kind == "mods":
            return 200, {"count": 2, "lightCount": 1,
                         "plugins": [{"index": 0, "name": "Skyrim.esm"}, {"index": 22, "name": "BSHeartland.esm"}],
                         "lightPlugins": [{"index": 0x324, "name": "Some Patch.esp"}]}
        if kind == "scene":
            if _sim_loading():
                return 504, {"error": "main thread busy", "code": 504}
            return 200, {"cell": {"editorId": _sim["cell"]}, "playerLoaded": True}
        if kind == "player":
            return 200, {"godMode": _sim["god"]}
        return 200, {"playerLoaded": True, "frame": 1000}
    if path == "/api/tool/console" and body.get("action") == "exec":
        cmd = str(body.get("command"))
        if cmd.strip().lower() == "tgm":
            _sim["god"] = not _sim["god"]
            return 200, {"completed": True, "lines": ["God Mode -> " + ("On" if _sim["god"] else "Off")]}
        if cmd.lower().startswith("coc "):
            cell = cmd[4:].strip()
            if cell == "NoSuchCell":
                return 200, {"completed": True, "lines": ["Cell 'NoSuchCell' not found"]}
            if cell == "SilentBadCell":  # the real console prints nothing for an unknown cell
                return 200, {"completed": True, "lines": []}
            # an exterior coc can land in the neighbouring cell, as the real one does
            _sim["pending"], _sim["load_until"] = _NEIGHBOUR.get(cell, cell), _time.time() + 1.5
        return 200, {"completed": True, "lines": []}
    if path == "/api/tool/menu":
        if body.get("action") == "describe":
            if _sim["box"]:
                return 200, {"messageBoxOpen": True, "bodyText": "Pray?", "buttons": ["Pray", "Leave"]}
            return 200, {"messageBoxOpen": False}
        if body.get("action") == "accept":
            _sim["answer"], _sim["box"] = body.get("index"), False
            return 200, {"accepted": True}
    if path == "/api/tool/papyrus" and body.get("action") == "describe":
        return 200, {"memberFunctions": [], "globalFunctions": []}
    if path == "/api/tool/papyrus" and body.get("action") == "call":
        fn, self_ = body.get("function"), (body.get("self") or {}).get("form")
        if self_ == "0x16000999":
            return 400, {"error": "form '0x16000999' not found", "code": 400}
        if fn == "Is3DLoaded":
            return 200, {"returned": bool(_sim["moved"]) if self_ == "0x160012F7" else True}
        if fn == "GetAngleZ":
            return 200, {"returned": 90.0}
        if fn == "MoveTo":
            _sim["moved"], _sim["moveto"] = True, body.get("args")
            return 200, {"returned": None}
        if fn == "HasSpell":
            _sim["hasspell"] += 1
            return 200, {"returned": _sim["hasspell"] > 2}
        if fn == "GetDistance":
            return 200, {"returned": 150.0}
        if fn == "Echo":
            return 200, {"returned": body}
        if fn == "Activate" and self_ in _DOORS:
            _sim["pending"], _sim["load_until"] = _DOORS[self_], _time.time() + 1.0
            return 200, {"returned": True}
        return 200, {"returned": None}
    if path == "/api/tool/sim":  # test hook: the sim's own state
        return 200, {k: v for k, v in _sim.items() if k != "load_until"}
    return 200, {"ok": True}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep the test output clean
        pass

    def _send(self, code: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/api/health":
            if MODE == "legacy":  # pre-1.11.0: the endpoint does not exist
                return self._send(404, {"error": "not found"})
            return self._send(200, health_body())
        if self.path == "/api/tools":
            return self._send(200, {"tools": ["ping", "inspect"]})
        self._send(404, {"error": "not found"})

    def _bench(self, body: dict):
        """Mode "bench", for tests/test_bench_vr.py: a console that answers the commands bench-vr.py sends and
        logs each one (one per line) to $MOCK_LOG. $MOCK_FAIL_ON=<text> makes the console exec of a command that
        contains it answer HTTP 500, once, so a run can be failed partway. $MOCK_CELL is the current cell."""
        if self.path == "/api/tool/inspect":
            return self._send(200, {"cell": {"editorId": os.environ.get("MOCK_CELL", "SomeInterior")},
                                    "weather": {"editorId": "SkyrimCloudySN_A"}})
        if self.path != "/api/tool/console":
            return self._send(200, {"ok": True})
        if body.get("action") == "exec":
            cmd = str(body.get("command"))
            with open(os.environ["MOCK_LOG"], "a", encoding="utf-8") as fh:
                fh.write(cmd + "\n")
            fail = os.environ.get("MOCK_FAIL_ON")
            if fail and fail in cmd and not _state.get("failed"):
                _state["failed"] = True
                return self._send(500, {"error": "injected failure", "code": 500})
            _state["last"] = cmd
            return self._send(200, {"ok": True})
        last = _state.get("last", "")
        answers = {"show timescale": ["TimeScale = 20.00"], "show gamehour": ["GameHour = 9.50"],
                   "tgm": ["God Mode -> On"]}
        lines = answers.get(last, ["Cell 'NoSuchCell' not found"] if "NoSuchCell" in last else [])
        return self._send(200, {"lines": lines})

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            if MODE == "strict":  # a real server rejects invalid JSON; the lenient modes hide a malformed payload
                return self._send(400, {"error": "invalid JSON", "code": 400})
            body = {}
        if MODE == "strict":
            if body.get("function") == "Reject":
                return self._send(400, {"error": "arg 1: expected Float got Int", "code": 400})
            return self._send(200, {"path": self.path, "args": body})
        if MODE == "busy504":
            return self._send(504, {"error": "main thread did not run task in time",
                                    "code": 504})
        if MODE == "badarg400":
            return self._send(400, {"error": "kind must be a string", "code": 400})
        if MODE in ("capture", "incomplete"):
            if self.path == "/api/tool/console" and body.get("action") == "exec":
                return self._send(200, {"completed": MODE == "capture", "lines": [body["command"]]})
            return self._send(500, {"error": "must not read shared capture"})
        if MODE == "echo":
            return self._send(200, {"path": self.path, "args": body})
        if MODE == "bench":
            return self._bench(body)
        if MODE == "sim":
            return self._send(*_sim_post(self.path, body))
        if self.path == "/api/tool/ping":
            return self._send(200, {"ok": True})
        if self.path == "/api/tool/inspect":
            # Legacy path: the main-thread frame counter, advancing.
            return self._send(200, {"plugin": "devbench", "vr": True,
                                    "playerLoaded": True, "frame": 2000 + _tick() * 90})
        self._send(200, {"ok": True})


if __name__ == "__main__":
    # Bind first, then announce the port we actually got. Passing 0 lets the OS
    # choose, which removes the race in "find a free port, close it, hope it is
    # still free when the server binds it".
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"PORT={server.server_address[1]}", flush=True)
    server.serve_forever()
