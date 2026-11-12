"""'Story' reels: a tiny animated cartoon story (like the explainer reels that make people watch to
the end). The LLM writes the story as beats from a fixed vocabulary of scenes; the 3D world
(renderer/scene/story.js) acts them out; this module adds the 2D layer:

  * one big word at a time, synced to the voice (key words in the brand colour)
  * a tracker bar that collects an icon for every beat (problem = red, fix = green)
  * live UI: incoming-message notifications, the AI chat answering on a phone, a stats card
  * whip-blur cuts, end card with Follow tap, and a seamless loop back to the first frame
"""
import asyncio
import json
import math
import random
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .audio import SR, build_soundtrack
from .glass import _blend, _paste_rgba
from .light import INK, WHITE, _mix, card, pick_light_palette, rounded, shadow, text
from .render import FONT_BOLD, FONT_MED, FONT_SEMI, ease_out_back, ease_out_cubic

W, H = 1080, 1920
SCENES = ["open", "first_customer", "rush", "phone_overload", "after_hours", "customers_leave",
          "owner_stressed", "fix", "booked", "happy", "outro"]
PROBLEM = {"rush", "phone_overload", "after_hours", "customers_leave", "owner_stressed"}
GOOD = {"fix", "booked", "happy"}
MIN_DUR = {"open": 2.4, "first_customer": 3.0, "rush": 3.4, "phone_overload": 3.4, "after_hours": 3.4,
           "customers_leave": 3.6, "owner_stressed": 2.8, "fix": 5.2, "booked": 4.2, "happy": 3.2, "outro": 3.6}
BUSINESSES = ["salon", "cafe", "clinic", "restaurant", "store", "gym"]

# ====================================================================== script (LLM)
STORY = """
Create ONE short animated STORY reel (cartoon characters in a little 3D town) about: "{pillar}".
It works like the best explainer reels: a tiny story the viewer can't stop watching. A small business owner
has a problem that gets worse beat by beat, then {name} fixes it, then a happy ending.

Pick a business that fits the topic: one of "salon" | "cafe" | "clinic" | "restaurant" | "store" | "gym".
Give it a short friendly name (max 14 characters, e.g. "Mia's Salon") and 3 services with prices.

beats: 7 to 9 items {{"scene": one of the scenes below, "line": what the narrator says, max 12 words}}.
Scenes you can use (the animation already shows them, the line tells the story):
- "open": the owner opens the business (MUST be first)
- "first_customer": the first happy customer comes in
- "rush": more and more customers arrive and wait
- "phone_overload": the phone keeps buzzing with messages nobody can answer
- "after_hours": night, the shop is closed, messages keep coming in unanswered
- "customers_leave": waiting customers get annoyed and walk out
- "owner_stressed": the owner is overwhelmed, the clock runs
- "fix": a customer at home messages the business and the {name} AI assistant answers instantly (MUST appear once, after the problem)
- "booked": the customer walks to the shop exactly on time
- "happy": the shop is full of happy customers
- "outro": the call to action (MUST be last)
Use 2-4 problem scenes, then "fix", then 1-2 of "booked"/"happy", then "outro".
Lines: simple spoken English, past tense storytelling, short words, concrete ("Messages piled up. Nobody answered."),
wrap 1-2 key words per line in *asterisks* (they show in colour). The fix line names {name} naturally.
The outro line is a call to action like "Want this for your business? Follow {name}."

hooks: 3 alternative FIRST lines (the "open" line) {{"text": max 10 words, "type": one of "question" | "bold_claim" |
"number" | "pain" | "curiosity" | "myth", "spoken": same line said naturally}}; "best_hook": index 0-2.
messages: 4 short customer messages that arrive (max 6 words each, e.g. "Are you open Sunday?").
chat: 4 items {{"from": "customer" | "ai", "text": max 9 words}} alternating customer, ai, customer, ai - the AI answers
and books/solves it. badge: max 5 words shown when it's solved (e.g. "Booked: Sat 5:00 PM").
stat: {{"label": max 4 words, "from": small number, "to": bigger number}} - an illustrative before/after
shown as a counter (e.g. bookings per week), keep it realistic.
cta: max 7 words. Caption: 3-5 short paragraphs telling the lesson, end with a question. Max 2 emojis.
hashtags: exactly {hashtags_count}.
Return ONLY JSON: {{"topic","business","business_name","services":[["name","price"],...],"hooks","best_hook","beats",
"messages","chat","badge","stat","cta","caption","hashtags"}}
"""


