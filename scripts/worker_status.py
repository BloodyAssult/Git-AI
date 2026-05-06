#!/usr/bin/env python3
"""Write a clear-text worker status file to browser_queue/worker_status.json.
Used by start_codespace_worker.sh before Python dependencies/Playwright are ready,
so the GitHub Pages UI can show the real boot/error state instead of waiting forever.
"""
import base64
import json
import os
import re
import subprocess
import sys
import time
from urllib import request, error

BASE = "https://api.github.com"
QUEUE_DIR = os.environ.get("WORKER_QUEUE_DIR", "browser_queue").strip("/") or "browser_queue"
WORKER_PROTOCOL_VERSION = "2026-05-06-downloads-v4"


def run(cmd):
    try:
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return ""


def guess_repo():
    if os.environ.get("REPO"):
        return os.environ["REPO"].strip()
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"].strip()
    url = run(["git", "config", "--get", "remote.origin.url"])
    m = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+)(?:\.git)?", url or "")
    return f"{m.group('owner')}/{m.group('repo')}" if m else ""


def guess_token():
    for key in ("GH_TOKEN", "WORKER_GITHUB_TOKEN", "GITHUB_TOKEN"):
        val = os.environ.get(key)
        if val:
            return val.strip()
    return run(["gh", "auth", "token"])


def api(method, path, token, body=None):
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        BASE + path,
        method=method,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with request.urlopen(req, timeout=25) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def main():
    repo = guess_repo()
    token = guess_token()
    if not repo or not token:
        # Nothing else we can do; print so /tmp/git-ai-worker.log has it.
        print("worker_status: missing repo/token", file=sys.stderr)
        return 2
    state = sys.argv[1] if len(sys.argv) > 1 else "booting"
    message = " ".join(sys.argv[2:]).strip() if len(sys.argv) > 2 else state
    path = f"/{repo}/contents/{QUEUE_DIR}/worker_status.json"
    old = api("GET", path + f"?_={time.time()}", token)
    sha = old.get("sha") if isinstance(old, dict) else None
    payload = {
        "ok": state not in {"error", "missing_key", "fatal"},
        "state": state,
        "message": message,
        "ts": time.time(),
        "repo": repo,
        "queue": QUEUE_DIR,
        "codespace": os.environ.get("CODESPACE_NAME") or os.environ.get("HOSTNAME") or "codespace",
        "pid": os.getpid(),
        "mode": "codespace-worker-relay",
        "version": WORKER_PROTOCOL_VERSION,
        "boot": True,
    }
    body = {
        "message": f"worker status: {state}",
        "content": base64.b64encode(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).decode("ascii"),
    }
    if sha:
        body["sha"] = sha
    api("PUT", path, token, body)
    print(f"worker_status: {state} - {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
