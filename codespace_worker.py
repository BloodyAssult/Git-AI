#!/usr/bin/env python3
"""
Codespace Worker Relay for Git-AI remote browser.

Run this inside a GitHub Codespace when you cannot access Codespaces forwarded ports
from your local network, but you can access your GitHub Pages site and GitHub API.

The GitHub Pages UI writes browser requests to browser_queue/prompt_<id>.json.
This worker polls that queue, runs Chromium/Playwright inside the Codespace, and
writes browser_queue/response_<id>.json for the UI to read.
"""
import json
import os
import re
import subprocess
import sys
import time
import traceback
from typing import Any, Dict, List, Optional

import requests

BASE = "https://api.github.com"
QUEUE_DIR = os.environ.get("WORKER_QUEUE_DIR", "browser_queue").strip("/") or "browser_queue"
POLL_SECONDS = float(os.environ.get("WORKER_POLL_SECONDS", "1.2"))
HEARTBEAT_SECONDS = float(os.environ.get("WORKER_HEARTBEAT_SECONDS", "8"))
WORKER_PROTOCOL_VERSION = "2026-05-06-lowdata-v2"
WORKER_STARTED_AT = time.time()
PROCESSED_COUNT = 0


def _run(cmd: List[str]) -> str:
    try:
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return ""


def _guess_repo() -> str:
    if os.environ.get("REPO"):
        return os.environ["REPO"].strip()
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"].strip()
    url = _run(["git", "config", "--get", "remote.origin.url"])
    if url:
        # Supports git@github.com:owner/repo.git and https://github.com/owner/repo.git
        m = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+)(?:\.git)?", url)
        if m:
            return f"{m.group('owner')}/{m.group('repo')}"
    return ""


