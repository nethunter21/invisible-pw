"""Structured, teachable analysis log.

Every pipeline step records what it did, which technique it used, what it found,
how long it took and a short "teach" paragraph explaining *why* an analyst uses
that technique. The UI renders this as the Log drawer.
"""
from __future__ import annotations

import threading
import time
from typing import Any


class AnalysisLog:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._t0 = time.perf_counter()
        self.progress = 0.0
        self.stage = "Queued"

    def set_stage(self, stage: str, progress: float) -> None:
        self.stage = stage
        self.progress = max(self.progress, min(1.0, progress))

    def add(self, step: str, title: str, *, method: str = "", detail: str = "",
            data: Any = None, teach: str = "", level: str = "info",
            ms: float | None = None) -> dict[str, Any]:
        entry = {
            "id": len(self.entries) + 1,
            "t": round(time.perf_counter() - self._t0, 3),
            "step": step,
            "title": title,
            "method": method,
            "detail": detail,
            "data": data,
            "teach": teach,
            "level": level,
            "ms": None if ms is None else round(ms, 1),
        }
        with self._lock:
            self.entries.append(entry)
        return entry

    def timer(self, step: str, title: str, **kw: Any) -> "_Timer":
        return _Timer(self, step, title, kw)

    def snapshot(self, since: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.entries[since:])


class _Timer:
    """Context manager: `with log.timer(...) as t: t.detail = ...` records duration."""

    def __init__(self, log: AnalysisLog, step: str, title: str, kw: dict[str, Any]):
        self.log, self.step, self.title, self.kw = log, step, title, kw
        self.detail = kw.pop("detail", "")
        self.data = kw.pop("data", None)
        self.level = kw.pop("level", "info")

    def __enter__(self) -> "_Timer":
        self._t = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        ms = (time.perf_counter() - self._t) * 1000
        if exc is not None:
            self.log.add(self.step, self.title + " — failed", detail=f"{type(exc).__name__}: {exc}",
                         level="error", ms=ms, **self.kw)
            return True  # swallow: one failing technique must never kill the analysis
        self.log.add(self.step, self.title, detail=self.detail, data=self.data,
                     level=self.level, ms=ms, **self.kw)
        return False
