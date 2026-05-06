#!/usr/bin/env bash
set -euo pipefail
pkill -f "python .*codespace_worker.py" || true
pkill -f "codespace_worker.py" || true
echo "Codespace worker process stopped if it was running."