def _fix_beats(beats: list) -> list:
    out = [{"scene": b["scene"], "line": str(b.get("line", "")).strip()} for b in beats
           if isinstance(b, dict) and b.get("scene") in SCENES and str(b.get("line", "")).strip()]
    if not out:
        raise ValueError("no usable beats")
    seen, clean = set(), []
    for b in out:  # each scene once, keep order
        if b["scene"] not in seen:
            seen.add(b["scene"])
            clean.append(b)
    out = clean
    if out[0]["scene"] != "open":
        first = next((b for b in out if b["scene"] == "open"), None)
        if first:
            out.remove(first)
        out.insert(0, first or {"scene": "open", "line": "This is a small local business."})
    if not any(b["scene"] in PROBLEM for b in out):
        raise ValueError("story has no problem")
    if not any(b["scene"] == "fix" for b in out):
        raise ValueError("story has no fix")
    # problems before the fix, good endings after it, outro last
    fix = next(b for b in out if b["scene"] == "fix")
    outro = next((b for b in out if b["scene"] == "outro"), None)
    head = [b for b in out if b["scene"] in ("open", "first_customer")]
    probs = [b for b in out if b["scene"] in PROBLEM][:4]
    goods = [b for b in out if b["scene"] in ("booked", "happy")][:2] or [{"scene": "happy", "line": "Now the shop is always busy."}]
    out = head + probs + [fix] + goods + [outro or {"scene": "outro", "line": "Want this for your business? Follow us."}]
    return out[:10]


def generate_story(cfg: dict, history: list) -> dict:
    from .content import BRAND, _ctx, _need
    from .llm import generate
    ctx = _ctx(cfg, history, "reel")

    def check(o):
        _need(o, "topic", "beats", "caption", "hashtags")
        o["beats"] = _fix_beats(o["beats"])
        hooks = [h for h in (o.get("hooks") or []) if isinstance(h, dict) and h.get("text")]
        if hooks:
            from .learning import choose_hook
            try:
                best = int(o.get("best_hook", 0))
            except (TypeError, ValueError):
                best = 0
            pick = hooks[choose_hook(hooks, best, random.Random())]
            o["beats"][0]["line"] = str(pick.get("spoken") or pick["text"])
            o["hook_type"], o["hook_options"] = pick.get("type", ""), [{"text": h["text"], "type": h.get("type")} for h in hooks]
        o["hook"] = o["beats"][0]["line"]
        o["business"] = o.get("business") if o.get("business") in BUSINESSES else "salon"
        o["business_name"] = str(o.get("business_name") or "Mia's Shop")[:16]
        sv = [s for s in (o.get("services") or []) if isinstance(s, (list, tuple)) and len(s) >= 2]
        o["services"] = [[str(a)[:11], str(b)[:6]] for a, b, *_ in sv][:3]
        o["messages"] = [str(m)[:40] for m in (o.get("messages") or []) if m][:4] or ["Are you open today?", "How much is it?", "Can I book for 5pm?"]
        chat = [c for c in (o.get("chat") or []) if isinstance(c, dict) and c.get("text")]
        o["chat"] = [{"from": "ai" if str(c.get("from")).lower() == "ai" else "customer", "text": str(c["text"])[:60]} for c in chat][:4] \
            or [{"from": "customer", "text": "Can I book for Saturday?"}, {"from": "ai", "text": "Sure! 5:00 PM is free. Booked ✓"}]
        o["badge"] = str(o.get("badge") or "Booked ✓")[:28]
        st = o.get("stat") if isinstance(o.get("stat"), dict) else {}
        try:
            a, b = int(st.get("from", 12)), int(st.get("to", 38))
        except (TypeError, ValueError):
            a, b = 12, 38
        o["stat"] = {"label": str(st.get("label") or "Bookings per week")[:26], "from": max(0, a), "to": max(a + 1, b)}
        o["cta"] = o.get("cta") or cfg["brand"]["call_to_action"]

    post = generate(BRAND.format(**ctx) + STORY.format(**ctx), cfg, validate=check)
    post["pillar"] = ctx["pillar"]
    return post


# ====================================================================== voice + timeline
def _clean(s):
    return " ".join(str(s or "").replace("*", "").split())


def make_story_voice(post: dict, cfg: dict, seed: int, work: Path, history: list | None = None) -> dict | None:
    if not (cfg.get("voice") or {}).get("enabled", True):
        return None
    try:
        from .voice import VOICES, _decode, _synth
    except ImportError:
        return None
    voices = (cfg.get("voice") or {}).get("voices") or VOICES
    last = next((h.get("voice") for h in reversed(history or []) if h.get("voice")), None)
    voice = random.Random(seed).choice([v for v in voices if v != last] or voices)
    rate = (cfg.get("voice") or {}).get("rate", "+6%")
    clips = []
    try:
        for i, b in enumerate(post["beats"]):
            mp3 = work / f"vo-beat{i}.mp3"
            words = asyncio.run(_synth(_clean(b["line"]), voice, mp3, rate))
            audio = _decode(mp3)
            if len(audio) < SR * 0.25:
                raise RuntimeError("empty audio")
            clips.append({"audio": audio, "dur": len(audio) / SR, "words": words})
    except Exception as e:  # noqa: BLE001 - voice is a bonus
        print(f"[voice] unavailable ({type(e).__name__}: {e}) -> story without voice")
        return None
    print(f"[voice] {voice}: {sum(c['dur'] for c in clips):.1f}s of speech")
    return {"voice": voice, "clips": clips}


