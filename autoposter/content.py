"""Writes the posts with the LLM: cinematic reels, carousels and stories.

Token budget: one short request per post (prompt ~600 tokens, answer ~500).
8 reels + 1 carousel + 2 stories a day is ~11 requests/day, far below the
Gemini free limits; comment replies use the cheaper Flash-Lite model.
"""
import json

from .config import DATA
from .llm import generate

HISTORY_FILE = DATA / "history.json"

BRAND = """You are the social media lead for {name} ({handle}).
About the brand: {description}
Instagram bio: {bio}
Audience: {audience}
Tone: {tone}
Language: {language}. Content must be accurate and genuinely useful. Never invent statistics,
studies, clients or quotes; use clearly illustrative wording ("e.g.", "up to", "hours") instead.

STYLE GUIDE learned from this account's own reels and carousels (follow it, it is what works for them):
{guide}

Make it crystal clear for EVERYONE, not only tech people: simple everyday words, no jargon
(if a tool name is needed, say what it does), one idea per line, a concrete benefit the viewer feels
(time, money, customers, stress). High impact: bold contrast, curiosity, a real "aha".

Do not repeat or closely resemble these recent topics (ours and already on the account):
{recent}
"""

REEL = BRAND + """
Create ONE cinematic Instagram Reel script about: "{pillar}".
Story structure: HOOK -> THE PROBLEM -> THE FIX (exactly 3 steps) -> THE RESULT -> CTA.
On-screen text rules (short, punchy; wrap 1-2 key words in *asterisks* to highlight):
- hook: max 8 words, scroll-stopping.
- problem.text: max 14 words, the pain the viewer recognises.
- problem.alerts: 3 notification texts shown on a phone/laptop screen, max 4 words each (e.g. "Report overdue").
- solution.steps: 3 items {{"title": max 4 words, "text": max 8 words}}.
- result: max 10 words, the outcome.
- app_name: 1-2 word generic tool name shown on the laptop screen (not a real brand).
- cta: max 7 words (e.g. "{cta}").
Caption: 3-5 short paragraphs, first line is a hook, add value beyond the video, end with a question.
Max 2 emojis. hashtags: exactly {hashtags_count} relevant hashtags.
Return ONLY JSON: {{"topic","hook","problem":{{"text","alerts"}},"solution":{{"steps"}},"result","app_name","cta","caption","hashtags"}}
"""

CAROUSEL = BRAND + """
Create ONE Instagram carousel (swipeable slides) about: "{pillar}".
- title: max 7 words, the cover headline (wrap 1-2 words in *asterisks* to highlight).
- subtitle: max 10 words.
- slides: exactly 5 items {{"title": max 6 words, "body": max 26 words}} - one concrete, actionable idea each.
- cta: max 7 words.
Caption: 2-4 short paragraphs ending with a question. Max 2 emojis. hashtags: exactly {hashtags_count}.
Return ONLY JSON: {{"topic","title","subtitle","slides","cta","caption","hashtags"}}
"""

STORIES = BRAND + """
Create {n} Instagram stories (single full-screen images with text) for today. Mix these kinds:
"tip" (one quick actionable tip), "question" (a question to the audience), "fact" (a surprising but TRUE tech fact).
Each: {{"kind", "title": max 6 words, "body": max 20 words}}.
Return ONLY JSON: {{"stories": [...]}}
"""


def load_history() -> list:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8") or "[]")
        except ValueError:
            return []
    return []


def save_history(history: list, entry: dict) -> None:
    history.append(entry)
    HISTORY_FILE.write_text(json.dumps(history[-300:], indent=2, ensure_ascii=False), encoding="utf-8")


def _ctx(cfg: dict, history: list, kind: str) -> dict:
    pillars = cfg["content_pillars"]
    done = [h for h in history if h.get("status") == "posted" and h.get("type", "reel") == kind]
    pillar = pillars[(len(done) + {"reel": 0, "carousel": 3, "story": 5}.get(kind, 0)) % len(pillars)]
    recent = [h["topic"] for h in history if h.get("topic") and h.get("status") != "error"][-30:]
    acc = cfg.get("_account") or {}
    recent += acc.get("ig_recent", [])[:15]
    guide = acc.get("guide") or {}
    b = cfg["brand"]
    return {
        "bio": acc.get("bio") or "(not available)",
        "guide": json.dumps(guide, ensure_ascii=False)[:2500] if guide else "(no posts analysed yet - use the brand info)",
        "name": b["name"], "handle": b["handle"], "description": b["description"].strip(),
        "audience": b["audience"], "tone": b["tone"], "language": cfg.get("language", "English"),
        "recent": "\n".join(f"- {r}" for r in recent) or "- (none yet)", "pillar": pillar,
        "cta": b["call_to_action"], "hashtags_count": cfg.get("hashtags_count", 8),
    }


def _need(obj, *keys):
    for k in keys:
        if not obj.get(k):
            raise ValueError(f"missing '{k}'")


def generate_reel(cfg: dict, history: list) -> dict:
    ctx = _ctx(cfg, history, "reel")

    def check(o):
        _need(o, "topic", "hook", "problem", "solution", "result", "caption", "hashtags")
        steps = o["solution"].get("steps") or []
        if len(steps) < 3 or not all(s.get("title") for s in steps):
            raise ValueError("need 3 steps")
        o["solution"]["steps"] = [{"title": str(s["title"]), "text": str(s.get("text", ""))} for s in steps[:3]]
        o["problem"]["alerts"] = [str(a) for a in (o["problem"].get("alerts") or [])][:3]
        o.setdefault("app_name", "Workspace")
        o["cta"] = o.get("cta") or cfg["brand"]["call_to_action"]

    post = generate(REEL.format(**ctx), cfg, validate=check)
    post["pillar"] = ctx["pillar"]
    return post


def generate_carousel(cfg: dict, history: list) -> dict:
    ctx = _ctx(cfg, history, "carousel")

    def check(o):
        _need(o, "topic", "title", "slides", "caption", "hashtags")
        if len(o["slides"]) < 3:
            raise ValueError("need slides")
        o["slides"] = [{"title": str(s.get("title", "")), "body": str(s.get("body", ""))} for s in o["slides"][:7]]
        o["cta"] = o.get("cta") or cfg["brand"]["call_to_action"]

    post = generate(CAROUSEL.format(**ctx), cfg, validate=check)
    post["pillar"] = ctx["pillar"]
    return post


def generate_stories(cfg: dict, history: list, n: int) -> list:
    ctx = _ctx(cfg, history, "story")

    def check(o):
        if not isinstance(o.get("stories"), list) or not o["stories"]:
            raise ValueError("no stories")

    out = generate(STORIES.format(n=n, **ctx), cfg, validate=check)
    return [{"kind": s.get("kind", "tip"), "title": str(s.get("title", "")), "body": str(s.get("body", ""))}
            for s in out["stories"][:n]]


def build_caption(post: dict) -> str:
    tags = " ".join(t if str(t).startswith("#") else f"#{t}" for t in post.get("hashtags", []))
    caption = str(post.get("caption", "")).replace("*", "").strip()
    return f"{caption}\n\n{tags}".strip()[:2200]
