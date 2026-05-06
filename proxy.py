import base64
import json
import os
import re
import time
import traceback
import urllib.parse
import ipaddress
import socket
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
AVALAI_API_KEY = os.environ.get("AVALAI_API_KEY", "")
HF_TOKEN = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_API_KEY") or os.environ.get("HUGGINGFACEHUB_API_TOKEN") or ""
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
        timeout=25,
    )
    if r.status_code == 404:
        return None, None
    r.raise_for_status()
    d = r.json()
    content = d.get("content") or ""
    # For larger files GitHub Contents API may omit inline content; fetch the blob.
    if (not content or d.get("encoding") == "none") and d.get("sha"):
        br = requests.get(
            f"{BASE}/repos/{REPO}/git/blobs/{d['sha']}?_={time.time()}",
            headers=GH_HEADERS,
            timeout=35,
        )
        br.raise_for_status()
        bd = br.json()
        content = bd.get("content") or ""
    if not content:
        return None, d.get("sha")
    content = base64.b64decode(content).decode("utf-8")
    return json.loads(content), d.get("sha")


def get_file_sha(path: str) -> Optional[str]:
    r = requests.get(
        f"{BASE}/repos/{REPO}/contents/{path}?_={time.time()}",
        headers=GH_HEADERS,
        timeout=20,
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    d = r.json()
    return d.get("sha")


def put_file(path: str, content: Any, sha: Optional[str] = None) -> bool:
    body = {"message": f"proxy: {path}", "content": _b64_json(content)}
    if sha:
        body["sha"] = sha
    r = requests.put(
        f"{BASE}/repos/{REPO}/contents/{path}",
        headers=GH_HEADERS,
        json=body,
        timeout=60,
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
        text_parts: List[Dict[str, Any]] = []
        image_parts: List[Dict[str, Any]] = []
        for p in parts:
            if "text" in p:
                text_parts.append({"type": "text", "text": p["text"]})
            elif "inline_data" in p:
                mime = p["inline_data"].get("mime_type", "image/jpeg")
                data = p["inline_data"].get("data", "")
                if data:
                    image_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{data}", "detail": "auto"},
                    })
        # Put the textual instruction before images. xAI accepts any order, but some gateways are stricter.
        content_parts = text_parts + image_parts
        if len(content_parts) == 1 and content_parts[0]["type"] == "text":
            final_content: Any = content_parts[0]["text"]
        elif content_parts:
            final_content = content_parts
        else:
            final_content = ""
        messages.append({"role": role, "content": final_content})
    return messages


def message_stats(messages: List[Dict[str, Any]]) -> Dict[str, int]:
    image_count = 0
    approx_b64_chars = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            for part in c:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    image_count += 1
                    url = ((part.get("image_url") or {}).get("url") or "")
                    if ";base64," in url:
                        approx_b64_chars += len(url.split(";base64,", 1)[1])
    return {"image_count": image_count, "approx_b64_chars": approx_b64_chars}


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
def _merge_meta(data: Dict[str, Any], provider: str, requested_model: str) -> Dict[str, Any]:
    return {"provider": provider, "model": data.get("model") or requested_model, "requested_model": requested_model}