LEAD = 0.12


def build_timeline(post: dict, vo: dict | None) -> dict:
    beats, t = [], 0.0
    for i, b in enumerate(post["beats"]):
        need = LEAD + vo["clips"][i]["dur"] + 0.3 if vo else 0.6 + len(_clean(b["line"]).split()) * 0.36
        d = round(max(MIN_DUR.get(b["scene"], 3.0), need), 2)
        beats.append({"scene": b["scene"], "start": round(t, 3), "dur": d})
        t += d
    return {"beats": beats, "total": round(t, 2)}


def word_track(post: dict, tl: dict, vo: dict | None):
    """[(t0, t1, word, beat_index, highlighted)] + mono voice track."""
    words, track = [], None
    if vo:
        track = np.zeros(int(tl["total"] * SR) + 1)
    for i, (b, tb) in enumerate(zip(post["beats"], tl["beats"])):
        hl = {w.strip(".,!?;:\"'").lower() for w in " ".join(str(b["line"]).split("*")[1::2]).split()}
        t0 = tb["start"] + LEAD
        if vo:
            c = vo["clips"][i]
            i0 = int(t0 * SR)
            a = c["audio"][: max(0, len(track) - i0)]
            track[i0:i0 + len(a)] += a
            ws = [(t0 + a0, t0 + a1, w) for a0, a1, w in c["words"]]
        else:
            toks = _clean(b["line"]).split()
            step = (tb["dur"] - 0.6) / max(1, len(toks))
            ws = [(t0 + k * step, t0 + (k + 1) * step, w) for k, w in enumerate(toks)]
        for w0, w1, w in ws:
            words.append((w0, w1, w, i, w.strip(".,!?;:\"'").lower() in hl))
    if track is not None:
        track = track / (np.max(np.abs(track)) or 1) * 0.92
    return words, track


def cues_for(tl: dict, post: dict) -> list:
    cues = [(0.1, "pop"), (0.35, "impact")]
    for b in tl["beats"][1:]:
        cues.append((b["start"] - 0.12, "whoosh"))
        cues.append((b["start"] + 0.05, "pop"))
    for b in tl["beats"]:
        s, d = b["start"], b["dur"]
        if b["scene"] == "rush":
            cues += [(s + 0.25 + i * min(0.5, (d - 1.2) / 6), "pop") for i in range(6)]
        if b["scene"] in ("phone_overload", "after_hours"):
            cues += [(s + 0.35 + i * 0.6, "alert") for i in range(min(4, len(post["messages"])))]
        if b["scene"] == "fix":
            cues += [(s + 0.5 + i * 0.95, "tick") for i in range(len(post["chat"]))] + [(s + d - 1.15, "chime")]
        if b["scene"] in ("happy", "booked"):
            cues.append((s + d * 0.5, "chime"))
        if b["scene"] == "outro":
            cues += [(s + 0.2, "riser"), (s + 1.7, "pop")]
    return [(max(0.0, t), n) for t, n in cues]


