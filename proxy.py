import base64
import json
import os
import re
import time
import traceback
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# ─────────────────────────────────────────────────────────────────────────────
# Environment
# ─────────────────────────────────────────────────────────────────────────────
GH_TOKEN = os.environ["GH_TOKEN"]
REPO = os.environ["REPO"]
CHAT_QUEUE_KEY = os.environ.get("CHAT_QUEUE_KEY", "")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
XAI_API_KEY = os.environ.get("XAI_API_KEY", "")
PUTER_TOKEN = os.environ.get("PUTER_TOKEN", "")

BASE = "https://api.github.com"
GH_HEADERS = {
    "Authorization": f"token {GH_TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/vnd.github.v3+json",
}

POLL_SECONDS = 3
REQUEST_TIMEOUT = 120

# ─────────────────────────────────────────────────────────────────────────────
# GitHub content helpers
# ─────────────────────────────────────────────────────────────────────────────
def _b64_json(data: Any) -> str:
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def list_queue_files() -> List[Dict[str, Any]]:
    r = requests.get(
        f"{BASE}/repos/{REPO}/contents/queue?_={time.time()}",
        headers=GH_HEADERS,
        timeout=20,
    )
    if r.status_code == 404:
        return []
    r.raise_for_status()
    items = r.json()
    if not isinstance(items, list):
        return []
    return [x for x in items if x.get("type") == "file"]


def get_file(path: str) -> Tuple[Optional[Any], Optional[str]]:
    r = requests.get(
        f"{BASE}/repos/{REPO}/contents/{path}?_={time.time()}",
        headers=GH_HEADERS,
        timeout=20,
    )
    if r.status_code == 404:
        return None, None
    r.raise_for_status()
    d = r.json()
    content = base64.b64decode(d["content"]).decode("utf-8")
    return json.loads(content), d["sha"]


def put_file(path: str, content: Any, sha: Optional[str] = None) -> bool:
    body = {"message": f"proxy: {path}", "content": _b64_json(content)}
    if sha:
        body["sha"] = sha
    r = requests.put(
        f"{BASE}/repos/{REPO}/contents/{path}",
        headers=GH_HEADERS,
        json=body,
        timeout=25,
    )
    if r.status_code not in (200, 201):
        print(f"put_file failed {path}: {r.status_code} {r.text[:400]}")
        return False
    return True


def delete_file(path: str, sha: str) -> bool:
    body = {"message": f"proxy: delete {path}", "sha": sha}
    r = requests.delete(
        f"{BASE}/repos/{REPO}/contents/{path}",
        headers=GH_HEADERS,
        json=body,
        timeout=25,
    )
    if r.status_code not in (200, 204):
        print(f"delete_file failed {path}: {r.status_code} {r.text[:300]}")
        return False
    return True

# ─────────────────────────────────────────────────────────────────────────────
# Public-repo queue encryption: AES-GCM + PBKDF2-SHA256
# The browser encrypts prompt_*.json; the Action decrypts it with CHAT_QUEUE_KEY.
# The Action encrypts response_*.json; the browser decrypts it with the same key.
# ─────────────────────────────────────────────────────────────────────────────
def derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=200_000,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def decrypt_envelope(obj: Any) -> Any:
    if not isinstance(obj, dict) or obj.get("secure") != 1:
        return obj
    if not CHAT_QUEUE_KEY:
        raise RuntimeError("CHAT_QUEUE_KEY secret is missing. Add the same Security Key in GitHub Secrets and in the web setup screen.")
    salt = base64.b64decode(obj["salt"])
    iv = base64.b64decode(obj["iv"])
    ciphertext = base64.b64decode(obj["data"])
    key = derive_key(CHAT_QUEUE_KEY, salt)
    raw = AESGCM(key).decrypt(iv, ciphertext, None)
    return json.loads(raw.decode("utf-8"))


def encrypt_envelope(obj: Any) -> Any:
    if not CHAT_QUEUE_KEY:
        return obj
    salt = os.urandom(16)
    iv = os.urandom(12)
    key = derive_key(CHAT_QUEUE_KEY, salt)
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(iv, raw, None)
    return {
        "secure": 1,
        "alg": "AES-GCM-PBKDF2-SHA256",
        "salt": base64.b64encode(salt).decode("ascii"),
        "iv": base64.b64encode(iv).decode("ascii"),
        "data": base64.b64encode(ciphertext).decode("ascii"),
    }

# ─────────────────────────────────────────────────────────────────────────────
# Message conversion
# ─────────────────────────────────────────────────────────────────────────────
def contents_to_openai_messages(contents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
    for c in contents:
        role = "assistant" if c.get("role") == "model" else c.get("role", "user")
        parts = c.get("parts", [])
        content_parts = []
        for p in parts:
            if "text" in p:
                content_parts.append({"type": "text", "text": p["text"]})
            elif "inline_data" in p:
                mime = p["inline_data"].get("mime_type", "image/png")
                data = p["inline_data"].get("data", "")
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{data}"},
                })
        if len(content_parts) == 1 and content_parts[0]["type"] == "text":
            final_content: Any = content_parts[0]["text"]
        elif content_parts:
            final_content = content_parts
        else:
            final_content = ""
        messages.append({"role": role, "content": final_content})
    return messages