def call_openai_compatible(
    provider: str,
    model: str,
    contents: List[Dict[str, Any]],
    *,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    add_reasoning: bool = True,
) -> Dict[str, Any]:
    messages = contents_to_openai_messages(contents)

    if provider == "github":
        api_key = GH_TOKEN
        url = "https://models.github.ai/inference/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10",
        }
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
    elif provider == "huggingface":
        if not HF_TOKEN:
            raise RuntimeError("HF_TOKEN secret is missing. Create a Hugging Face token with 'Make calls to Inference Providers' permission and add it to GitHub Secrets as HF_TOKEN.")
        api_key = HF_TOKEN
        url = "https://router.huggingface.co/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    elif provider == "avalai":
        if not AVALAI_API_KEY:
            raise RuntimeError("AVALAI_API_KEY secret is missing. Add your AvalAI API key to GitHub Secrets as AVALAI_API_KEY.")
        api_key = AVALAI_API_KEY
        url = "https://api.avalai.ir/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
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
    if max_tokens:
        payload["max_tokens"] = max_tokens
    if temperature is not None:
        payload["temperature"] = temperature

    # Disable OpenRouter provider fallback for exact models so a wrong model does not answer silently.
    # Keep it enabled only for the special OpenRouter free router, because that model is a router by design.
    if provider == "openrouter" and model != "openrouter/free":
        payload["provider"] = {"allow_fallbacks": False}

    # Keep extra reasoning controls limited to OpenRouter, where this extension is commonly supported.
    # Direct providers such as Groq/HuggingFace may reject unknown body fields.
    if provider == "openrouter" and add_reasoning and any(x in model for x in ("deepseek-v4", "kimi-k2.6", "mimo", "qwen3.6", "glm-5.1", "minimax-m2.7", "ling-2.6")):
        payload["reasoning"] = {"effort": "high"}

    stats = message_stats(messages)
    if stats["image_count"]:
        print(f"multimodal request: images={stats['image_count']} approx_b64_chars={stats['approx_b64_chars']}")

    r = requests.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
    raw_text = r.text or ""
    content_type = r.headers.get("Content-Type", "")
    if r.status_code != 200:
        raise RuntimeError(f"{provider}/{model} failed: HTTP {r.status_code}: {raw_text[:900]}")
    try:
        data = r.json()
    except ValueError:
        preview = raw_text.strip()[:900] or "<empty body>"
        extra = ""
        if stats["image_count"]:
            extra = f" images={stats['image_count']} approx_payload_mb={stats['approx_b64_chars']/1024/1024:.2f}. Try one smaller image or a vision-capable model if the gateway rejects it."
        raise RuntimeError(f"{provider}/{model} returned a non-JSON response. HTTP {r.status_code}, Content-Type={content_type}.{extra} Body preview: {preview}")

    text = extract_text_from_openai(data)
    if not text:
        raise RuntimeError(f"{provider}/{model} returned an empty response: {json.dumps(data)[:500]}")
    return as_gemini_response(text, _merge_meta(data, provider, model))


def call_gemini(
    model: str,
    contents: List[Dict[str, Any]],
    *,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
) -> Dict[str, Any]:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY secret is missing.")
    gen_cfg: Dict[str, Any] = {}
    if max_tokens:
        gen_cfg["maxOutputTokens"] = max_tokens
    if temperature is not None:
        gen_cfg["temperature"] = temperature
    body: Dict[str, Any] = {"contents": contents}
    if gen_cfg:
        body["generationConfig"] = gen_cfg
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}",
        json=body,
        timeout=REQUEST_TIMEOUT,
    )
    if r.status_code != 200:
        raise RuntimeError(f"gemini/{model} failed: HTTP {r.status_code}: {r.text[:700]}")
    data = r.json()
    data["meta"] = {"provider": "gemini", "model": model, "requested_model": model}
    return data


def call_provider(
    provider: str,
    model: str,
    contents: List[Dict[str, Any]],
    *,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    add_reasoning: bool = True,
) -> Dict[str, Any]:
    if provider == "gemini":
        return call_gemini(model, contents, max_tokens=max_tokens, temperature=temperature)
    return call_openai_compatible(provider, model, contents, max_tokens=max_tokens, temperature=temperature, add_reasoning=add_reasoning)


def _first_user_text(contents: List[Dict[str, Any]]) -> Tuple[str, bool]:
    text = ""
    has_img = False
    for c in contents:
        if c.get("role") != "user":
            continue
        for p in c.get("parts", []):
            if "text" in p and not text:
                text = p.get("text", "")
            if "inline_data" in p:
                has_img = True
    return text.strip(), has_img


def local_title(text: str, has_img: bool = False) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    t = re.sub(r"^(سلام|درود|هی|hello|hi)\s*[,،!]*\s*", "", t, flags=re.I)
    if not t:
        return "تحلیل تصویر" if has_img else "چت جدید"
    # Remove common filler and keep a compact topic-like title.
    t = re.sub(r"\b(لطفا|لطفاً|میخوام|می‌خوام|میشه|میتونی|می‌تونی|برام|برای من)\b", "", t)
    t = re.sub(r"\s+", " ", t).strip(" -،,.؟?")
    words = t.split()
    return " ".join(words[:7])[:58] or ("تحلیل تصویر" if has_img else "چت جدید")