# ====================================================================== icons for the tracker
def _icon(kind: str, size: int, color) -> Image.Image:
    s = size
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = color + (255,)
    k = s / 100
    L = lambda pts: [(x * k, y * k) for x, y in pts]  # noqa: E731
    lw = max(3, int(8 * k))
    if kind == "open":  # storefront
        d.rectangle(L([(22, 44), (78, 80)]), outline=c, width=lw)
        d.polygon(L([(16, 44), (24, 24), (76, 24), (84, 44)]), fill=c)
        d.rectangle(L([(42, 58), (58, 80)]), fill=c)
    elif kind in ("first_customer", "booked"):  # person (+ check)
        d.ellipse(L([(38, 16), (62, 40)]), fill=c)
        d.rounded_rectangle(L([(28, 46), (72, 84)]), radius=int(16 * k), fill=c)
    elif kind in ("rush", "happy"):  # people
        for x0 in (14, 40, 66):
            d.ellipse(L([(x0 + 2, 22), (x0 + 20, 40)]), fill=c)
            d.rounded_rectangle(L([(x0 - 4, 46), (x0 + 26, 78)]), radius=int(12 * k), fill=c)
    elif kind == "phone_overload":
        d.rounded_rectangle(L([(32, 12), (68, 88)]), radius=int(10 * k), outline=c, width=lw)
        d.ellipse(L([(58, 6), (86, 34)]), fill=(230, 60, 60, 255))
    elif kind == "after_hours":  # moon
        d.ellipse(L([(20, 18), (80, 78)]), fill=c)
        d.ellipse(L([(36, 10), (92, 66)]), fill=(0, 0, 0, 0))
    elif kind == "customers_leave":  # door + arrow
        d.rectangle(L([(18, 16), (52, 84)]), outline=c, width=lw)
        d.line(L([(46, 50), (86, 50)]), fill=c, width=lw)
        d.polygon(L([(74, 36), (90, 50), (74, 64)]), fill=c)
    elif kind == "owner_stressed":  # clock
        d.ellipse(L([(16, 16), (84, 84)]), outline=c, width=lw)
        d.line(L([(50, 50), (50, 28)]), fill=c, width=lw)
        d.line(L([(50, 50), (66, 60)]), fill=c, width=lw)
    elif kind == "fix":  # chat bubble with sparkle
        d.rounded_rectangle(L([(12, 20), (78, 68)]), radius=int(16 * k), fill=c)
        d.polygon(L([(24, 64), (20, 84), (42, 66)]), fill=c)
        for x0 in (28, 44, 60):
            d.ellipse(L([(x0 - 5, 39), (x0 + 5, 49)]), fill=(0, 0, 0, 0))
        d.polygon(L([(86, 6), (90, 16), (100, 20), (90, 24), (86, 34), (82, 24), (72, 20), (82, 16)]), fill=c)
    else:  # outro: star
        pts = [(50 + 40 * math.cos(a), 50 + 40 * math.sin(a)) if j % 2 == 0 else (50 + 17 * math.cos(a), 50 + 17 * math.sin(a))
               for j, a in enumerate([-math.pi / 2 + j * math.pi / 5 for j in range(10)])]
        d.polygon(L(pts), fill=c)
    if kind == "booked":
        d.line(L([(56, 72), (68, 84), (92, 58)]), fill=(255, 255, 255, 255), width=lw)
    if kind == "happy":
        d.ellipse(L([(66, 4), (96, 34)]), fill=(232, 69, 90, 255))
    return im


def _wrap(t, font, max_w):
    words, lines, cur = str(t).split(), [], ""
    for w in words:
        nxt = (cur + " " + w).strip()
        if font.getlength(nxt) > max_w and cur:
            lines.append(cur)
            cur = w
        else:
            cur = nxt
    if cur:
        lines.append(cur)
    return lines