def extract_text_from_openai(data: Dict[str, Any]) -> str:
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, dict):
                out.append(part.get("text") or part.get("content") or "")
        return "".join(out)
    return str(content or "")


def as_gemini_response(text: str, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    res = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    if meta:
        res["meta"] = meta
    return res

# ─────────────────────────────────────────────────────────────────────────────
# Web search helper: DuckDuckGo Instant + HTML fallback
# ─────────────────────────────────────────────────────────────────────────────
def clean_html(html: str) -> str:
    html = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", html, flags=re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    html = re.sub(r"&\w+;", " ", html)
    return re.sub(r"\s+", " ", html).strip()[:4500]


def fetch_url(url: str) -> Optional[str]:
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True)
        if "text" in r.headers.get("Content-Type", ""):
            return clean_html(r.text)
    except Exception as e:
        print(f"fetch_url error: {e}")
    return None


def ddg_search(query: str, n: int = 5) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    try:
        r = requests.get(
            f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1",
            timeout=12,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        d = r.json()
        if d.get("AbstractText"):
            results.append({"title": d.get("Heading", ""), "snippet": d["AbstractText"], "url": d.get("AbstractURL", "")})
        for t in d.get("RelatedTopics", [])[:5]:
            if isinstance(t, dict) and t.get("Text"):
                results.append({"title": t["Text"][:80], "snippet": t["Text"], "url": t.get("FirstURL", "")})
    except Exception as e:
        print(f"DDG instant error: {e}")

    if len(results) < 2:
        try:
            r = requests.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query},
                timeout=12,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            snips = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', r.text, re.S)
            titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', r.text, re.S)
            hrefs = re.findall(r'class="result__a" href="([^"]+)"', r.text)
            for i in range(min(n, len(snips))):
                results.append({
                    "title": re.sub(r"<[^>]+>", "", titles[i]).strip() if i < len(titles) else "",
                    "snippet": re.sub(r"<[^>]+>", "", snips[i]).strip(),
                    "url": hrefs[i] if i < len(hrefs) else "",
                })
        except Exception as e:
            print(f"DDG html error: {e}")
    return results[:n]


def inject_search(contents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    query = ""
    for c in reversed(contents):
        if c.get("role") == "user":
            for p in c.get("parts", []):
                if "text" in p:
                    query = p["text"]
                    break
        if query:
            break
    if not query:
        return contents

    results = ddg_search(query)
    if not results:
        return contents

    ctx = f"[نتایج جستجوی وب برای: {query!r}]\n\n"
    for i, res in enumerate(results, 1):
        ctx += f"--- منبع {i}: {res.get('title','')} ---\nURL: {res.get('url','')}\n{res.get('snippet','')}\n"
        if res.get("url", "").startswith("http"):
            body = fetch_url(res["url"])
            if body:
                ctx += f"محتوا:\n{body}\n"
        ctx += "\n"
    ctx += "[پایان نتایج جستجو. در پاسخ، اگر از این نتایج استفاده کردی لینک‌ها را هم ذکر کن.]\n\n"

    enhanced = list(contents)
    last = dict(enhanced[-1])
    new_parts = []
    inserted = False
    for p in last.get("parts", []):
        if "text" in p and not inserted:
            new_parts.append({"text": ctx + "سوال کاربر: " + p["text"]})
            inserted = True
        else:
            new_parts.append(p)
    if not inserted:
        new_parts.append({"text": ctx})
    last["parts"] = new_parts
    enhanced[-1] = last
    return enhanced

# ─────────────────────────────────────────────────────────────────────────────
# Provider calls
# ─────────────────────────────────────────────────────────────────────────────
def call_openai_compatible(provider: str, model: str, contents: List[Dict[str, Any]]) -> Dict[str, Any]:
    messages = contents_to_openai_messages(contents)

    if provider == "github":
        api_key = GH_TOKEN
        url = "https://models.github.ai/inference/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "application/vnd.github+json"}
    elif provider == "openrouter":
        if not OPENROUTER_API_KEY:
            raise RuntimeError("OPENROUTER_API_KEY secret is missing.")
        api_key = OPENROUTER_API_KEY
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": f"https://github.com/{REPO}",
            "X-Title": "GitHub Pages AI Proxy",
        }
    elif provider == "groq":
        if not GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY secret is missing.")
        api_key = GROQ_API_KEY
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    elif provider == "xai":
        if not XAI_API_KEY:
            raise RuntimeError("XAI_API_KEY secret is missing.")
        api_key = XAI_API_KEY
        url = "https://api.x.ai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    elif provider == "puter":
        if not PUTER_TOKEN:
            raise RuntimeError("PUTER_TOKEN secret is missing.")
        api_key = PUTER_TOKEN
        url = "https://api.puter.com/puterai/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    else:
        raise RuntimeError(f"Unknown OpenAI-compatible provider: {provider}")

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
    }

    # Some providers understand reasoning; unsupported providers usually ignore it or return a clear error.
    if any(x in model for x in ("gpt-5", "claude-opus", "gemini-3", "grok-4", "deepseek-v4", "kimi-k2.6", "mimo")):
        payload["reasoning"] = {"effort": "high"}

    r = requests.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"{provider}/{model} failed: HTTP {r.status_code}: {r.text[:700]}")
    data = r.json()
    text = extract_text_from_openai(data)
    if not text:
        raise RuntimeError(f"{provider}/{model} returned an empty response: {json.dumps(data)[:500]}")
    return as_gemini_response(text, {"provider": provider, "model": model})


