"""Text generation with the free Gemini API (or Groq), built to survive model
renames and to spend as few requests/tokens as possible.

* The API key goes in a header, never in the URL, so it can't leak into logs.
* The model is chosen automatically from the models your key can use
  (Google renames/retires models often: a fixed name eventually 404s).
* "content" calls use the best Flash model, "light" calls (comment replies)
  use Flash-Lite, which has much higher free limits.
* On 429 (rate limit) it waits and falls back to the other model.
"""
import json
import os
import re
import time

import requests

from .config import env

API = "https://generativelanguage.googleapis.com/v1beta"
_models_cache: list[str] | None = None


class LLMError(RuntimeError):
    pass


def redact(text: str) -> str:
    """Removes any secret value that might appear in an error message."""
    text = str(text)
    for name in ("GEMINI_API_KEY", "GROQ_API_KEY", "IG_ACCESS_TOKEN", "FB_PAGE_TOKEN",
                 "PEXELS_API_KEY", "BLOB_READ_WRITE_TOKEN"):
        val = os.environ.get(name, "")
        if len(val) > 6:
            text = text.replace(val, "***")
    return re.sub(r"(key=)[^&\s]+", r"\1***", text)


def _headers() -> dict:
    return {"x-goog-api-key": env("GEMINI_API_KEY"), "Content-Type": "application/json"}


def list_models(refresh=False) -> list[str]:
    global _models_cache
    if _models_cache is None or refresh:
        r = requests.get(f"{API}/models", headers=_headers(), params={"pageSize": 1000}, timeout=30)
        if r.status_code >= 400:
            raise LLMError(f"Gemini: cannot list models (HTTP {r.status_code}) - check the API key")
        _models_cache = [m["name"].split("/", 1)[1] for m in r.json().get("models", [])
                         if "generateContent" in m.get("supportedGenerationMethods", [])]
    return _models_cache


def _version(name: str) -> float:
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    return float(m.group(1)) if m else 0.0


def pick_model(kind: str, configured: str | None = None) -> str:
    models = list_models()
    if configured and configured in models:
        return configured
    lite = kind == "light"
    alias = "gemini-flash-lite-latest" if lite else "gemini-flash-latest"
    if alias in models:
        return alias
    bad = ("image", "tts", "audio", "live", "embedding", "thinking", "exp", "learnlm", "gemma")
    cands = [m for m in models if m.startswith("gemini") and "flash" in m
             and ("lite" in m) == lite and not any(b in m for b in bad)]
    if not cands:  # anything that can generate text
        cands = [m for m in models if m.startswith("gemini") and not any(b in m for b in bad)]
    if not cands:
        raise LLMError("Gemini: no text model available for this key")
    # newest version first, stable before preview
    cands.sort(key=lambda m: (_version(m), "preview" not in m), reverse=True)
    return cands[0]


def _gemini(prompt: str, model: str, temperature: float, as_json: bool, images: list[bytes] | None = None) -> str:
    import base64
    parts = [{"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(b).decode()}} for b in (images or [])]
    body = {"contents": [{"parts": parts + [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature}}
    if as_json:
        body["generationConfig"]["responseMimeType"] = "application/json"
    r = requests.post(f"{API}/models/{model}:generateContent", headers=_headers(), json=body, timeout=120)
    if r.status_code >= 400:
        try:
            msg = r.json().get("error", {}).get("message", "")
        except ValueError:
            msg = r.text[:200]
        err = LLMError(f"Gemini {model}: HTTP {r.status_code} {redact(msg)[:300]}")
        err.status = r.status_code
        raise err
    data = r.json()
    try:
        return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError):
        raise LLMError(f"Gemini {model}: empty answer ({data.get('promptFeedback', '')})")


def _groq(prompt: str, model: str, temperature: float, as_json: bool, images=None) -> str:
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": temperature}
    if as_json:
        body["response_format"] = {"type": "json_object"}
    r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                      headers={"Authorization": f"Bearer {env('GROQ_API_KEY')}"}, json=body, timeout=120)
    if r.status_code >= 400:
        err = LLMError(f"Groq: HTTP {r.status_code} {redact(r.text)[:300]}")
        err.status = r.status_code
        raise err
    return r.json()["choices"][0]["message"]["content"]


def parse_json(raw: str):
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
    try:
        return json.loads(raw)
    except ValueError:
        m = re.search(r"[\[{].*[\]}]", raw, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def generate(prompt: str, cfg: dict, kind: str = "content", as_json: bool = True,
             validate=None, attempts: int = 4, images: list[bytes] | None = None):
    """Returns parsed JSON (or text). `validate(obj)` may raise to force a retry."""
    llm = cfg.get("llm", {})
    temperature = llm.get("temperature", 0.9) if kind == "content" else 0.6
    if llm.get("provider") == "groq":
        model = llm.get("groq_model", "llama-3.3-70b-versatile")
        order = [(_groq, model)]
    else:
        main = pick_model(kind, llm.get("gemini_model") if kind == "content" else None)
        other = pick_model("content" if kind == "light" else "light")
        order = [(_gemini, main), (_gemini, other)]

    last = None
    for i in range(attempts):
        fn, model = order[0] if (i % 2 == 0 or len(order) == 1) else order[1]
        try:
            out = fn(prompt, model, temperature, as_json, images)
            obj = parse_json(out) if as_json else out
            if validate:
                validate(obj)
            print(f"[llm] {model} ok")
            return obj
        except Exception as e:  # noqa: BLE001
            last = e
            status = getattr(e, "status", None)
            print(f"[llm] {model} attempt {i + 1} failed: {redact(e)}")
            if status == 404 and fn is _gemini:
                list_models(refresh=True)
            time.sleep(min(30, 4 * (i + 1)) if status == 429 else 2)
    raise LLMError(f"text generation failed: {redact(last)}")