def _guess_token() -> str:
    for key in ("GH_TOKEN", "WORKER_GITHUB_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(key):
            return os.environ[key].strip()
    token = _run(["gh", "auth", "token"])
    return token.strip()


def _prepare_env() -> None:
    repo = _guess_repo()
    token = _guess_token()
    if not repo:
        print("ERROR: REPO is missing. Example: export REPO=username/repo", file=sys.stderr)
        sys.exit(2)
    if not token:
        print("ERROR: GH_TOKEN is missing. Create a fine-grained PAT with Contents read/write and export GH_TOKEN=...", file=sys.stderr)
        sys.exit(2)
    os.environ["REPO"] = repo
    os.environ["GH_TOKEN"] = token


_prepare_env()

# Import after env is ready. proxy.py contains the Playwright browser implementation,
# provider clients, encryption helpers, and GitHub content helpers.
import proxy  # noqa: E402

REPO = os.environ["REPO"]
GH_HEADERS = proxy.GH_HEADERS


def list_worker_files() -> List[Dict[str, Any]]:
    r = requests.get(
        f"{BASE}/repos/{REPO}/contents/{QUEUE_DIR}?_={time.time()}",
        headers=GH_HEADERS,
        timeout=25,
    )
    if r.status_code == 404:
        return []
    r.raise_for_status()
    items = r.json()
    if not isinstance(items, list):
        return []
    return [x for x in items if x.get("type") == "file"]


def id_from_prompt_path(path: str) -> str:
    m = re.search(r"prompt_([A-Za-z0-9_-]+)\.json$", path)
    return m.group(1) if m else "unknown"


def write_response(req_id: str, result: Any) -> None:
    """Write the response, with progressively smaller fallbacks.

    A big browser payload can fail to commit via Contents API. Previously that made
    the web UI wait forever. Now every failed write degrades to a smaller payload
    and finally to a tiny explicit error response.
    """
    resp_path = f"{QUEUE_DIR}/response_{req_id}.json"

    def attempt(obj: Any) -> bool:
        old_sha = proxy.get_file_sha(resp_path)
        return proxy.put_file(resp_path, proxy.encrypt_envelope(obj), old_sha)

    if attempt(result):
        return

    if isinstance(result, dict) and isinstance(result.get("browser"), dict):
        lean = dict(result)
        b = dict(result["browser"])
        b["frames"] = []
        b["note"] = (b.get("note") or "") + "\nفریم‌های ویدیو برای کاهش حجم حذف شدند."
        lean["browser"] = b
        if attempt(lean):
            write_worker_status({"state": "idle", "message": "response written without frames", "last_request_id": req_id})
            return

        tiny = dict(lean)
        tb = dict(b)
        tb["screenshot"] = ""
        tb["text_preview"] = (tb.get("text_preview") or "")[:1200]
        tb["note"] = (tb.get("note") or "") + "\nاسکرین‌شات هم برای کاهش حجم حذف شد؛ دوباره Refresh Frame را بزن."
        tiny["browser"] = tb
        if attempt(tiny):
            write_worker_status({"state": "idle", "message": "response written as tiny payload", "last_request_id": req_id})
            return

    attempt({"error": {"code": 500, "message": "Worker پاسخ را ساخت ولی نتوانست آن را در GitHub ذخیره کند. حجم خروجی یا دسترسی repo را چک کن."}})
    write_worker_status({"ok": False, "state": "error", "request_id": req_id, "message": "failed to write response file"})


def write_worker_status(extra: Optional[Dict[str, Any]] = None) -> None:
    """Write a tiny clear-text heartbeat for the GitHub Pages UI."""
    status_path = f"{QUEUE_DIR}/worker_status.json"
    try:
        old_sha = proxy.get_file_sha(status_path)
        payload: Dict[str, Any] = {
            "ok": True,
            "state": "idle",
            "ts": time.time(),
            "repo": REPO,
            "queue": QUEUE_DIR,
            "codespace": os.environ.get("CODESPACE_NAME") or os.environ.get("HOSTNAME") or "codespace",
            "pid": os.getpid(),
            "mode": "codespace-worker-relay",
            "version": WORKER_PROTOCOL_VERSION,
            "started_at": WORKER_STARTED_AT,
            "processed_count": PROCESSED_COUNT,
            "message": "worker alive",
        }
        if extra:
            payload.update(extra)
        proxy.put_file(status_path, payload, old_sha)
    except Exception as e:
        print(f"[worker] heartbeat failed: {e}", flush=True)

def process_prompt_file(path: str, sha: str) -> None:
    global PROCESSED_COUNT
    req_id = id_from_prompt_path(path)
    print(f"[worker] processing {path} req_id={req_id}", flush=True)
    write_worker_status({"state": "processing", "request_id": req_id, "message": f"processing {req_id}"})
    current_sha: Optional[str] = sha
    try:
        raw, current_sha = proxy.get_file(path)
        if raw is None:
            return
        try:
            data = proxy.decrypt_envelope(raw)
        except Exception as e:
            write_response(req_id, {"error": {"code": 401, "message": str(e)}})
            if current_sha:
                proxy.delete_file(path, current_sha)
            write_worker_status({"ok": False, "state": "error", "request_id": req_id, "message": "decrypt failed: " + str(e)[:220]})
            return
        if data.get("id"):
            req_id = str(data["id"])
        if data.get("type") != "browser":
            write_response(req_id, {"error": {"code": 400, "message": "Codespace Worker فقط درخواست‌های مرورگر را پردازش می‌کند."}})
            return
        result = proxy.run_browser_request(data)
        # Make the backend visible in the UI/debug payload.
        try:
            result.setdefault("meta", {})["backend"] = "codespace-worker"
            if isinstance(result.get("browser"), dict):
                result["browser"]["backend"] = "codespace-worker"
        except Exception:
            pass
        write_response(req_id, result)
        if current_sha:
            proxy.delete_file(path, current_sha)
        PROCESSED_COUNT += 1
        write_worker_status({"state": "idle", "last_request_id": req_id, "last_done": time.time(), "message": f"done {req_id}"})
        print(f"[worker] done req_id={req_id}", flush=True)
    except Exception as e:
        print(f"[worker] error: {e}", flush=True)
        traceback.print_exc()
        write_response(req_id, {"error": {"code": 500, "message": str(e), "trace": traceback.format_exc()[-1800:]}})
        write_worker_status({"ok": False, "state": "error", "request_id": req_id, "message": str(e)[:260]})


def main() -> None:
    print("Codespace Worker Relay started")
    print(f"Repository: {REPO}")
    print(f"Queue: {QUEUE_DIR}/prompt_*.json")
    print("Encryption:", "ON" if proxy.CHAT_QUEUE_KEY else "OFF - set CHAT_QUEUE_KEY to match the web UI")
    print("Stop with Ctrl+C")
    processed = set()
    last_heartbeat = 0.0
    write_worker_status({"state": "started", "message": "codespace_worker.py started"})
    while True:
        try:
            files = list_worker_files()
            pending = [x for x in files if re.match(r"^prompt_[A-Za-z0-9_-]+\.json$", x.get("name", ""))]
            if time.time() - last_heartbeat >= HEARTBEAT_SECONDS:
                write_worker_status({"state": "idle", "pending_prompts": len(pending)})
                last_heartbeat = time.time()
            for item in files:
                path = item.get("path", "")
                sha = item.get("sha", "")
                name = item.get("name", "")
                if not re.match(r"^prompt_[A-Za-z0-9_-]+\.json$", name):
                    continue
                key = f"{path}:{sha}"
                if key in processed:
                    continue
                process_prompt_file(path, sha)
                processed.add(key)
        except KeyboardInterrupt:
            write_worker_status({"ok": False, "state": "stopped", "message": "worker stopped by user"})
            print("\nWorker stopped.")
            return
        except Exception as e:
            print(f"[worker] loop error: {e}", flush=True)
            traceback.print_exc()
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
