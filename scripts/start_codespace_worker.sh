#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -z "${REPO:-}" ]; then
  if [ -n "${GITHUB_REPOSITORY:-}" ]; then
    export REPO="$GITHUB_REPOSITORY"
  else
    origin="$(git config --get remote.origin.url || true)"
    if [[ "$origin" =~ github.com[:/]([^/]+)/([^/.]+)(\.git)?$ ]]; then
      export REPO="${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"
    fi
  fi
fi

if [ -z "${GH_TOKEN:-}" ]; then
  if command -v gh >/dev/null 2>&1; then
    export GH_TOKEN="$(gh auth token 2>/dev/null || true)"
  fi
fi

if [ -z "${GH_TOKEN:-}" ]; then
  echo "GH_TOKEN is missing. Export a PAT with Contents read/write first:"
  echo "  export GH_TOKEN=ghp_..."
  exit 2
fi

if [ -z "${REPO:-}" ]; then
  echo "REPO is missing. Example: export REPO=username/repo"
  exit 2
fi

if [ -z "${CHAT_QUEUE_KEY:-}" ]; then
  echo "CHAT_QUEUE_KEY is not set. It must match the Security Key in the web UI and GitHub Secret."
  if [ "${WORKER_NONINTERACTIVE:-}" = "1" ]; then
    echo "Non-interactive auto-start: skipping worker. Add CHAT_QUEUE_KEY as a Codespaces secret, then start again from the web UI."
    exit 3
  fi
  read -r -s -p "CHAT_QUEUE_KEY: " CHAT_QUEUE_KEY
  echo
  export CHAT_QUEUE_KEY
fi

if [ ! -f .worker_deps_ready ]; then
  python -m pip install -q requests cryptography playwright
  python -m playwright install --with-deps chromium
  touch .worker_deps_ready
fi

python codespace_worker.py
