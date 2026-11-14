"""Runs every wallet sweep in parallel and writes a receipt."""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

from . import ui
from .chains import make_sweeper
from .chains.base import Report


def build(config: dict, log=None):
    log = log or ui.log
    settings = config.get("settings", {})
    sweepers, broken = [], []
    for i, entry in enumerate(config.get("wallets", [])):
        if entry.get("enabled", True) is False:
            continue
        name = entry.get("name") or f"{entry.get('chain', '?')}#{i}"
        entry.setdefault("name", name)
        try:
            sweepers.append(make_sweeper(entry, settings, log))
        except Exception as exc:
            r = Report(name, entry.get("chain", "?"))
            r.errors.append(f"config error: {exc}")
            broken.append(r)
            log(name, f"config error: {exc}", "error")
    return sweepers, broken


def run_all(config: dict, dry_run: bool, log=None):
    """Run every sweeper in parallel, return the reports (no printing)."""
    sweepers, broken = build(config, log)

    def go(s):
        try:
            return s.run(dry_run)
        except Exception as exc:  # never let one chain kill the others
            s.report.errors.append(str(exc))
            s.log(f"crashed: {exc}", "error")
            return s.report

    with ThreadPoolExecutor(max(1, len(sweepers))) as pool:
        reports = list(pool.map(go, sweepers)) + broken
    for r in reports:
        r.finished = time.time()
    return reports


def fire(config: dict, dry_run: bool, receipt_dir: str | None = None) -> int:
    t0 = time.time()
    reports = run_all(config, dry_run)
    failures = ui.summary(reports)
    ui.say(f"  done in {time.time() - t0:.1f}s  -  {'DRILL, nothing broadcast' if dry_run else 'broadcast complete'}",
           "ok" if not failures else "warn")
    if receipt_dir and not dry_run:
        path = write_receipt(reports, receipt_dir)
        ui.say(f"  receipt (txids only, no secrets): {path}")
    return 1 if failures else 0


def write_receipt(reports, directory: str) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(directory, f"receipt-{stamp}.json")
    data = [{"wallet": r.wallet, "chain": r.chain, "errors": r.errors,
             "actions": [{"asset": a.asset, "amount": str(a.amount), "from": a.source, "to": a.dest,
                          "txid": a.txid, "status": a.status, "note": a.note} for a in r.actions]}
            for r in reports]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    return path


def list_addresses(config: dict) -> None:
    sweepers, _ = build(config)
    for s in sweepers:
        try:
            s.validate_destination()
            dest_ok = ui.c(ui.GRN, "OK")
        except Exception as exc:
            dest_ok = ui.c(ui.RED, f"INVALID: {exc}")
        print(ui.c(ui.BLD, f"\n[{s.name}] {s.entry['chain']}"))
        print(f"   to   -> {s.to}  {dest_ok}")
        try:
            for a in s.addresses():
                print(f"   from <- {a}")
        except Exception as exc:
            print(ui.c(ui.RED, f"   key error: {exc}"))
