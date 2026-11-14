from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal

import requests


class SweepError(Exception):
    pass


@dataclass
class Action:
    asset: str
    amount: Decimal
    source: str
    dest: str
    txid: str | None = None
    status: str = "planned"  # planned | sent | skipped | failed
    note: str = ""


@dataclass
class Report:
    wallet: str
    chain: str
    actions: list[Action] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    started: float = field(default_factory=time.time)
    finished: float | None = None


class Sweeper:
    """One wallet entry from the config -> moves everything to `to`."""

    chain: str = "?"

    def __init__(self, entry: dict, settings: dict, log):
        self.entry = entry
        self.settings = settings
        self.name = entry.get("name") or entry["chain"]
        self.to = entry["to"]
        self.boost = float(entry.get("fee_boost", settings.get("fee_boost", 2.0)))
        self.timeout = float(settings.get("timeout", 20))
        self.report = Report(self.name, entry["chain"])
        self._log = log
        self.http = requests.Session()
        self.http.headers["User-Agent"] = "Mozilla/5.0"

    # -- helpers -------------------------------------------------------
    def log(self, msg: str, level: str = "info") -> None:
        self._log(self.name, msg, level)

    def add(self, action: Action) -> Action:
        self.report.actions.append(action)
        return action

    def rpc(self, url: str, method: str, params=None, retries: int = 3):
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params if params is not None else []}
        last = None
        for attempt in range(retries):
            try:
                r = self.http.post(url, json=payload, timeout=self.timeout)
                r.raise_for_status()
                body = r.json()
                if body.get("error"):
                    raise SweepError(f"{method}: {body['error']}")
                return body["result"]
            except SweepError:
                raise
            except Exception as exc:  # network hiccup -> retry fast
                last = exc
                time.sleep(0.3 * (attempt + 1))
        raise SweepError(f"{method} failed: {last}")

    def get(self, url: str, retries: int = 3, **kw):
        last = None
        for attempt in range(retries):
            try:
                r = self.http.get(url, timeout=self.timeout, **kw)
                r.raise_for_status()
                return r.json()
            except Exception as exc:
                last = exc
                time.sleep(0.3 * (attempt + 1))
        raise SweepError(f"GET {url} failed: {last}")

    # -- interface -----------------------------------------------------
    def addresses(self) -> list[str]:
        """Source addresses controlled by this entry (no network needed)."""
        raise NotImplementedError

    def validate_destination(self) -> None:
        raise NotImplementedError

    def run(self, dry_run: bool) -> Report:
        raise NotImplementedError
