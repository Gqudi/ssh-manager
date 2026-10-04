#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -d .venv ]]; then python -m venv .venv; fi
.venv/bin/python -m pip install -e .
.venv/bin/python -m ssh_manager