# ====================================================================== overlay
class StoryOverlay:
    def __init__(self, post, cfg, tl, pal, fps, words, first_frame=None):
        self.post, self.tl, self.fps, self.words = post, tl, fps, words
        rgb = pal["_rgb"]
        self.accent = tuple(rgb["accent"])
        self.red = (226, 72, 60)
        acc = (cfg.get("_account") or {}).get("assets") or {}
        from .account import local_logo, logo_png
        lb = acc.get("avatar_bytes") or local_logo()[0]
        self.logo = logo_png(lb, 220) if lb else None
        self.brand = cfg["brand"]["name"]
        self.handle = "@" + acc["username"] if acc.get("username") else cfg["brand"]["handle"]
        self.first = first_frame

        # caption font + cache
        self.cap_font = ImageFont.truetype(str(FONT_BOLD), 128)
        self._cap = {}

        # tracker slots (every beat but the outro)
        self.slots = [(i, b) for i, b in enumerate(tl["beats"]) if b["scene"] != "outro"]
        n = len(self.slots)
        self.slot = 84
        self.bar_w = n * self.slot + (n - 1) * 14 + 44
        self.bar, self.bar_m = card(self.bar_w, 112, 56, fill=(255, 255, 255, 232))
        self.icons = []
        for i, b in self.slots:
            sc = b["scene"]
            col = self.red if sc in PROBLEM else (self.accent if sc in GOOD else INK)
            disc = rounded(self.slot, self.slot, self.slot // 2, col + (255,))
            disc.alpha_composite(_icon(sc, int(self.slot * 0.62), WHITE), (int(self.slot * 0.19), int(self.slot * 0.19)))
            self.icons.append(disc)

        # notification cards
        tf, bf, sf = ImageFont.truetype(str(FONT_BOLD), 34), ImageFont.truetype(str(FONT_MED), 34), ImageFont.truetype(str(FONT_MED), 26)
        self.notes = []
        for m in post["messages"]:
            im, mm = card(W - 140, 128, 36)
            dd = ImageDraw.Draw(im)
            ic = rounded(80, 80, 22, self.accent + (255,))
            ic.alpha_composite(_icon("fix", 56, WHITE), (12, 12))
            im.alpha_composite(ic, (mm + 24, mm + 14))
            dd.text((mm + 128, mm + 14), "New message", font=tf, fill=INK + (255,))
            dd.text((W - 140 + mm - 90, mm + 20), "now", font=sf, fill=INK + (120,))
            dd.text((mm + 128, mm + 60), self._fit(m, bf, W - 140 - 170), font=bf, fill=INK + (170,))
            self.notes.append((im, mm))
        self.unans = {}

        # phone chat UI
        self._phone_static()

        # stat card
        self.stat_font = ImageFont.truetype(str(FONT_BOLD), 110)
        self.stat_lab = ImageFont.truetype(str(FONT_SEMI), 34)

        # end card
        ew, eh = W - 120, 560
        self.end, self.end_m = card(ew, eh, 60)
        if self.logo:
            self.end.alpha_composite(self.logo.resize((170, 170), Image.LANCZOS), (self.end_m + (ew - 170) // 2, self.end_m + 34))
        bfn = ImageFont.truetype(str(FONT_BOLD), 76)
        bt = text(self.brand, bfn, INK + (255,))
        self.end.alpha_composite(bt, (self.end_m + (ew - bt.width) // 2, self.end_m + 214))
        ct = text(post.get("cta") or "", ImageFont.truetype(str(FONT_MED), 36), INK + (150,))
        if ct.width > ew - 60:
            ct = ct.resize((ew - 60, int(ct.height * (ew - 60) / ct.width)), Image.LANCZOS)
        self.end.alpha_composite(ct, (self.end_m + (ew - ct.width) // 2, self.end_m + 312))
        bf2 = ImageFont.truetype(str(FONT_BOLD), 46)
        self.btn = rounded(470, 112, 56, self.accent + (255,))
        t1 = text("Follow  →", bf2, WHITE + (255,))
        self.btn.alpha_composite(t1, ((470 - t1.width) // 2, (112 - t1.height) // 2))
        self.btn2 = rounded(470, 112, 56, INK + (255,))
        t2 = text("Following ✓", bf2, WHITE + (255,))
        self.btn2.alpha_composite(t2, ((470 - t2.width) // 2, (112 - t2.height) // 2))
        hf = text(self.handle, ImageFont.truetype(str(FONT_SEMI), 32), INK + (130,))
        self.end_handle = hf

    @staticmethod
    def _fit(t, font, max_w):
        t = str(t)
        while font.getlength(t) > max_w and len(t) > 4:
            t = t[:-2].rstrip() + "…"
        return t.replace("……", "…")

    # ---------------------------------------------------------------- phone UI
    def _phone_static(self):
        pw, ph = 700, 1180
        self.pw, self.ph = pw, ph
        body = rounded(pw, ph, 96, (22, 22, 26, 255))
        scr = rounded(pw - 36, ph - 36, 80, (246, 244, 240, 255))
        body.alpha_composite(scr, (18, 18))
        d = ImageDraw.Draw(body)
        d.rounded_rectangle((pw // 2 - 90, 40, pw // 2 + 90, 92), radius=26, fill=(10, 10, 12, 255))  # island
        hdr = rounded(pw - 36, 190, 0, self.accent + (255,))
        mask = rounded(pw - 36, 260, 80, (255, 255, 255, 255)).crop((0, 0, pw - 36, 190)).getchannel("A")
        body.paste(hdr, (18, 18), mask)
        if self.logo:
            lg = self.logo.resize((86, 86), Image.LANCZOS)
            ring = rounded(96, 96, 48, (255, 255, 255, 255))
            body.alpha_composite(ring, (54, 104))
            body.alpha_composite(lg, (59, 109))
        d.text((170, 108), f"{self.brand} AI", font=ImageFont.truetype(str(FONT_BOLD), 40), fill=WHITE + (255,))
        d.text((170, 158), f"for {self.post['business_name']}", font=ImageFont.truetype(str(FONT_MED), 28), fill=WHITE + (210,))
        d.ellipse((pw - 160, 128, pw - 142, 146), fill=(120, 255, 170, 255))
        d.text((pw - 132, 118), "Live", font=ImageFont.truetype(str(FONT_SEMI), 30), fill=WHITE + (255,))
        d.text((60, 30), "9:41", font=ImageFont.truetype(str(FONT_SEMI), 30), fill=WHITE + (255,))
        self.phone_body = body
        bf = ImageFont.truetype(str(FONT_MED), 34)
        self.bubbles = []
        for c in self.post["chat"]:
            ai = c["from"] == "ai"
            lines = _wrap(c["text"], bf, pw - 240)
            bw = int(max(bf.getlength(x) for x in lines)) + 56
            bh = len(lines) * 44 + 34
            col = self.accent if ai else (228, 225, 219)
            b = rounded(bw, bh, 30, col + (255,))
            bd = ImageDraw.Draw(b)
            for k, ln in enumerate(lines):
                bd.text((28, 14 + k * 44), ln, font=bf, fill=(WHITE if ai else INK) + (255,))
            self.bubbles.append((b, ai))
        bfnt = ImageFont.truetype(str(FONT_BOLD), 38)
        bt = text("✓  " + self.post["badge"], bfnt, WHITE + (255,))
        self.badge = rounded(bt.width + 60, 92, 46, (22, 22, 26, 255))
        self.badge.alpha_composite(bt, (30, (92 - bt.height) // 2))
        self.dots = [rounded(18, 18, 9, (140, 140, 140, 255))]

    def _phone(self, f, lt, d):
        k_in = ease_out_cubic(lt / 0.55)
        k_out = ease_out_cubic((lt - (d - 0.35)) / 0.35)
        y = int(H - (H - 860) * k_in + 900 * k_out)
        ph = self.phone_body.copy()
        n = len(self.bubbles)
        span = max(0.8, (d - 1.9) / max(1, n))
        cy = 250
        for j, (b, ai) in enumerate(self.bubbles):
            t0 = 0.55 + j * span
            if ai:  # typing dots first
                if t0 - 0.45 <= lt < t0:
                    ty = rounded(120, 64, 32, (228, 225, 219, 255))
                    for q in range(3):
                        a = 0.45 + 0.55 * abs(math.sin((lt * 7) - q * 0.7))
                        ty.alpha_composite(rounded(16, 16, 8, (90, 90, 90, int(255 * a))), (24 + q * 28, 24))
                    ph.alpha_composite(ty, (44, cy))
            if lt < t0:
                break
            k = ease_out_back((lt - t0) / 0.32)
            bw, bh = b.size
            sb = b if k >= 0.999 else b.resize((max(1, int(bw * max(0.05, k))), max(1, int(bh * max(0.05, k)))))
            x = 44 if ai else self.pw - 44 - sb.width
            ph.alpha_composite(sb, (x, cy + (bh - sb.height) // 2))
            cy += bh + 22
        kb = ease_out_back((lt - (d - 1.15)) / 0.4)
        if kb > 0:
            bb = self.badge.resize((max(1, int(self.badge.width * min(1.15, kb))), max(1, int(self.badge.height * min(1.15, kb)))))
            ph.alpha_composite(bb, ((self.pw - bb.width) // 2, min(cy + 20, self.ph - 220)))
        sh, sm = shadow(self.pw, self.ph, 96, 40, 110)
        _paste_rgba(f, sh, (W - self.pw) // 2 - sm, y - sm + 20)
        _paste_rgba(f, ph, (W - self.pw) // 2, y)
        # ripple on the badge moment
        q = (lt - (d - 1.1)) / 0.8
        if 0 <= q < 1:
            self._ring(f, W // 2, y + min(cy + 66, self.ph - 174), q, 80, 360)

    def _ring(self, f, cx, cy, q, rmin, rmax, col=None, width=10):
        rad = int(rmin + (rmax - rmin) * ease_out_cubic(q))
        im = Image.new("RGBA", (rad * 2 + 20, rad * 2 + 20), (0, 0, 0, 0))
        ImageDraw.Draw(im).ellipse((10, 10, rad * 2 + 10, rad * 2 + 10), outline=(col or self.accent) + (int(230 * (1 - q)),),
                                   width=max(2, int(width * (1 - q))))
        _paste_rgba(f, im, cx - rad - 10, cy - rad - 10)

    # ---------------------------------------------------------------- pieces
    def _caption(self, f, t):
        cur = None
        for w in self.words:
            if w[0] - 0.03 <= t < w[1] + 0.12:
                cur = w
        if not cur:
            return
        word, hl = cur[2].strip(), cur[4]
        key = (word, hl)
        if key not in self._cap:
            col = self.accent if hl else WHITE
            font = self.cap_font
            size = 128
            while font.getlength(word) > W - 120 and size > 60:
                size -= 8
                font = ImageFont.truetype(str(FONT_BOLD), size)
            tw = int(font.getlength(word)) + 60
            asc, desc = font.getmetrics()
            im = Image.new("RGBA", (tw, asc + desc + 60), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            d.text((30, 30), word, font=font, fill=col + (255,), stroke_width=9, stroke_fill=(24, 24, 30, 255))
            sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
            sh.putalpha(im.getchannel("A").point(lambda a: int(a * 0.35)))
            from PIL import ImageFilter
            sh = sh.filter(ImageFilter.GaussianBlur(10))
            out = Image.new("RGBA", (im.width, im.height + 10), (0, 0, 0, 0))
            out.alpha_composite(sh, (0, 10))
            out.alpha_composite(im)
            self._cap[key] = out
        im = self._cap[key]
        k = ease_out_back((t - cur[0] + 0.03) / 0.16)
        s = 0.82 + 0.18 * min(1.08, k)
        if abs(s - 1) > 0.01:
            im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))))
        _paste_rgba(f, im, (W - im.width) // 2, 430 - im.height // 2, min(1.0, max(0.0, k * 1.5)))

    def _tracker(self, f, t, bi):
        x0 = (W - self.bar_w) // 2
        k_bar = ease_out_cubic(t / 0.4)
        _paste_rgba(f, self.bar, x0 - self.bar_m, 150 - self.bar_m - int((1 - k_bar) * 40), k_bar)
        for j, (i, b) in enumerate(self.slots):
            cx = x0 + 22 + j * (self.slot + 14)
            if t < b["start"]:
                ghost = rounded(self.slot, self.slot, self.slot // 2, INK + (18,))
                _paste_rgba(f, ghost, cx, 164, k_bar)
                continue
            k = ease_out_back((t - b["start"]) / 0.45)
            ic = self.icons[j]
            if k < 0.999:
                s = max(1, int(self.slot * min(1.25, k)))
                ic = ic.resize((s, s))
            _paste_rgba(f, ic, cx + (self.slot - ic.width) // 2, 164 + (self.slot - ic.height) // 2)
            if i == bi:
                self._ring(f, cx + self.slot // 2, 164 + self.slot // 2, ((t - b["start"]) % 1.2) / 1.2, 44, 70,
                           self.red if b["scene"] in PROBLEM else self.accent, 6)

    def _notes(self, f, lt, d, night):
        n = len(self.notes)
        for j, (im, m) in enumerate(self.notes):
            t0 = 0.35 + j * min(0.6, (d - 1.0) / n)
            k = ease_out_back((lt - t0) / 0.4)
            if k <= 0:
                continue
            y = 1250 + j * 150 - int((1 - min(1.0, k)) * 120)
            _paste_rgba(f, im, 70 - m, y - m, min(1.0, k) * (1 - ease_out_cubic((lt - (d - 0.3)) / 0.3)))
        if night:
            cnt = min(99, int(max(0, lt - 0.3) * 6) + 1)
            if cnt not in self.unans:
                tt = text(f"{cnt} unanswered", ImageFont.truetype(str(FONT_BOLD), 40), WHITE + (255,))
                pill = rounded(tt.width + 56, 76, 38, self.red + (255,))
                pill.alpha_composite(tt, (28, (76 - tt.height) // 2))
                self.unans[cnt] = pill
            p = self.unans[cnt]
            _paste_rgba(f, p, (W - p.width) // 2, 1110, ease_out_cubic(lt / 0.4))

    def _stat(self, f, lt, d):
        st = self.post["stat"]
        k = ease_out_back((lt - 0.2) / 0.5)
        if k <= 0:
            return
        cw, ch = W - 140, 300
        im, m = card(cw, ch, 48)
        dd = ImageDraw.Draw(im)
        dd.text((m + 50, m + 34), st["label"].upper(), font=self.stat_lab, fill=INK + (140,))
        q = ease_out_cubic((lt - 0.5) / max(0.8, d - 1.4))
        val = int(round(st["from"] + (st["to"] - st["from"] * 1.0) * q))
        dd.text((m + 46, m + 80), str(val), font=self.stat_font, fill=INK + (255,))
        pct = int(round((st["to"] - st["from"]) / max(1, st["from"]) * 100 * q))
        chip = rounded(190, 64, 32, self.accent + (255,))
        ct = text(f"▲ {pct}%", ImageFont.truetype(str(FONT_BOLD), 34), WHITE + (255,))
        chip.alpha_composite(ct, ((190 - ct.width) // 2, (64 - ct.height) // 2))
        im.alpha_composite(chip, (m + 50, m + 210))
        for b in range(6):  # bars growing
            hb = int((40 + b * 26) * min(1.0, q * 1.3 - b * 0.08 if q * 1.3 - b * 0.08 > 0 else 0))
            if hb > 0:
                col = self.accent if b == 5 else _mix(self.accent, WHITE, 0.55)
                dd.rounded_rectangle((m + cw - 360 + b * 52, m + 250 - hb, m + cw - 324 + b * 52, m + 250), radius=10, fill=col + (255,))
        y = 1300 + int((1 - min(1.0, k)) * 200)
        _paste_rgba(f, im, 70 - m, y - m, min(1.0, k))

    def _end(self, f, lt, d):
        k = ease_out_back((lt - 0.15) / 0.6)
        if k <= 0:
            return
        y = 1180 + int((1 - min(1.0, k)) * 700)
        _paste_rgba(f, self.end, 60 - self.end_m, y - self.end_m)
        tapped = lt > 1.75
        press = 6 if 1.55 < lt < 1.8 else 0
        bx, by = (W - 470) // 2, y + 400 + press
        _paste_rgba(f, self.btn2 if tapped else self.btn, bx, by)
        _paste_rgba(f, self.end_handle, (W - self.end_handle.width) // 2, y + 520 - 6)
        q = (lt - 1.55) / 0.7
        if 0 <= q < 1:
            self._ring(f, bx + 330, by + 56, q, 20, 130, INK, 6)

    # ---------------------------------------------------------------- frame
    def compose_raw(self, i, frame_path):
        img = Image.open(frame_path).transpose(Image.FLIP_TOP_BOTTOM)
        if img.size != (W, H):
            img = img.resize((W, H), Image.BICUBIC)
        t = i / self.fps
        beats = self.tl["beats"]
        bi = next((k for k, b in enumerate(beats) if b["start"] <= t < b["start"] + b["dur"]), len(beats) - 1)
        b = beats[bi]
        lt, d = t - b["start"], b["dur"]
        f = np.asarray(img).copy()
        # whip blur + punch around cuts
        for nb in beats[1:]:
            q = t - nb["start"]
            if -0.09 <= q < 0.09:
                amt = 1 - abs(q) / 0.09
                sh = int(30 * amt)
                if sh > 1:
                    acc = sum(np.roll(f, int(o), axis=1).astype(np.float32) for o in np.linspace(-sh, sh, 7)) / 7
                    f = acc.clip(0, 255).astype(np.uint8)
                break
        sc = b["scene"]
        self._tracker(f, t, bi)
        if sc in ("phone_overload", "after_hours"):
            self._notes(f, lt, d, sc == "after_hours")
        if sc == "fix":
            self._phone(f, lt, d)
        if sc == "happy":
            self._stat(f, lt, d)
        if sc == "outro":
            self._end(f, lt, d)
        if sc != "outro" or lt < 1.0:
            self._caption(f, t)
        return f

    def compose(self, i, frame_path):
        f = self.compose_raw(i, frame_path)
        total = self.tl["total"]
        t = i / self.fps
        q = (t - (total - 0.45)) / 0.45
        if q > 0 and self.first is not None:  # seamless loop into the first frame
            k = ease_out_cubic(q)
            f = (f.astype(np.float32) * (1 - k) + self.first.astype(np.float32) * k).astype(np.uint8)
        return f.tobytes()


_O = None


def _init(*args):
    global _O
    _O = StoryOverlay(*args)


def _work(args):
    i, path = args
    return _O.compose(i, Path(path))


def render_story_reel(post: dict, cfg: dict, out: Path, work: Path, seed: int, vo: dict | None = None) -> Path:
    import os
    import subprocess
    from multiprocessing import get_context
    from .cinematic import run_renderer
    from .ff import FFMPEG
    fps = int(cfg["video"].get("fps_cinematic", 24))
    rng = random.Random(seed)
    pal_name, pal = pick_light_palette(cfg, rng)
    tl = build_timeline(post, vo)
    post["_plan"] = {"style": "story", "theme": "light", "palette": pal_name, "business": post["business"]}
    job = {"mode": "reel", "page": "story", "width": W, "height": H, "fps": fps, "seed": seed,
           "render_scale": cfg["video"].get("render_scale", 0.6667),
           "palette": {k: v for k, v in pal.items() if not k.startswith("_")},
           "story": {"business": post["business"], "business_name": post["business_name"], "services": post["services"],
                     "beats": tl["beats"], "total": tl["total"]}}
    print(f"[story] {post['business']} '{post['business_name']}', palette {pal_name}, {tl['total']:.1f}s, "
          f"beats {[b['scene'] for b in tl['beats']]}")
    rdir = work / "3d"
    run_renderer(job, rdir)
    frames = sorted((rdir / "frames").glob("*.jpg"))
    words, voice = word_track(post, tl, vo)
    total = round(len(frames) / fps, 3)
    audio = build_soundtrack(total, cues_for(tl, post), cfg, work / "audio.wav", seed=seed, style="classic", voice=voice)
    first = StoryOverlay(post, cfg, tl, pal, fps, words).compose_raw(0, frames[0])
    cmd = [FFMPEG, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "pipe:0",
           "-i", str(audio), "-map", "0:v", "-map", "1:a", "-shortest", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-maxrate", "10M", "-bufsize", "20M", "-pix_fmt", "yuv420p", "-profile:v", "high", "-c:a", "aac", "-b:a", "192k",
           "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    procs = max(1, min(os.cpu_count() or 2, 6))
    try:
        with get_context("fork").Pool(procs, initializer=_init, initargs=(post, cfg, tl, pal, fps, words, first)) as pool:
            for k, buf in enumerate(pool.imap(_work, [(i, str(p)) for i, p in enumerate(frames)], chunksize=4)):
                proc.stdin.write(buf)
                if k % 120 == 0:
                    print(f"[story] composited {k}/{len(frames)}")
    finally:
        proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed while encoding the story reel")
    shutil.rmtree(rdir / "frames", ignore_errors=True)
    print(f"[story] saved {out}")
    return out


if __name__ == "__main__":  # quick local check: python -m autoposter.story sample.json out.mp4
    import sys
    import tempfile
    from .config import load_config
    cfg = load_config()
    post = json.loads(Path(sys.argv[1]).read_text())
    post["beats"] = _fix_beats(post["beats"])
    w = Path(tempfile.mkdtemp())
    vo = make_story_voice(post, cfg, 1, w) if "--voice" in sys.argv else None
    render_story_reel(post, cfg, Path(sys.argv[2]), w, 7, vo)
