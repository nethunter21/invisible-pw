#!/usr/bin/env bash
# One-click launcher (Linux/macOS). Double-click or run: ./lastchance.sh
cd "$(dirname "$0")"
PY=python3; [ -x .venv/bin/python ] && PY=.venv/bin/python
"$PY" -m lastchance fire "$@"
read -r -p "press enter to close" _
