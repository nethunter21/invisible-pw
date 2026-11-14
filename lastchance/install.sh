#!/usr/bin/env bash
# Creates a private virtualenv next to the tool and installs dependencies.
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
echo "installed. next: write your config, then: .venv/bin/python -m lastchance seal my-config.json"
