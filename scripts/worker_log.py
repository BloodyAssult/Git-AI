#!/usr/bin/env python3
"""Append a small diagnostic event to browser_queue/worker_log.json.
This file is intentionally plain JSON (not encrypted) so the GitHub Pages UI can
show what happened during low-data Codespace auto-start without opening VS Code Web.
"""
import base64
import json
import os
import re
import subprocess
import sys
import time
import traceback
from urllib import request, error

BASE = "https://api.github.com"
QUEUE_DIR = os.environ.get("WORKER_QUEUE_DIR", "browser_queue").strip("/") or "browser_queue"
WORKER_PROTOCOL_VERSION = "2026-05-06-downloads-v4"
MAX_EVENTS = int(os.environ.get("WORKER_LOG_MAX_EVENTS", "120"))


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
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
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
        msg = e.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"GitHub API {e.code}: {msg}")


def decode_content(obj):
    if not isinstance(obj, dict) or not obj.get("content"):
        return None
    raw = base64.b64decode(obj["content"].encode("ascii"))
    return json.loads(raw.decode("utf-8"))


def main():
    repo = guess_repo()
    token = guess_token()
    level = sys.argv[1] if len(sys.argv) > 1 else "info"
    message = " ".join(sys.argv[2:]).strip() if len(sys.argv) > 2 else level
    event = {
        "ts": time.time(),
        "level": level,
        "message": message,
        "version": WORKER_PROTOCOL_VERSION,
        "codespace": os.environ.get("CODESPACE_NAME") or os.environ.get("HOSTNAME") or "codespace",
        "pid": os.getpid(),
        "repo": repo,
        "cwd": os.getcwd(),
    }
    if not repo or not token:
        print("worker_log: missing repo/token", file=sys.stderr)
        print(json.dumps(event, ensure_ascii=False), file=sys.stderr)
        return 2
    path = f"/{repo}/contents/{QUEUE_DIR}/worker_log.json"
    try:
        old = api("GET", path + f"?_={time.time()}", token)
        sha = old.get("sha") if isinstance(old, dict) else None
        data = decode_content(old) if old else None
        if not isinstance(data, dict):
            data = {"version": WORKER_PROTOCOL_VERSION, "events": []}
        events = data.get("events") if isinstance(data.get("events"), list) else []
        events.append(event)
        data.update({"version": WORKER_PROTOCOL_VERSION, "updated_at": time.time(), "events": events[-MAX_EVENTS:]})
        body = {
            "message": f"worker log: {level}",
            "content": base64.b64encode(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).decode("ascii"),
        }
        if sha:
            body["sha"] = sha
        api("PUT", path, token, body)
        print(f"worker_log: {level} - {message}")
        return 0
    except Exception:
        print("worker_log failed", file=sys.stderr)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