def clean_title(title: str) -> str:
    title = re.sub(r"[\n\r\t]+", " ", title or "")
    title = title.strip().strip("\"“”'`*-:،. ")
    title = re.sub(r"^(عنوان|Title)\s*[:：-]\s*", "", title, flags=re.I).strip()
    title = re.sub(r"\s+", " ", title)
    if len(title) > 58:
        title = title[:58].rstrip() + "…"
    return title


def _extract_text_from_gemini_like(res: Dict[str, Any]) -> str:
    try:
        return res.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
    except Exception:
        return ""


def generate_smart_title(contents: List[Dict[str, Any]], reply: str, preferred: Tuple[str, str]) -> Dict[str, str]:
    user_text, has_img = _first_user_text(contents)
    fallback = local_title(user_text, has_img)
    prompt = (
        "برای این گفت‌وگو یک عنوان کوتاه و طبیعی فارسی بساز. "
        "فقط خود عنوان را بده؛ بدون نقل‌قول، بدون نقطه، بدون توضیح. "
        "۲ تا ۶ کلمه، شبیه عنوان چت در ChatGPT.\n\n"
        f"پیام کاربر:\n{user_text[:1400]}\n\n"
        f"خلاصه پاسخ مدل:\n{reply[:1200]}"
    )
    title_contents = [{"role": "user", "parts": [{"text": prompt}]}]
    candidates: List[Tuple[str, str]] = []
    # Prefer cheap/free title models; if no key exists they fail fast and local fallback is used.
    if OPENROUTER_API_KEY:
        candidates.append(("openrouter", "openrouter/free"))
    if HF_TOKEN:
        candidates.append(("huggingface", "openai/gpt-oss-20b:groq"))
    if GEMINI_API_KEY:
        candidates.append(("gemini", "gemini-3-flash-preview"))
    if preferred not in candidates:
        candidates.append(preferred)
    for prov, mod in candidates:
        try:
            res = call_provider(prov, mod, title_contents, max_tokens=48, temperature=0.2, add_reasoning=False)
            title = clean_title(_extract_text_from_gemini_like(res))
            if 2 <= len(title) <= 60:
                return {"title": title, "title_provider": prov, "title_model": mod}
        except Exception as e:
            print(f"smart title failed on {prov}/{mod}: {str(e)[:240]}")
    return {"title": fallback, "title_provider": "local", "title_model": "heuristic"}


def fallback_chain(primary_provider: str, primary_model: str) -> List[Tuple[str, str]]:
    chain = [(primary_provider, primary_model)]
    # Keep the user's selected model first, then try low/no-cost fallbacks.
    candidates = [
        ("huggingface", "openai/gpt-oss-20b:groq"),
        ("huggingface", "Qwen/Qwen2.5-7B-Instruct:together"),
        ("huggingface", "meta-llama/Llama-3.1-8B-Instruct:novita"),
        ("openrouter", "openrouter/free"),
        ("openrouter", "qwen/qwen3.6-plus:free"),
        ("openrouter", "xiaomi/mimo-v2-flash:free"),
        ("openrouter", "tencent/hy3-preview:free"),
        ("groq", "openai/gpt-oss-120b"),
        ("gemini", "gemini-3-flash-preview"),
        ("github", "openai/gpt-4.1-mini"),
    ]
    for item in candidates:
        if item not in chain:
            chain.append(item)
    return chain


# ─────────────────────────────────────────────────────────────────────────────
# Remote Browser Agent (Playwright inside GitHub Actions)
# ─────────────────────────────────────────────────────────────────────────────
_pw = None
_browser = None
BROWSER_SESSIONS: Dict[str, Dict[str, Any]] = {}


def _fa_digits_to_en(text: str) -> str:
    table = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    return str(text or "").translate(table)