def call_gemini(model: str, contents: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY secret is missing.")
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}",
        json={"contents": contents},
        timeout=REQUEST_TIMEOUT,
    )
    if r.status_code != 200:
        raise RuntimeError(f"gemini/{model} failed: HTTP {r.status_code}: {r.text[:700]}")
    data = r.json()
    data["meta"] = {"provider": "gemini", "model": model}
    return data


def call_provider(provider: str, model: str, contents: List[Dict[str, Any]]) -> Dict[str, Any]:
    if provider == "gemini":
        return call_gemini(model, contents)
    return call_openai_compatible(provider, model, contents)


def fallback_chain(primary_provider: str, primary_model: str) -> List[Tuple[str, str]]:
    chain = [(primary_provider, primary_model)]
    # Keep the user's selected model first, then try genuinely low/no-cost fallbacks.
    candidates = [
        ("github", "openai/gpt-5.4-mini"),
        ("github", "deepseek/deepseek-v4-flash"),
        ("openrouter", "openrouter/free"),
        ("groq", "openai/gpt-oss-120b"),
        ("gemini", "gemini-3-flash-preview"),
        ("puter", "openai/gpt-5.5"),
    ]
    for item in candidates:
        if item not in chain:
            chain.append(item)
    return chain


def run_request(data: Dict[str, Any]) -> Dict[str, Any]:
    provider = data.get("provider", "github")
    model = data.get("model", "openai/gpt-5.4-mini")
    use_search = bool(data.get("use_search", False))
    use_fallback = bool(data.get("use_fallback", True))
    contents = data.get("contents", [])

    if use_search:
        contents = inject_search(contents)

    errors = []
    attempts = fallback_chain(provider, model) if use_fallback else [(provider, model)]
    for prov, mod in attempts:
        try:
            print(f"calling provider={prov} model={mod}")
            res = call_provider(prov, mod, contents)
            if errors:
                note = "\n\n---\n«یادداشت سیستم: مدل انتخابی اول خطا داد و پاسخ با fallback ساخته شد.»"
                try:
                    res["candidates"][0]["content"]["parts"][0]["text"] += note
                    res["meta"]["fallback_errors"] = errors[-3:]
                except Exception:
                    pass
            return res
        except Exception as e:
            msg = str(e)
            print(f"attempt failed: {msg[:600]}")
            errors.append({"provider": prov, "model": mod, "error": msg[:900]})
            # Only fallback on missing keys, rate limits, unavailable model, server errors.
            continue
    return {"error": {"code": 500, "message": "All providers failed.", "details": errors}}

# ─────────────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────────────
def id_from_prompt_path(path: str) -> str:
    m = re.search(r"queue/prompt_([A-Za-z0-9_-]+)\.json$", path)
    return m.group(1) if m else "unknown"


def write_response(req_id: str, result: Any) -> None:
    resp_path = f"queue/response_{req_id}.json"
    _, old_sha = get_file(resp_path)
    payload = encrypt_envelope(result)
    put_file(resp_path, payload, old_sha)


def process_prompt_file(path: str, sha: str) -> None:
    req_id = id_from_prompt_path(path)
    print(f"processing {path} req_id={req_id}")
    try:
        raw, current_sha = get_file(path)
        if raw is None:
            return
        try:
            data = decrypt_envelope(raw)
        except Exception as e:
            write_response(req_id, {"error": {"code": 401, "message": str(e)}})
            return

        if data.get("id"):
            req_id = data["id"]
        result = run_request(data)
        write_response(req_id, result)
        if current_sha:
            delete_file(path, current_sha)
        print(f"done req_id={req_id}")
    except Exception as e:
        print(f"process error: {e}")
        traceback.print_exc()
        write_response(req_id, {"error": {"code": 500, "message": str(e), "trace": traceback.format_exc()[-1500:]}})


def main() -> None:
    print("AI proxy started: GitHub Models + Puter + OpenRouter + Groq + Gemini + xAI")
    print("Queue encryption:", "ON" if CHAT_QUEUE_KEY else "OFF - add CHAT_QUEUE_KEY for public repos")
    processed = set()
    while True:
        try:
            for item in list_queue_files():
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
        except Exception as e:
            print(f"loop error: {e}")
            traceback.print_exc()
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
