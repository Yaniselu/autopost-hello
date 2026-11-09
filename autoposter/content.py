"""Generates the post idea, on-screen text and caption with a free LLM API."""
import json
import re
import time

import requests

from .config import DATA, env

HISTORY_FILE = DATA / "history.json"

PROMPT = """You are the social media lead for {name} ({handle}).
About the brand: {description}
Audience: {audience}
Tone: {tone}

Create ONE Instagram Reel (text-only animated video, no voiceover) in {language}.
Content pillar for this post: "{pillar}"

Do NOT repeat or closely resemble these recent topics:
{recent}

Rules for on-screen text:
- "hook": max 8 words, scroll-stopping, curiosity or bold claim.
- "slides": 3 to 5 items, each max 14 words, one idea per slide, punchy.
- Wrap 1-2 key words per hook/slide in *asterisks* to highlight them.
- Content must be accurate and genuinely useful. No fake statistics.
- "cta": short call to action, e.g. "{cta}".

Rules for caption:
- 2-4 short paragraphs, first line is a strong hook, add value beyond the video,
  end with a question to drive comments. Max 2 emojis total.
- "hashtags": exactly {hashtags_count} relevant hashtags, mix of broad and niche.

"pexels_query": 2-4 English words describing an aesthetic vertical stock video
background that fits (e.g. "dark server room", "abstract neon lines", "city night timelapse").

Return ONLY valid JSON with keys: topic, hook, slides, cta, caption, hashtags, pexels_query.
"""


def load_history() -> list:
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8") or "[]")
    return []


def save_history(history: list, entry: dict) -> None:
    history.append(entry)
    HISTORY_FILE.write_text(json.dumps(history[-300:], indent=2, ensure_ascii=False), encoding="utf-8")


def _call_gemini(prompt: str, cfg: dict) -> str:
    model = cfg["llm"]["gemini_model"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": cfg["llm"].get("temperature", 1.0),
            "responseMimeType": "application/json",
        },
    }
    r = requests.post(url, params={"key": env("GEMINI_API_KEY")}, json=body, timeout=90)
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _call_groq(prompt: str, cfg: dict) -> str:
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {env('GROQ_API_KEY')}"},
        json={
            "model": cfg["llm"]["groq_model"],
            "messages": [{"role": "user", "content": prompt}],
            "temperature": cfg["llm"].get("temperature", 1.0),
            "response_format": {"type": "json_object"},
        },
        timeout=90,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _parse(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    data = json.loads(raw)
    for key in ("topic", "hook", "slides", "caption", "hashtags"):
        if not data.get(key):
            raise ValueError(f"LLM response missing '{key}'")
    data["slides"] = [str(s) for s in data["slides"]][:5]
    data.setdefault("cta", "")
    data.setdefault("pexels_query", "abstract technology")
    return data


def generate_post(cfg: dict, history: list) -> dict:
    pillars = cfg["content_pillars"]
    pillar = pillars[len([h for h in history if h.get("status", "posted") == "posted"]) % len(pillars)]
    posted = [h for h in history if h.get("topic") and h.get("status", "posted") != "error"]
    recent = "\n".join(f"- {h['topic']}" for h in posted[-40:]) or "- (none yet)"
    b = cfg["brand"]
    prompt = PROMPT.format(
        name=b["name"], handle=b["handle"], description=b["description"].strip(),
        audience=b["audience"], tone=b["tone"], language=cfg.get("language", "English"),
        pillar=pillar, recent=recent, cta=b["call_to_action"],
        hashtags_count=cfg.get("hashtags_count", 8),
    )
    call = _call_groq if cfg["llm"]["provider"] == "groq" else _call_gemini

    last_err = None
    for attempt in range(4):
        try:
            data = _parse(call(prompt, cfg))
            data["pillar"] = pillar
            if not data["cta"]:
                data["cta"] = b["call_to_action"]
            return data
        except Exception as e:  # rate limits / bad JSON -> retry
            last_err = e
            print(f"[content] attempt {attempt + 1} failed: {e}")
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Could not generate content: {last_err}")


def build_caption(post: dict) -> str:
    tags = " ".join(t if t.startswith("#") else f"#{t}" for t in post["hashtags"])
    caption = post["caption"].replace("*", "").strip()
    return f"{caption}\n\n{tags}"[:2200]