def _safe_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise RuntimeError("URL خالی است.")
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = "https://" + url
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise RuntimeError("فقط URLهای http/https مجاز هستند.")
    host = parsed.hostname or ""
    if not host:
        raise RuntimeError("URL نامعتبر است.")
    if host.lower() in ("localhost", "localtest.me") or host.endswith(".local"):
        raise RuntimeError("باز کردن آدرس‌های local مجاز نیست.")
    try:
        ips = [x[4][0] for x in socket.getaddrinfo(host, None)]
        for ip in ips:
            addr = ipaddress.ip_address(ip)
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_reserved:
                raise RuntimeError("برای امنیت، آدرس‌های شبکه خصوصی/داخلی باز نمی‌شوند.")
    except RuntimeError:
        raise
    except Exception:
        pass
    return urllib.parse.urlunparse(parsed)


def _ensure_browser():
    global _pw, _browser
    if _browser is not None:
        return _browser
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        raise RuntimeError("Playwright نصب نیست. workflow را با dependency جدید اجرا کن: pip install playwright و python -m playwright install chromium") from e
    _pw = sync_playwright().start()
    _browser = _pw.chromium.launch(
        headless=True,
        args=[
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
        ],
    )
    return _browser


def _get_browser_session(sid: str) -> Dict[str, Any]:
    sid = sid or "default"
    sess = BROWSER_SESSIONS.get(sid)
    if sess and sess.get("page"):
        return sess
    browser = _ensure_browser()
    context = browser.new_context(
        viewport={"width": 1180, "height": 820},
        device_scale_factor=1.5,
        locale="fa-IR",
        timezone_id="Asia/Tehran",
        ignore_https_errors=True,
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()
    page.set_default_timeout(30000)
    sess = {"sid": sid, "context": context, "page": page, "created": time.time(), "updated": time.time()}
    BROWSER_SESSIONS[sid] = sess
    return sess


def _visible_elements(page) -> List[Dict[str, Any]]:
    js = r"""
    () => {
      const nodes = Array.from(document.querySelectorAll('a,button,input,textarea,select,[role="button"],[onclick],[tabindex]'));
      const out = [];
      const vw = Math.max(document.documentElement.clientWidth || 0, window.innerWidth || 0);
      const vh = Math.max(document.documentElement.clientHeight || 0, window.innerHeight || 0);
      for (const el of nodes) {
        const r = el.getBoundingClientRect();
        const st = window.getComputedStyle(el);
        if (!r || r.width < 4 || r.height < 4) continue;
        if (r.bottom < 0 || r.right < 0 || r.top > vh || r.left > vw) continue;
        if (st.visibility === 'hidden' || st.display === 'none' || Number(st.opacity || '1') < 0.05) continue;
        const tag = (el.tagName || '').toLowerCase();
        const role = el.getAttribute('role') || '';
        const href = el.href || el.getAttribute('href') || '';
        const type = el.getAttribute('type') || '';
        const label = el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('placeholder') || href || tag;
        out.push({
          tag, role, type, href,
          text: String(label || '').replace(/\s+/g,' ').trim().slice(0, 140),
          x: Math.max(0, Math.round(r.left)), y: Math.max(0, Math.round(r.top)),
          w: Math.round(r.width), h: Math.round(r.height),
          cx: Math.round(r.left + r.width/2), cy: Math.round(r.top + r.height/2)
        });
        if (out.length >= 80) break;
      }
      return out;
    }
    """
    try:
        els = page.evaluate(js)
        if isinstance(els, list):
            for i, e in enumerate(els, 1):
                e["index"] = i
            return els
    except Exception as e:
        print(f"visible elements error: {e}")
    return []


def _page_text(page, limit: int = 9000) -> str:
    try:
        txt = page.evaluate("() => document.body ? document.body.innerText : ''") or ""
        txt = re.sub(r"\s+", " ", txt).strip()
        return txt[:limit]
    except Exception:
        return ""


def _safe_wait(page) -> None:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=6000)
    except Exception:
        pass
    try:
        page.wait_for_timeout(600)
    except Exception:
        pass



