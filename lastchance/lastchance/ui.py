"""Terminal output: colors, banner, live log, summary."""

from __future__ import annotations

import os
import sys
import threading
import time

_lock = threading.Lock()
_t0 = time.time()

if os.name == "nt":
    os.system("")  # enable ANSI escape codes in the Windows console

COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if COLOR else text


RED, GRN, YEL, CYN, DIM, BLD = "1;31", "1;32", "1;33", "1;36", "2", "1"
LEVEL = {"info": DIM, "ok": GRN, "warn": YEL, "error": RED}

BANNER = r"""
  ██╗      █████╗ ███████╗████████╗     ██████╗██╗  ██╗ █████╗ ███╗   ██╗ ██████╗███████╗
  ██║     ██╔══██╗██╔════╝╚══██╔══╝    ██╔════╝██║  ██║██╔══██╗████╗  ██║██╔════╝██╔════╝
  ██║     ███████║███████╗   ██║       ██║     ███████║███████║██╔██╗ ██║██║     █████╗
  ██║     ██╔══██║╚════██║   ██║       ██║     ██╔══██║██╔══██║██║╚██╗██║██║     ██╔══╝
  ███████╗██║  ██║███████║   ██║       ╚██████╗██║  ██║██║  ██║██║ ╚████║╚██████╗███████╗
  ╚══════╝╚═╝  ╚═╝╚══════╝   ╚═╝        ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝╚══════╝"""


def banner(mode: str) -> None:
    print(c(RED, BANNER))
    tag = "DRILL MODE - nothing will be broadcast" if mode == "drill" else "EMERGENCY SWEEP - EVERYTHING MOVES NOW"
    print(c(BLD, f"  >>> {tag} <<<\n"))


def log(wallet: str, msg: str, level: str = "info") -> None:
    stamp = f"{time.time() - _t0:6.2f}s"
    with _lock:
        print(f"{c(DIM, stamp)} {c(CYN, f'[{wallet:>12}]')} {c(LEVEL.get(level, ''), msg)}", flush=True)


def say(msg: str, level: str = "info") -> None:
    with _lock:
        print(c(LEVEL.get(level, BLD), msg), flush=True)


def summary(reports) -> int:
    print()
    print(c(BLD, "=" * 100))
    print(c(BLD, f"  {'WALLET':<14}{'ASSET':<26}{'AMOUNT':>22}  {'STATUS':<9} TX / NOTE"))
    print(c(BLD, "=" * 100))
    failures = 0
    for r in reports:
        if not r.actions and not r.errors:
            print(f"  {r.wallet:<14}{c(DIM, 'nothing to move')}")
        for a in r.actions:
            col = {"sent": GRN, "failed": RED, "planned": CYN}.get(a.status, "")
            failures += a.status == "failed"
            print(f"  {r.wallet:<14}{a.asset[:25]:<26}{str(a.amount):>22}  {c(col, f'{a.status:<9}')} "
                  f"{a.txid or a.note}")
        for e in r.errors:
            failures += 1
            print(f"  {r.wallet:<14}{c(RED, 'ERROR')} {e[:150]}")
    print(c(BLD, "=" * 100))
    return failures
