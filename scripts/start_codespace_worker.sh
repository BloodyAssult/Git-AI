#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p /tmp/git-ai
log(){ echo "[$(date -Is)] $*" | tee -a /tmp/git-ai/worker.log; python scripts/worker_log.py info "$*" >/dev/null 2>&1 || true; }
errlog(){ echo "[$(date -Is)] ERROR: $*" | tee -a /tmp/git-ai/worker.log >&2; python scripts/worker_log.py error "$*" >/dev/null 2>&1 || true; }
log "start_codespace_worker.sh invoked; cwd=$(pwd); codespace=${CODESPACE_NAME:-$HOSTNAME}"

# Low-data auto-start: this script must work without opening the Codespaces UI.
# It accepts either a user PAT in GH_TOKEN, or the built-in Codespaces GITHUB_TOKEN.
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
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    export GH_TOKEN="$GITHUB_TOKEN"
  elif [ -n "${WORKER_GITHUB_TOKEN:-}" ]; then
    export GH_TOKEN="$WORKER_GITHUB_TOKEN"
  elif command -v gh >/dev/null 2>&1; then
    export GH_TOKEN="$(gh auth token 2>/dev/null || true)"
  fi
fi

log "repo guess: REPO=${REPO:-}; GITHUB_REPOSITORY=${GITHUB_REPOSITORY:-}; token present: GH_TOKEN=${GH_TOKEN:+yes} GITHUB_TOKEN=${GITHUB_TOKEN:+yes}"
log "git branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true) commit=$(git rev-parse --short HEAD 2>/dev/null || true)"
python scripts/worker_status.py booting "اسکریپت Worker شروع شد" || true

if [ -z "${GH_TOKEN:-}" ]; then
  errlog "GH_TOKEN/GITHUB_TOKEN is missing. Add a Codespaces secret named GH_TOKEN or use the built-in GITHUB_TOKEN."
  python scripts/worker_status.py error "GH_TOKEN/GITHUB_TOKEN در Codespace پیدا نشد" || true
  exit 2
fi

if [ -z "${REPO:-}" ]; then
  errlog "REPO is missing. Example: export REPO=username/repo"
  python scripts/worker_status.py error "REPO پیدا نشد" || true
  exit 2
fi

if [ -z "${CHAT_QUEUE_KEY:-}" ]; then
  errlog "CHAT_QUEUE_KEY is not set. It must match the Security Key in the web UI and GitHub Secret."
  python scripts/worker_status.py missing_key "CHAT_QUEUE_KEY داخل Codespaces Secret تنظیم نشده یا هنوز وارد container نشده است" || true
  if [ "${WORKER_NONINTERACTIVE:-}" = "1" ]; then
    errlog "Non-interactive auto-start: skipping worker. Add CHAT_QUEUE_KEY as a Codespaces secret, stop/start or rebuild the Codespace."
    exit 3
  fi
  read -r -s -p "CHAT_QUEUE_KEY: " CHAT_QUEUE_KEY
  echo
  export CHAT_QUEUE_KEY
fi

# Avoid duplicate workers when postStartCommand runs more than once.
exec 9>/tmp/git-ai-worker.lock
if ! flock -n 9; then
  log "Worker already running; not starting another copy."
  python scripts/worker_status.py already_running "یک Worker دیگر از قبل در حال اجراست؛ اگر پاسخ نمی‌دهد، Codespace را Stop/Start کن" || true
  exit 0
fi

if [ ! -f .worker_deps_ready ]; then
  log "installing dependencies/playwright if needed"
python scripts/worker_status.py installing "در حال نصب وابستگی‌ها و Chromium؛ بار اول ممکن است چند دقیقه طول بکشد" || true
  python -m pip install -q requests cryptography playwright || { errlog "pip install failed"; python scripts/worker_status.py error "pip install failed" || true; exit 11; }
  python -m playwright install --with-deps chromium || { errlog "playwright chromium install failed"; python scripts/worker_status.py error "playwright chromium install failed" || true; exit 12; }
  touch .worker_deps_ready
fi

log "dependencies ready; launching codespace_worker.py"
python scripts/worker_status.py starting "وابستگی‌ها آماده‌اند؛ در حال اجرای codespace_worker.py" || true
python codespace_worker.py || { code=$?; errlog "codespace_worker.py exited with code $code"; python scripts/worker_status.py error "codespace_worker.py exited with code $code" || true; exit $code; }
