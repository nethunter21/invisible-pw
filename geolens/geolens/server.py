"""Local HTTP backend (127.0.0.1 only) that serves the UI and the analysis API."""
from __future__ import annotations

import json
import mimetypes
import os
import threading
import traceback
import uuid
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from PIL import Image
import io

from . import reverse as rev
from . import sun as sun_mod
from .gazetteer import resource_path
from .log import AnalysisLog
from .pipeline import DEFAULT_SETTINGS, Analyzer
from .vision import MODELS, VisionEngine

UI_DIR = resource_path("ui")


def data_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    d = os.path.join(base, "GeoLens")
    os.makedirs(d, exist_ok=True)
    return d


class State:
    def __init__(self, use_vision: bool = True):
        self.settings = dict(DEFAULT_SETTINGS)
        p = os.path.join(data_dir(), "settings.json")
        try:
            self.settings.update(json.load(open(p)))
        except Exception:
            pass
        if os.environ.get("GEOLENS_MODEL"):  # power users / tests: HF repo key or local CLIP folder
            self.settings["model"] = os.environ["GEOLENS_MODEL"]
        self.use_vision = use_vision
        self.engine = VisionEngine(self.settings["model"], os.path.join(data_dir(), "models")) if use_vision else None
        self.jobs: dict[str, dict] = {}
        self.run_lock = threading.Lock()

    def save(self):
        json.dump(self.settings, open(os.path.join(data_dir(), "settings.json"), "w"), indent=2)

    def preload(self):
        if self.engine is not None:
            threading.Thread(target=self.engine.load, daemon=True).start()


STATE: State | None = None


def _run_job(job_id: str):
    job = STATE.jobs[job_id]
    log: AnalysisLog = job["log"]
    try:
        with STATE.run_lock:
            an = Analyzer(STATE.engine, STATE.settings)
            job["result"] = an.run(job["bytes"], job["name"], log, focus=job.get("focus"), focus_space=job.get("focus_space", "original"))
            job["search_img"] = an.search_image
    except Exception as e:
        job["error"] = f"{type(e).__name__}: {e}"
        log.add("error", "Analysis failed", detail=traceback.format_exc(), level="error")
    finally:
        job["done"] = True


class Handler(BaseHTTPRequestHandler):
    server_version = "GeoLens/1.0"

    def log_message(self, fmt, *args):  # quiet
        pass

    # ---------------------------------------------------------------- helpers
    def _json(self, obj, code=200):
        body = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _jbody(self) -> dict:
        try:
            return json.loads(self._body() or b"{}")
        except Exception:
            return {}

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        q = parse_qs(u.query)
        if p == "/api/status":
            e = STATE.engine
            return self._json({"settings": STATE.settings, "models": {k: v["label"] for k, v in MODELS.items()},
                               "model": None if e is None else {"key": e.model_key, "status": e.status, "error": e.error,
                                                                "download": e.download, "device": e.device}})
        if p.startswith("/api/job/"):
            jid = p.rsplit("/", 1)[-1]
            job = STATE.jobs.get(jid)
            if not job:
                return self._json({"error": "unknown job"}, 404)
            since = int(q.get("since", ["0"])[0])
            log: AnalysisLog = job["log"]
            r = {"stage": log.stage, "progress": log.progress, "entries": log.snapshot(since),
                 "done": job["done"], "error": job.get("error")}
            if job["done"]:
                r["result"] = job.get("result")
                r["log"] = log.snapshot()
            return self._json(r)
        # static
        rel = "index.html" if p in ("/", "") else unquote(p.lstrip("/"))
        full = os.path.normpath(os.path.join(UI_DIR, rel))
        if not full.startswith(os.path.normpath(UI_DIR)) or not os.path.isfile(full):
            self.send_error(404)
            return
        data = open(full, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(full)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        u = urlparse(self.path)
        p = u.path
        q = parse_qs(u.query)
        try:
            if p == "/api/analyze":
                data = self._body()
                Image.open(io.BytesIO(data)).verify()
                jid = uuid.uuid4().hex[:12]
                try:
                    focus = json.loads(q.get("focus", ["[]"])[0])
                except Exception:
                    focus = []
                STATE.jobs[jid] = {"bytes": data, "name": q.get("name", ["image"])[0], "log": AnalysisLog(),
                                   "done": False, "created": datetime.now().isoformat(), "focus": focus,
                                   "focus_space": q.get("space", ["original"])[0]}
                for old in list(STATE.jobs)[:-8]:  # keep memory bounded
                    STATE.jobs.pop(old, None)
                threading.Thread(target=_run_job, args=(jid,), daemon=True).start()
                return self._json({"job": jid})
            if p == "/api/settings":
                body = self._jbody()
                old_model = STATE.settings["model"]
                for k in DEFAULT_SETTINGS:
                    if k in body:
                        STATE.settings[k] = body[k]
                STATE.save()
                if STATE.use_vision and STATE.settings["model"] != old_model:
                    STATE.engine = VisionEngine(STATE.settings["model"], os.path.join(data_dir(), "models"))
                    STATE.preload()
                return self._json({"ok": True, "settings": STATE.settings})
            if p == "/api/model/load":
                STATE.preload()
                return self._json({"ok": True})
            if p == "/api/sun/position":
                b = self._jbody()
                dt = datetime.fromisoformat(b["utc"])
                return self._json({"position": sun_mod.solar_position(b["lat"], b["lon"], dt),
                                   "times": sun_mod.sun_times(b["lat"], b["lon"], dt)})
            if p == "/api/sun/locus":
                b = self._jbody()
                dt = datetime.fromisoformat(b["utc"])
                return self._json(sun_mod.shadow_locus(dt, float(b["elevation"]), float(b.get("tol", 1.5)),
                                                       None if b.get("azimuth") in (None, "") else float(b["azimuth"]),
                                                       float(b.get("az_tol", 10))))
            if p == "/api/sun/chrono":
                b = self._jbody()
                dt = datetime.fromisoformat(b["date"])
                return self._json({"times": sun_mod.chronolocate(b["lat"], b["lon"], dt, float(b["elevation"]))})
            if p.startswith("/api/reverse/"):
                engine = p.rsplit("/", 1)[-1]
                b = self._jbody()
                job = STATE.jobs.get(b.get("job", ""))
                if engine not in rev.ENGINES or not job:
                    return self._json({"error": "unknown engine or job"}, 400)
                img = job.get("search_img") or Image.open(io.BytesIO(job["bytes"])).convert("RGB")
                try:
                    res = rev.ENGINES[engine](img)
                except Exception as e:
                    res = {"engine": engine, "error": f"{type(e).__name__}: {e}", "url": rev.MANUAL.get(engine)}
                if b.get("open") and res.get("url"):
                    webbrowser.open(res["url"])
                job["log"].add("reverse", f"Manual reverse search: {engine}", method="Web upload, no API key",
                               detail=res.get("error") or res.get("url", ""), level="warn" if res.get("error") else "info")
                return self._json(res)
            if p == "/api/open":
                url = self._jbody().get("url", "")
                if url.startswith(("https://", "http://")):
                    webbrowser.open(url)
                return self._json({"ok": True})
            if p == "/api/geocode":
                return self._json({"results": rev.nominatim(self._jbody().get("q", ""))})
            self.send_error(404)
        except Exception as e:
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)


def serve(port: int = 0, use_vision: bool = True) -> ThreadingHTTPServer:
    global STATE
    STATE = State(use_vision)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd
