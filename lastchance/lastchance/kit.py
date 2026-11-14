"""Build a self-contained, run-anywhere emergency kit folder.

The kit contains the sealed `model9x`, a copy of the lastchance package, and
one-click launchers + installers for Windows / macOS / Linux. Copy the folder
(or its zip) to any machine; no per-device setup, because all the
destinations live inside `model9x`.
"""

from __future__ import annotations

import os
import shutil
import zipfile

from . import vault

RUN_PY = '''import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lastchance.cli import main
sys.exit(main())
'''

LAUNCH_SH = '''#!/usr/bin/env bash
# One-click LAST CHANCE launcher (Linux/macOS). Double-click or: ./lastchance.sh
cd "$(dirname "$0")"
PY=python3; command -v python3 >/dev/null || PY=python
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; fi
"$PY" run.py "$@"
read -r -p "press enter to close " _
'''

LAUNCH_BAT = '''@echo off
title LAST CHANCE
cd /d "%~dp0"
if exist ".venv\\Scripts\\python.exe" (set PY=.venv\\Scripts\\python.exe) else (set PY=python)
%PY% run.py %*
echo.
pause
'''

INSTALL_SH = '''#!/usr/bin/env bash
# Run ONCE per machine if `python run.py` complains about missing packages.
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
echo "ready. now double-click lastchance.sh to fire."
'''

INSTALL_BAT = '''@echo off
cd /d "%~dp0"
python -m venv .venv
.venv\\Scripts\\python.exe -m pip install -q --upgrade pip
.venv\\Scripts\\python.exe -m pip install -q -r requirements.txt
echo ready. now double-click LASTCHANCE.bat to fire.
pause
'''

REQUIREMENTS = '''cryptography>=42
requests>=2.31
embit>=0.8
eth-account>=0.13
solders>=0.21
tronpy>=0.5
xrpl-py>=3.0
'''

README = '''# LAST CHANCE emergency kit

This folder is self-contained. Copy it to ANY computer (or a USB stick) and
run it. All your safe destination addresses are baked into the encrypted
`model9x` file, so there is nothing to set up per device.

## To fire (move everything to safety)
- Windows: double-click **LASTCHANCE.bat**
- macOS / Linux: double-click **lastchance.sh** (or run `./lastchance.sh`)

It asks for your vault passphrase, then (if the kit was built without stored
keys) for your seed phrase / private key ONE time, then sweeps every
configured wallet to your safe addresses in parallel.

## First time on a machine
If it says a package is missing, run the installer once:
- Windows: **install.bat**      - macOS/Linux: **./install.sh**
(Needs Python 3.9+ installed. Or build a single .exe with PyInstaller - see the
main project README.)

## Other commands (run in a terminal)
    python run.py drill       rehearsal: real balances + fees, NOTHING is sent
    python run.py addresses   show every source + destination address
    python run.py show        print the config with secrets hidden

## Safety
- `model9x` is encrypted and tamper-proof: nobody can change your destination
  addresses without the passphrase.
- Each unlock prints a destination fingerprint. Write it down; if it ever
  changes, stop and do not fire.
- Prefer running from a clean computer. Always do a `drill` after copying.
'''


def _copy_package(dst_pkg: str) -> None:
    src_pkg = os.path.dirname(os.path.abspath(__file__))
    shutil.copytree(
        src_pkg, dst_pkg,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests"),
    )


def build_kit(config: dict, passphrase: str, out_dir: str, make_zip: bool = True) -> dict:
    """Write the kit into out_dir. Returns {dir, zip, fingerprint}."""
    os.makedirs(out_dir, exist_ok=True)
    _copy_package(os.path.join(out_dir, "lastchance"))
    vault.seal_config(config, passphrase, os.path.join(out_dir, "model9x"))

    files = {
        "run.py": RUN_PY, "lastchance.sh": LAUNCH_SH, "LASTCHANCE.bat": LAUNCH_BAT,
        "install.sh": INSTALL_SH, "install.bat": INSTALL_BAT,
        "requirements.txt": REQUIREMENTS, "README.txt": README,
    }
    for name, content in files.items():
        path = os.path.join(out_dir, name)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        if name.endswith(".sh"):
            os.chmod(path, 0o755)

    # a copy of the example so people can see the config format
    example = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "model9x.example.json")
    if os.path.isfile(example):
        shutil.copy(example, os.path.join(out_dir, "model9x.example.json"))

    zip_path = None
    if make_zip:
        zip_path = out_dir.rstrip("/\\") + ".zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, names in os.walk(out_dir):
                for n in names:
                    full = os.path.join(root, n)
                    zf.write(full, os.path.join(os.path.basename(out_dir), os.path.relpath(full, out_dir)))

    from .cli import dest_fingerprint
    return {"dir": out_dir, "zip": zip_path, "fingerprint": dest_fingerprint(config)}