def _jpeg_data_url(raw: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")


def _capture_browser_jpeg(page, quality: int = 94, max_chars: int = 1_200_000) -> str:
    # High-quality viewport screenshot. JPEG keeps queue files smaller than PNG while quality remains clear.
    # For browser frames we prefer preserving quality; max_chars is only a safety valve for unusually huge pages.
    q = int(quality)
    last = b""
    while q >= 82:
        shot = page.screenshot(type="jpeg", quality=q, full_page=False)
        last = shot
        data = _jpeg_data_url(shot)
        if not max_chars or len(data) <= max_chars:
            return data
        q -= 4
    return _jpeg_data_url(last)


def _data_url_chars(items: List[str]) -> int:
    return sum(len(x or "") for x in items)


def _evenly_sample(items: List[str], keep: int) -> List[str]:
    if keep <= 0:
        return []
    if len(items) <= keep:
        return items
    if keep == 1:
        return [items[len(items) // 2]]
    idxs = sorted(set(round(i * (len(items) - 1) / (keep - 1)) for i in range(keep)))
    out = [items[i] for i in idxs]
    # If rounding collapsed an index, fill from the end to reach the requested count.
    if len(out) < keep:
        used = set(id(x) for x in out)
        for x in reversed(items):
            if id(x) not in used:
                out.append(x)
                used.add(id(x))
            if len(out) >= keep:
                break
    return out[:keep]


def _trim_frames_for_queue(frames: List[str], final_shot: str, max_chars: int = 18_500_000) -> List[str]:
    """Keep the clip small enough for GitHub polling while preserving motion and image quality.

    The stable final screenshot is sent separately, so transition frames intentionally
    exclude it. In HQ 25-frame mode we try to keep all 24 transition frames; if the page is
    visually too heavy, we down-sample evenly instead of reducing JPEG quality first.
    """
    frames = [f for f in frames if f and f != final_shot]
    if _data_url_chars(frames + [final_shot]) <= max_chars:
        return frames
    for keep in (24, 22, 20, 18, 16, 14, 12, 10, 8, 6, 4, 3, 2, 1):
        if len(frames) < keep:
            continue
        candidate = _evenly_sample(frames, keep)
        if _data_url_chars(candidate + [final_shot]) <= max_chars:
            return candidate
    return []


def _capture_screencast_frames(page, count: int = 25, duration_ms: int = 760, quality: int = 92) -> List[str]:
    """Fast path: use Playwright's native screencast callback when available.

    This collects JPEG frames from Chromium without forcing 25 full screenshot calls.
    It keeps quality high and usually finishes much faster. Older Playwright versions
    fall back to the screenshot burst path.
    """
    sc = getattr(page, "screencast", None)
    if not sc:
        return []
    frames: List[str] = []

    def on_frame(frame: Dict[str, Any]) -> None:
        try:
            data = frame.get("data") if isinstance(frame, dict) else None
            if data:
                frames.append(_jpeg_data_url(data))
        except Exception as e:
            print(f"screencast frame failed: {e}")

    try:
        sc.start(on_frame=on_frame, quality=int(quality))
        page.wait_for_timeout(max(200, int(duration_ms)))
        sc.stop()
    except Exception as e:
        print(f"screencast unavailable, falling back: {e}")
        try:
            sc.stop()
        except Exception:
            pass
        return []
    if not frames:
        return []
    # Keep the visual timeline smooth and exactly bounded.
    return _evenly_sample(frames, count)


def _capture_transition_frames(page, count: int = 25, delay_ms: int = 28, quality: int = 92) -> List[str]:
    """Capture a short, high-quality 'live-ish' clip after an action.

    First tries Playwright native screencast for speed. Fallback is a faster screenshot
    burst with the same JPEG quality target. The last frame should be used as the stable
    browser screenshot.
    """
    frames = _capture_screencast_frames(page, count=count, duration_ms=760, quality=quality)
    if frames:
        try:
            final_frame = _capture_browser_jpeg(page, quality=96, max_chars=2_400_000)
            frames.append(final_frame)
        except Exception:
            pass
        return frames[-count:]

    frames = []
    for i in range(max(1, count - 1)):
        try:
            frames.append(_capture_browser_jpeg(page, quality=quality, max_chars=950_000))
        except Exception as e:
            print(f"frame capture {i} failed: {e}")
        try:
            page.wait_for_timeout(delay_ms)
        except Exception:
            pass
    _safe_wait(page)
    try:
        final_frame = _capture_browser_jpeg(page, quality=96, max_chars=2_400_000)
        frames.append(final_frame)
    except Exception as e:
        print(f"final frame capture failed: {e}")
    return frames[-count:]

def _state_payload(sess: Dict[str, Any], note: str = "", analysis: str = "", animate: bool = True) -> Dict[str, Any]:
    page = sess["page"]
    raw_frames = _capture_transition_frames(page) if animate else []
    if raw_frames:
        screenshot = raw_frames[-1]
        frames = _trim_frames_for_queue(raw_frames[:-1], screenshot)
    else:
        _safe_wait(page)
        screenshot = _capture_browser_jpeg(page, quality=96, max_chars=1_600_000)
        frames = []
    title = ""
    url = ""
    try:
        title = page.title()
    except Exception:
        pass
    try:
        url = page.url
    except Exception:
        pass
    elements = _visible_elements(page)
    text = _page_text(page, 7000)
    return {
        "browser": {
            "sid": sess.get("sid", "default"),
            "url": url,
            "title": title,
            "note": note,
            "analysis": analysis,
            "screenshot": screenshot,
            "frames": frames,
            "elements": elements,
            "text_preview": text,
            "ts": int(time.time()),
            "device_scale_factor": 1.5,
            "frame_profile": "hq-25frames-fast-screencast",
        },
        "meta": {"provider": "github-actions", "model": "playwright/chromium", "requested_model": "browser-agent"},
    }


def _element_by_index(page, index: int) -> Optional[Dict[str, Any]]:
    elements = _visible_elements(page)
    for e in elements:
        if int(e.get("index", -1)) == int(index):
            return e
    return None


def _extract_number(text: str) -> Optional[int]:
    t = _fa_digits_to_en(text)
    m = re.search(r"(?:#|شماره|لینک|دکمه|گزینه|click|کلیک)?\s*(\d{1,2})", t, re.I)
    if m:
        return int(m.group(1))
    words = {
        "اول": 1, "نخست": 1, "یکم": 1,
        "دوم": 2, "سوم": 3, "چهارم": 4, "پنجم": 5,
        "ششم": 6, "هفتم": 7, "هشتم": 8, "نهم": 9, "دهم": 10,
    }
    for w, n in words.items():
        if w in text:
            return n
    return None


def _click_element(page, e: Dict[str, Any]) -> str:
    page.mouse.click(int(e.get("cx", 0)), int(e.get("cy", 0)))
    label = e.get("text") or e.get("href") or e.get("tag") or "element"
    return f"کلیک شد: {label[:80]}"


def _type_into_element(page, e: Dict[str, Any], text: str) -> str:
    page.mouse.click(int(e.get("cx", 0)), int(e.get("cy", 0)))
    try:
        page.keyboard.press("Control+A")
    except Exception:
        pass
    page.keyboard.type(text, delay=10)
    label = e.get("text") or e.get("tag") or "field"
    return f"متن وارد شد در: {label[:60]}"


def _find_element_by_text(page, command: str) -> Optional[Dict[str, Any]]:
    t = command.strip()
    needles = []
    patterns = [
        r"روی\s+(.{2,60}?)(?:\s+کلیک|\s+بزن|$)",
        r"(?:دکمه|لینک|گزینه)\s+(.{2,60}?)(?:\s+را|\s+رو|\s+کلیک|\s+بزن|$)",
        r"click\s+(.{2,60})",
    ]
    for pat in patterns:
        m = re.search(pat, t, re.I)
        if m:
            needles.append(m.group(1).strip(" '\"،.؟"))
    for needle in needles:
        if not needle:
            continue
        for e in _visible_elements(page):
            hay = (e.get("text") or "") + " " + (e.get("href") or "")
            if needle.lower() in hay.lower():
                return e
    return None


def _analyze_page_with_ai(sess: Dict[str, Any], command: str, provider: str, model: str) -> str:
    page = sess["page"]
    elements = _visible_elements(page)[:35]
    element_lines = []
    for e in elements:
        element_lines.append(f"{e.get('index')}. {e.get('tag')} {e.get('text','')} {e.get('href','')[:90]}")
    prompt = (
        "تو دستیار مرورگر ریموت هستی. کاربر صفحه‌ای را باز کرده و از تو تحلیل/راهنمایی می‌خواهد. "
        "بر اساس متن صفحه و عناصر قابل کلیک پاسخ بده. اگر باید عملیات بعدی انجام شود، دقیق بگو روی کدام شماره کلیک کند.\n\n"
        f"URL: {page.url}\nTitle: {page.title()}\n\n"
        f"درخواست کاربر: {command}\n\n"
        f"عناصر قابل کلیک:\n" + "\n".join(element_lines) + "\n\n"
        f"متن صفحه:\n{_page_text(page, 12000)}"
    )
    contents = [{"role": "user", "parts": [{"text": prompt}]}]
    try:
        res = call_provider(provider, model, contents, max_tokens=900, temperature=0.25, add_reasoning=False)
        return _extract_text_from_gemini_like(res)[:5000]
    except Exception as e:
        return f"تحلیل AI ناموفق بود: {str(e)[:900]}"


def run_browser_request(data: Dict[str, Any]) -> Dict[str, Any]:
    sid = data.get("browser_session") or data.get("sid") or "default"
    action = (data.get("action") or "state").strip().lower()
    command = (data.get("command") or "").strip()
    sess = _get_browser_session(sid)
    page = sess["page"]
    note = ""
    analysis = ""

    try:
        if action in ("open", "goto"):
            url = _safe_url(data.get("url") or command)
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            note = "صفحه باز شد."
        elif action == "click_xy":
            x = int(float(data.get("x", 0)))
            y = int(float(data.get("y", 0)))
            page.mouse.click(x, y)
            note = f"کلیک روی مختصات {x},{y} انجام شد."
        elif action == "click_index":
            idx = int(data.get("index") or _extract_number(command) or 0)
            e = _element_by_index(page, idx)
            if not e:
                raise RuntimeError(f"عنصر شماره {idx} پیدا نشد؛ صفحه را Refresh/State کن.")
            note = _click_element(page, e)
        elif action == "type_index":
            idx = int(data.get("index") or _extract_number(command) or 0)
            text = data.get("text") or command
            e = _element_by_index(page, idx)
            if not e:
                raise RuntimeError(f"فیلد شماره {idx} پیدا نشد.")
            note = _type_into_element(page, e, text)
        elif action == "press":
            key = data.get("key") or command or "Enter"
            page.keyboard.press(str(key))
            note = f"کلید {key} زده شد."
        elif action == "scroll":
            dy = int(data.get("dy", 650))
            page.mouse.wheel(0, dy)
            note = "اسکرول انجام شد."
        elif action == "back":
            page.go_back(wait_until="domcontentloaded", timeout=30000)
            note = "برگشت انجام شد."
        elif action == "forward":
            page.go_forward(wait_until="domcontentloaded", timeout=30000)
            note = "رفتن به جلو انجام شد."
        elif action == "reload":
            page.reload(wait_until="domcontentloaded", timeout=30000)
            note = "صفحه تازه‌سازی شد."
        elif action in ("frames", "refresh_frames", "capture_frames"):
            note = "۲۵ فریم تازه از وضعیت فعلی صفحه گرفته شد."
        elif action == "analyze":
            provider = data.get("provider", "github")
            model = data.get("model", "openai/gpt-4.1-mini")
            analysis = _analyze_page_with_ai(sess, command or "این صفحه را خلاصه و تحلیل کن", provider, model)
            note = "تحلیل صفحه آماده شد."
        elif action == "command":
            raw = _fa_digits_to_en(command)
            url_match = re.search(r"https?://[^\s]+|(?:[\w-]+\.)+[a-zA-Z]{2,}(?:/[^\s]*)?", raw)
            if url_match and any(w in command.lower() for w in ("برو", "باز", "open", "go", "goto")):
                url = _safe_url(url_match.group(0))
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                note = "صفحه باز شد."
            elif any(w in command for w in ("برگرد", "قبلی", "back")):
                page.go_back(wait_until="domcontentloaded", timeout=30000)
                note = "برگشت انجام شد."
            elif any(w in command for w in ("رفرش", "تازه", "reload", "refresh")):
                page.reload(wait_until="domcontentloaded", timeout=30000)
                note = "صفحه تازه‌سازی شد."
            elif any(w in command for w in ("اسکرول پایین", "پایین", "scroll down")):
                page.mouse.wheel(0, 750)
                note = "اسکرول پایین انجام شد."
            elif any(w in command for w in ("اسکرول بالا", "بالا", "scroll up")):
                page.mouse.wheel(0, -750)
                note = "اسکرول بالا انجام شد."
            elif ("کلیک" in command or "بزن" in command or "click" in command.lower()) and _extract_number(command):
                idx = int(_extract_number(command) or 0)
                e = _element_by_index(page, idx)
                if not e:
                    raise RuntimeError(f"عنصر شماره {idx} پیدا نشد.")
                note = _click_element(page, e)
            elif "تایپ" in command or "type" in command.lower():
                idx = _extract_number(command)
                if not idx:
                    raise RuntimeError("برای تایپ بگو داخل شماره چند تایپ کنم؛ مثلا: تایپ 4 سلام")
                text = re.sub(r".*?(?:تایپ|type)\s*\d*\s*[:：-]?\s*", "", command, flags=re.I).strip()
                e = _element_by_index(page, int(idx))
                if not e:
                    raise RuntimeError(f"فیلد شماره {idx} پیدا نشد.")
                note = _type_into_element(page, e, text)
            elif ("کلیک" in command or "بزن" in command or "click" in command.lower()) and _find_element_by_text(page, command):
                note = _click_element(page, _find_element_by_text(page, command) or {})
            else:
                provider = data.get("provider", "github")
                model = data.get("model", "openai/gpt-4.1-mini")
                analysis = _analyze_page_with_ai(sess, command or "این صفحه را بررسی کن", provider, model)
                note = "دستور به عنوان تحلیل صفحه اجرا شد."
        else:
            note = "وضعیت فعلی صفحه گرفته شد."

        sess["updated"] = time.time()
        return _state_payload(sess, note=note, analysis=analysis)
    except Exception as e:
        try:
            state = _state_payload(sess, note=f"خطای مرورگر: {str(e)[:900]}")
            state["error"] = {"code": 500, "message": str(e)}
            return state
        except Exception:
            return {"error": {"code": 500, "message": str(e)}}

def run_request(data: Dict[str, Any]) -> Dict[str, Any]:
    if data.get("type") == "browser":
        return run_browser_request(data)

    provider = data.get("provider", "github")
    model = data.get("model", "openai/gpt-4.1-mini")
    use_search = bool(data.get("use_search", False))
    use_fallback = bool(data.get("use_fallback", False))
    make_title = bool(data.get("make_title", False))
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
                    res.setdefault("meta", {})["fallback_errors"] = errors[-3:]
                except Exception:
                    pass
            if make_title:
                try:
                    reply = res["candidates"][0]["content"]["parts"][0].get("text", "")
                    title_meta = generate_smart_title(contents, reply, (provider, model))
                    res.setdefault("meta", {}).update(title_meta)
                except Exception as e:
                    print(f"title generation wrapper failed: {str(e)[:240]}")
            return res
        except Exception as e:
            msg = str(e)
            print(f"attempt failed: {msg[:600]}")
            errors.append({"provider": prov, "model": mod, "error": msg[:900]})
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
    old_sha = get_file_sha(resp_path)
    payload = encrypt_envelope(result)
    ok = put_file(resp_path, payload, old_sha)
    if not ok:
        # If the rich browser payload is too large, retry with a lean payload.
        try:
            if isinstance(result, dict) and isinstance(result.get("browser"), dict):
                lean = dict(result)
                b = dict(result["browser"])
                b["frames"] = []
                b["note"] = (b.get("note") or "") + "\nفریم‌های ویدیو برای کاهش حجم حذف شدند."
                lean["browser"] = b
                payload = encrypt_envelope(lean)
                put_file(resp_path, payload, old_sha)
        except Exception as e:
            print(f"lean response retry failed: {e}")


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
    print("AI proxy started: AI providers + Playwright remote browser")
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
