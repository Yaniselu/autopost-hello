"""'Story' reels v2: short animated films in a little cartoon 3D town, directed by the LLM.

Every reel gets a different STORY TYPE (time travel to 1995, a day in someone's life, two rival
shops, the customer's side, a disaster at the worst moment, a secret revealed, myth vs reality,
3 mistakes, flash-forward...) and the LLM writes it as SHOTS: place (shop, home, office, warehouse,
park, street, an abstract studio), era (today or the past, in sepia), time of day, camera, a cast
of named characters who walk, sit, type, call, talk (speech bubbles), think, celebrate, panic...,
props (paper piles, money rain, confetti, rain clouds, light bulbs...) and an on-screen UI moment.

The 3D world (renderer/scene/story.js) plays the shots; this module adds the 2D layer:
one big word at a time synced to the voice, an icon tracker, title cards ("1995", "3 months later"),
notifications, a live AI chat on a phone, before/after comparison, checklist, timer, stats,
time-travel / whip / dip transitions, sepia for the past, an end card and a seamless loop.
"""
import asyncio
import json
import math
import random
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .audio import SR, build_soundtrack
from .glass import _paste_rgba
from .light import INK, WHITE, _mix, card, pick_light_palette, rounded, shadow, text
from .render import FONT_BOLD, FONT_MED, FONT_SEMI, ease_out_back, ease_out_cubic

W, H = 1080, 1920
BUSINESSES = ["salon", "cafe", "clinic", "restaurant", "store", "gym", "bakery", "agency"]
SLOTS = {
    "shop": ["service", "staff", "couch1", "couch2", "couch3", "couch4", "queue1", "queue2", "center", "door"],
    "home": ["couch", "couch2", "center", "window", "door"],
    "office": ["desk1", "desk2", "boss", "whiteboard", "center", "door"],
    "warehouse": ["packing", "shelf", "boxes", "center", "door"],
    "park": ["bench1", "bench2", "path_left", "path_right", "fountain", "center", "door"],
    "stage": ["left", "center", "right", "door"],
    "street": [],
}
LANDMARKS = ["park", "shop", "home", "office", "warehouse"]
DOS = ["stand", "sit", "type", "phone", "call", "talk", "work", "serve", "wave", "point", "carry", "celebrate", "facepalm",
       "sleep", "shrug", "panic", "walk_in", "run_in", "walk_out", "storm_out", "walk_to", "walk", "run"]
EMOS = ["neutral", "happy", "excited", "proud", "sad", "stressed", "tired", "angry", "surprised", "confused"]
BUBBLES = ["?", "!", "zzz", "$", "check", "heart", "angry", "msg", "idea", "clock", "sweat"]
PROPS = ["papers_pile", "boxes_pile", "money_rain", "confetti", "lightbulb", "sparkles", "rain_cloud", "msg_bubbles", "clock_fast"]
STAGE_PROPS = ["big_phone", "big_laptop", "coins", "big_clock"]
UIS = ["none", "notifications", "chat", "stat", "compare", "checklist", "timer", "title"]
TRANSITIONS = ["cut", "time_travel", "later", "zoom"]
ICONS = ["store", "person", "people", "phone", "moon", "exit", "clock", "chat", "check", "heart", "star", "money", "box",
         "laptop", "mail", "calendar", "bolt", "rocket", "warning", "hourglass", "idea", "home", "chart"]
COLORS = ["red", "blue", "green", "yellow", "orange", "purple", "pink", "teal", "black", "white", "gray", "navy", "brown"]
HAIR = ["short", "curly", "bun", "long", "bald"]

ARCHETYPES = {
    "time_travel": "Open in the PAST (era \"past\", around 1995, shown in sepia): how this job used to be done - paper, fax, "
                   "landline calls, piles of forms, waiting. Then a shot with transition \"time_travel\" jumps to TODAY "
                   "(era \"now\") where the same thing happens instantly thanks to {name}. Use a \"title\" UI for the years "
                   "and a \"compare\" UI (then vs now).",
    "day_in_life": "Follow ONE person through ONE day from morning to night across at least 4 places (home -> street -> "
                   "work -> park/street -> home...). Small problems pile up hour by hour (use time sunset/night later on). "
                   "The turning point is {name}; the next day is calm.",
    "rivals": "Two neighbours run similar businesses on the same street. One does everything the old way, the other uses "
              "{name}. Cut between them shot by shot so the difference is obvious; use \"compare\" or \"stat\" UI; "
              "end with the old-way neighbour walking over to ask how.",
    "customer_pov": "Tell it from a CUSTOMER's side: they try to buy / book / get an answer and hit wall after wall "
                    "(no reply, closed, on hold, lost message) in different places. Then they find a business that answers "
                    "instantly thanks to {name}. Use \"notifications\" and \"chat\" UI.",
    "disaster": "Everything goes wrong at the worst possible moment (a huge order, a viral post, a holiday rush, the owner "
                "is sick): chaos, piles of work, panic, angry customers. A rescue with {name} turns it around; end with "
                "a \"timer\" or \"stat\" UI and a celebration.",
    "secret": "Start with a mystery hook: why is this business always full / always calm? A curious competitor or friend "
              "investigates (walks there on the street, peeks in, asks). The secret is revealed: {name}. Use a "
              "\"checklist\" UI of what it does.",
    "myth_bust": "Myth vs reality. Use the abstract \"stage\" set (with big props) for 2-3 explainer shots, mixed with "
                 "short real-life scenes in DIFFERENT places that show the myth and then the reality with {name}. "
                 "Use \"title\" UI (\"MYTH\" / \"REALITY\") and a \"checklist\".",
    "countdown": "3 mistakes small businesses make. Each mistake is a mini-scene in a DIFFERENT place, introduced by a "
                 "\"title\" UI (\"Mistake #1\" ...). Then the fix with {name} and a \"checklist\".",
    "flash_forward": "Start at a happy moment in the future (a celebration, confetti). Then transition \"later\" with a "
                     "\"title\" UI like \"6 months earlier...\" showing how bad things were, step by step, and how "
                     "{name} changed it, ending back at the celebration.",
}

# ====================================================================== script (LLM)
STORY = """
Write ONE short animated FILM for an Instagram Reel (cartoon characters in a little 3D town) about: "{pillar}".
It must feel like a real mini-movie people watch to the end: a clear character, a situation that escalates,
a turning point, a payoff. {name} is the turning point, shown naturally (not an ad read).

STORY TYPE for this reel (follow it): {archetype_name} - {archetype}
Do NOT reuse these recent story types/places/names: {avoid}

THE TOWN (what the animation can show - use ONLY these words):
- sets and their spots ("at"):
  shop (a {business}, name it): service, staff, couch1..couch4, queue1, queue2, center, door
  home: couch, couch2, center, window, door
  office: desk1, desk2, boss, whiteboard, center, door
  warehouse: packing, shelf, boxes, center, door
  park: bench1, bench2, path_left, path_right, fountain, center, door
  stage (abstract studio to explain an idea, with big props big_phone | big_laptop | coins | big_clock): left, center, right
  street (people walking between places): instead of "at" use "from" and "to", each one of park|shop|home|office|warehouse
- do: stand, sit, type, phone, call, talk, work, serve, wave, point, carry, celebrate, facepalm, sleep, shrug, panic,
  walk_in (enters from outside to "at"), run_in, walk_out, storm_out, walk_to (+ "to": another spot); on street: walk, run, carry, phone
- emo: neutral, happy, excited, proud, sad, stressed, tired, angry, surprised, confused
- icon above a head (optional): ?, !, zzz, $, check, heart, angry, msg, idea, clock, sweat
- say: a short line in a SPEECH bubble (max 5 words) / think: a THOUGHT bubble (max 5 words) - use them, they make it alive
- props: papers_pile, boxes_pile, money_rain, confetti, lightbulb, sparkles, rain_cloud, msg_bubbles, clock_fast (+ stage props on stage)
- crowd (extra people): {{"n": 0-6, "emo": ..., "do": stand|arrive|leave|celebrate|phone|talk}}
- era: now | past (around 1995: paper, fax, landline phones, CRT screens - shown in sepia). time: day | sunset | night
- camera: wide (whole building) | medium (the room) | close (one character) | track (follows someone walking)
- transition INTO the shot: cut | time_travel (jump between eras) | later (time skip) | zoom
- ui (one on-screen moment per shot, or none):
  {{"type":"title","text":"1995","sub":"optional"}} | {{"type":"notifications","items":["max 6 words",...]}} |
  {{"type":"chat","messages":[{{"from":"customer"|"ai","text":"max 9 words"}},...],"badge":"max 5 words"}} |
  {{"type":"compare","left_title":"1995","left":["max 4 words",...],"right_title":"Today","right":["max 4 words",...]}} |
  {{"type":"checklist","title":"max 4 words","items":["max 5 words",...]}} | {{"type":"timer","label":"max 3 words","from":"4 hours","to":"30 sec"}} |
  {{"type":"stat","label":"max 4 words","from":12,"to":40}} | {{"type":"none"}}
- tracker icon per shot: one of {icons}; mood per shot: bad | good | neutral

RULES:
- cast: 2-4 characters {{"id":"lowercase name","name":"Name","role":"who they are","look":{{"shirt": one of {colors},
  "hair": short|curly|bun|long|bald, "skin": 0-5, "extra": none|glasses|tie|apron|cap, "beard": true|false}}}}. Fresh names every time.
- shots: 7 to 10. Use at least 3 DIFFERENT sets. Each shot: {{"set","era","time","camera","transition","focus": a cast id,
  "line": what the narrator says (max 13 words, spoken English, wrap 1-2 key words in *asterisks*), "icon","mood",
  "cast":[{{"who","at" (or "from"/"to" on street),"do","emo","say"?,"think"?,"icon"?,"to"?}}],"crowd"?,"props"?,"ui"?}}
- The FIRST line is the hook (curiosity, a bold statement or a question). The LAST shot is the call to action
  (e.g. "Want this for your business? Follow {name}.") - put the hero happy there.
- Show, don't tell: speech bubbles, emotions, props and UI carry the story; narration is short.
- Accurate and honest: no fake statistics, no real company names; numbers are clearly illustrative.

Also: hooks: 3 alternative FIRST lines {{"text": max 12 words, "type": question|bold_claim|number|pain|curiosity|myth,
"spoken": same line said naturally}}; "best_hook": 0-2. business_name (max 14 chars), services (3 ["name","$price"]),
office_name and warehouse_name (max 12 chars, invented). cta: max 7 words. Caption: 3-5 short paragraphs with the lesson,
end with a question, max 2 emojis. hashtags: exactly {hashtags_count}.
Return ONLY JSON: {{"topic","story_type","business","business_name","services","office_name","warehouse_name","cast","shots",
"hooks","best_hook","cta","caption","hashtags"}}
"""


def _pick(v, allowed, default):
    return v if v in allowed else default


def _short(s, n):
    return " ".join(str(s or "").replace("\n", " ").split())[:n]


def normalize(o: dict, allowed_biz: list, suggest_biz: str) -> dict:
    """Cleans whatever the LLM returned into something the renderer can always play."""
    o["business"] = _pick(o.get("business"), allowed_biz, suggest_biz)
    o["business_name"] = _short(o.get("business_name") or "Corner Shop", 16)
    o["office_name"] = _short(o.get("office_name") or "Brightline", 14)
    o["warehouse_name"] = _short(o.get("warehouse_name") or "FastBox", 14)
    sv = [s for s in (o.get("services") or []) if isinstance(s, (list, tuple)) and len(s) >= 2]
    o["services"] = [[_short(a, 11), _short(b, 6)] for a, b, *_ in sv][:3]
    # cast
    cast, seen = [], set()
    for c in (o.get("cast") or [])[:4]:
        if not isinstance(c, dict):
            continue
        cid = "".join(ch for ch in str(c.get("id") or c.get("name") or "").lower() if ch.isalnum())[:12] or f"c{len(cast)}"
        if cid in seen:
            continue
        seen.add(cid)
        lk = c.get("look") if isinstance(c.get("look"), dict) else {}
        try:
            skin = int(lk.get("skin", len(cast) * 2)) % 6
        except (TypeError, ValueError):
            skin = len(cast) % 6
        cast.append({"id": cid, "name": _short(c.get("name") or cid.title(), 14), "role": _short(c.get("role"), 40),
                     "look": {"shirt": _pick(lk.get("shirt"), COLORS, COLORS[len(cast) * 3 % len(COLORS)]),
                              "hair": _pick(lk.get("hair"), HAIR, HAIR[len(cast) % 4]), "skin": skin,
                              "extra": _pick(lk.get("extra"), ["none", "glasses", "tie", "apron", "cap"], "none"),
                              "beard": bool(lk.get("beard", False))}})
    if not cast:
        cast = [{"id": "sam", "name": "Sam", "role": "owner", "look": {"shirt": "orange", "hair": "curly", "skin": 2, "extra": "none", "beard": False}}]
    ids = [c["id"] for c in cast]
    alnum = lambda x: "".join(ch for ch in str(x or "").lower() if ch.isalnum())  # noqa: E731
    names = {alnum(c["name"]): c["id"] for c in cast}
    # shots
    shots = []
    for s in (o.get("shots") or [])[:11]:
        if not isinstance(s, dict) or not _short(s.get("line"), 200):
            continue
        st = _pick(s.get("set"), list(SLOTS), "shop")
        slots = SLOTS[st]
        sh = {"set": st, "era": _pick(s.get("era"), ["now", "past"], "now"), "time": _pick(s.get("time"), ["day", "sunset", "night"], "day"),
              "camera": _pick(s.get("camera"), ["wide", "medium", "close", "track"], "medium"),
              "transition": _pick(s.get("transition"), TRANSITIONS, "cut"), "line": _short(s.get("line"), 160),
              "icon": _pick(s.get("icon"), ICONS, "star"), "mood": _pick(s.get("mood"), ["bad", "good", "neutral"], "neutral")}
        if st == "stage":
            sh["era"], sh["time"] = "now", "day"
        rows = []
        for r in (s.get("cast") or [])[:4]:
            if not isinstance(r, dict):
                continue
            who = alnum(r.get("who"))[:12]
            who = who if who in ids else names.get(who, None)
            if not who or any(x["who"] == who for x in rows):
                continue
            row = {"who": who, "do": _pick(r.get("do"), DOS, "stand"), "emo": _pick(r.get("emo"), EMOS, "neutral")}
            if st == "street":
                row["from"] = _pick(r.get("from"), LANDMARKS, "home")
                row["to"] = _pick(r.get("to"), LANDMARKS, "shop")
                if row["to"] == row["from"]:
                    row["to"] = "shop" if row["from"] != "shop" else "office"
                row["do"] = row["do"] if row["do"] in ("walk", "run", "carry", "phone") else "walk"
            else:
                row["at"] = _pick(r.get("at"), slots, slots[len(rows) % len(slots)])
                if row["do"] == "walk_to":
                    row["to"] = _pick(r.get("to"), slots, "center")
                if row["do"] in ("walk", "run"):
                    row["do"] = "walk_in" if row["do"] == "walk" else "run_in"
            if r.get("say"):
                row["say"] = _short(str(r["say"]).replace("*", ""), 34)
            elif r.get("think"):
                row["think"] = _short(str(r["think"]).replace("*", ""), 34)
            if r.get("icon") in BUBBLES:
                row["icon"] = r["icon"]
            rows.append(row)
        # two characters on the same spot: move the second one
        used = set()
        for row in rows:
            if "at" in row:
                if row["at"] in used:
                    free = [x for x in slots if x not in used and x != "door"]
                    row["at"] = free[0] if free else row["at"]
                used.add(row["at"])
        sh["cast"] = rows
        sh["focus"] = s.get("focus") if s.get("focus") in [r["who"] for r in rows] else (rows[0]["who"] if rows else None)
        cr = s.get("crowd") if isinstance(s.get("crowd"), dict) else {}
        try:
            n = max(0, min(6, int(cr.get("n", 0))))
        except (TypeError, ValueError):
            n = 0
        if n:
            sh["crowd"] = {"n": n, "emo": _pick(cr.get("emo"), EMOS, "neutral"),
                           "do": _pick(cr.get("do"), ["stand", "arrive", "leave", "celebrate", "phone", "talk"], "stand")}
        props = [p for p in (s.get("props") or []) if p in PROPS or (st == "stage" and p in STAGE_PROPS)]
        if st == "stage" and not any(p in STAGE_PROPS for p in props):
            props.append(random.choice(STAGE_PROPS))
        sh["props"] = props[:3]
        sh["ui"] = _ui(s.get("ui"))
        shots.append(sh)
    if len(shots) < 4:
        raise ValueError("story has too few usable shots")
    if len({s["set"] for s in shots}) < 2:
        raise ValueError("story uses only one place")
    shots[-1]["ui"] = {"type": "endcard"}
    shots[-1]["mood"] = "good"
    o["cast"], o["shots"] = cast, shots
    return o


def _ui(u):
    if not isinstance(u, dict) or u.get("type") not in UIS or u.get("type") == "none":
        return {"type": "none"}
    t = u["type"]
    lst = lambda k, n, m: [_short(str(x).replace("*", ""), m) for x in (u.get(k) or []) if str(x).strip()][:n]  # noqa: E731
    if t == "title":
        return {"type": t, "text": _short(u.get("text"), 22) or "Meanwhile...", "sub": _short(u.get("sub"), 34)}
    if t == "notifications":
        items = lst("items", 4, 40)
        return {"type": t, "items": items or ["New message", "Are you open?", "Hello??"]}
    if t == "chat":
        msgs = [{"from": "ai" if str(m.get("from")).lower() == "ai" else "customer", "text": _short(m.get("text"), 60)}
                for m in (u.get("messages") or []) if isinstance(m, dict) and m.get("text")][:4]
        return {"type": t, "messages": msgs or [{"from": "customer", "text": "Can I book for today?"}, {"from": "ai", "text": "Sure! 5 PM is free. Booked!"}],
                "badge": _short(u.get("badge") or "Done", 26)}
    if t == "compare":
        return {"type": t, "left_title": _short(u.get("left_title") or "Before", 14), "right_title": _short(u.get("right_title") or "Now", 14),
                "left": lst("left", 3, 26) or ["Slow", "Manual"], "right": lst("right", 3, 26) or ["Instant", "Automatic"]}
    if t == "checklist":
        return {"type": t, "title": _short(u.get("title") or "What it does", 26), "items": lst("items", 4, 32) or ["Answers 24/7"]}
    if t == "timer":
        return {"type": t, "label": _short(u.get("label") or "Time", 20), "from": _short(u.get("from") or "4 hours", 12), "to": _short(u.get("to") or "30 sec", 12)}
    if t == "stat":
        try:
            a, b = int(u.get("from", 10)), int(u.get("to", 30))
        except (TypeError, ValueError):
            a, b = 10, 30
        return {"type": t, "label": _short(u.get("label") or "Customers", 26), "from": max(0, a), "to": max(a + 1, b)}
    return {"type": "none"}


def generate_story(cfg: dict, history: list) -> dict:
    from .content import BRAND, _ctx, _need
    from .llm import generate
    ctx = _ctx(cfg, history, "reel")
    allowed = [b for b in ((cfg.get("story") or {}).get("businesses") or BUSINESSES) if b in BUSINESSES] or BUSINESSES
    plans = [h.get("plan") or {} for h in history if (h.get("plan") or {}).get("style") == "story"][-6:]
    recent_types = [p.get("story_type") for p in plans if p.get("story_type")]
    recent_biz = [p.get("business") for p in plans if p.get("business")][-4:]
    recent_names = [n for p in plans for n in (p.get("names") or [])][-12:]
    rnd = random.Random()
    types = [t for t in ARCHETYPES if t not in recent_types[-4:]] or list(ARCHETYPES)
    stype = rnd.choice(types)
    biz = rnd.choice([b for b in allowed if b not in recent_biz] or allowed)
    ctx.update(archetype_name=stype, archetype=ARCHETYPES[stype].format(name=ctx["name"]), business=biz,
               icons=", ".join(ICONS), colors="|".join(COLORS),
               avoid=json.dumps({"story_types": recent_types[-4:], "businesses": recent_biz, "names": recent_names}))

    def check(o):
        _need(o, "topic", "shots", "caption", "hashtags")
        normalize(o, allowed, biz)
        hooks = [h for h in (o.get("hooks") or []) if isinstance(h, dict) and h.get("text")]
        if hooks:
            from .learning import choose_hook
            try:
                best = int(o.get("best_hook", 0))
            except (TypeError, ValueError):
                best = 0
            pick = hooks[choose_hook(hooks, best, random.Random())]
            o["shots"][0]["line"] = _short(pick.get("spoken") or pick["text"], 160)
            o["hook_type"], o["hook_options"] = pick.get("type", ""), [{"text": h["text"], "type": h.get("type")} for h in hooks]
        o["hook"] = o["shots"][0]["line"]
        o["story_type"] = stype
        o["cta"] = _short(o.get("cta") or cfg["brand"]["call_to_action"], 60)

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
    vc = cfg.get("voice") or {}
    voices = [vc["voice"]] if vc.get("voice") in VOICES else (vc.get("voices") or VOICES)
    last = next((h.get("voice") for h in reversed(history or []) if h.get("voice")), None)
    voice = random.Random(seed).choice([v for v in voices if v != last] or voices)
    rate = vc.get("rate", "+6%")
    clips = []
    try:
        for i, s in enumerate(post["shots"]):
            mp3 = work / f"vo-shot{i}.mp3"
            words = asyncio.run(_synth(s["line"], voice, mp3, rate))
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
UI_MIN = {"chat": 5.2, "compare": 4.6, "checklist": 4.2, "timer": 3.6, "stat": 3.6, "notifications": 3.4, "title": 3.0, "endcard": 3.8}


def build_timeline(post: dict, vo: dict | None) -> dict:
    shots, t = [], 0.0
    for i, s in enumerate(post["shots"]):
        lead = LEAD + (0.9 if s["ui"]["type"] == "title" else 0) + (0.25 if s["transition"] == "time_travel" else 0)
        need = lead + vo["clips"][i]["dur"] + 0.3 if vo else lead + 0.5 + len(_clean(s["line"]).split()) * 0.36
        walk = 2.6 if any(r.get("do") in ("walk_in", "walk_out", "storm_out", "walk_to") for r in s["cast"]) or s["set"] == "street" else 0
        d = round(max(2.4, UI_MIN.get(s["ui"]["type"], 0), walk, need), 2)
        shot = {k: v for k, v in s.items() if k != "line"}
        shot.update(start=round(t, 3), dur=d, lead=lead)
        shots.append(shot)
        t += d
    return {"shots": shots, "total": round(t, 2)}


def word_track(post: dict, tl: dict, vo: dict | None):
    """[(t0, t1, word, shot_index, highlighted)] + mono voice track."""
    words, track = [], None
    if vo:
        track = np.zeros(int(tl["total"] * SR) + 1)
    for i, (s, ts) in enumerate(zip(post["shots"], tl["shots"])):
        hl = {w.strip(".,!?;:\"'").lower() for w in " ".join(str(s["line"]).split("*")[1::2]).split()}
        t0 = ts["start"] + ts["lead"]
        if vo:
            c = vo["clips"][i]
            i0 = int(t0 * SR)
            a = c["audio"][: max(0, len(track) - i0)]
            track[i0:i0 + len(a)] += a
            ws = [(t0 + a0, t0 + a1, w) for a0, a1, w in c["words"]]
        else:
            toks = _clean(s["line"]).split()
            step = (ts["dur"] - ts["lead"] - 0.4) / max(1, len(toks))
            ws = [(t0 + k * step, t0 + (k + 1) * step, w) for k, w in enumerate(toks)]
        for w0, w1, w in ws:
            words.append((w0, w1, w, i, w.strip(".,!?;:\"'").lower() in hl))
    if track is not None:
        track = track / (np.max(np.abs(track)) or 1) * 0.92
    return words, track


def cues_for(tl: dict) -> list:
    cues = [(0.05, "impact")]
    for s in tl["shots"]:
        st, d, u = s["start"], s["dur"], s["ui"]["type"]
        if st > 0:
            if s["transition"] == "time_travel":
                cues += [(st - 0.9, "riser"), (st, "impact"), (st + 0.05, "whoosh")]
            else:
                cues += [(st - 0.12, "whoosh"), (st + 0.05, "pop")]
        if s.get("crowd", {}).get("do") == "arrive":
            cues += [(st + 0.3 + i * 0.4, "pop") for i in range(s["crowd"]["n"])]
        if u == "notifications":
            cues += [(st + 0.35 + i * 0.55, "alert") for i in range(4)]
        if u == "chat":
            cues += [(st + 0.6 + i * 0.95, "tick") for i in range(4)] + [(st + d - 1.15, "chime")]
        if u in ("checklist", "compare"):
            cues += [(st + 0.6 + i * 0.5, "tick") for i in range(4)]
        if u in ("stat", "timer"):
            cues.append((st + d * 0.6, "chime"))
        if u == "title":
            cues.append((st + 0.1, "pop"))
        if "confetti" in s.get("props", []) or "money_rain" in s.get("props", []):
            cues.append((st + 0.2, "chime"))
        if u == "endcard":
            cues += [(st + 0.2, "riser"), (st + 1.75, "pop")]
    return [(max(0.0, t), n) for t, n in cues]


# ====================================================================== tracker icons
def _icon(kind: str, size: int, color) -> Image.Image:
    s = size
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = color + (255,)
    k = s / 100
    L = lambda pts: [(x * k, y * k) for x, y in pts]  # noqa: E731
    lw = max(3, int(8 * k))
    hole = (0, 0, 0, 0)
    if kind == "store":
        d.rectangle(L([(22, 44), (78, 80)]), outline=c, width=lw); d.polygon(L([(16, 44), (24, 24), (76, 24), (84, 44)]), fill=c); d.rectangle(L([(42, 58), (58, 80)]), fill=c)
    elif kind == "person":
        d.ellipse(L([(38, 16), (62, 40)]), fill=c); d.rounded_rectangle(L([(28, 46), (72, 84)]), radius=int(16 * k), fill=c)
    elif kind == "people":
        for x0 in (14, 40, 66):
            d.ellipse(L([(x0 + 2, 22), (x0 + 20, 40)]), fill=c); d.rounded_rectangle(L([(x0 - 4, 46), (x0 + 26, 78)]), radius=int(12 * k), fill=c)
    elif kind == "phone":
        d.rounded_rectangle(L([(32, 12), (68, 88)]), radius=int(10 * k), outline=c, width=lw); d.ellipse(L([(45, 74), (55, 84)]), fill=c)
    elif kind == "moon":
        d.ellipse(L([(20, 18), (80, 78)]), fill=c); d.ellipse(L([(36, 10), (92, 66)]), fill=hole)
    elif kind == "exit":
        d.rectangle(L([(18, 16), (52, 84)]), outline=c, width=lw); d.line(L([(46, 50), (86, 50)]), fill=c, width=lw); d.polygon(L([(74, 36), (90, 50), (74, 64)]), fill=c)
    elif kind in ("clock", "hourglass"):
        if kind == "clock":
            d.ellipse(L([(16, 16), (84, 84)]), outline=c, width=lw); d.line(L([(50, 50), (50, 28)]), fill=c, width=lw); d.line(L([(50, 50), (66, 60)]), fill=c, width=lw)
        else:
            d.polygon(L([(26, 14), (74, 14), (50, 50)]), fill=c); d.polygon(L([(50, 50), (74, 86), (26, 86)]), outline=c, width=lw)
    elif kind == "chat":
        d.rounded_rectangle(L([(12, 20), (78, 68)]), radius=int(16 * k), fill=c); d.polygon(L([(24, 64), (20, 84), (42, 66)]), fill=c)
        for x0 in (28, 44, 60):
            d.ellipse(L([(x0 - 5, 39), (x0 + 5, 49)]), fill=hole)
    elif kind == "check":
        d.line(L([(18, 52), (40, 74), (84, 28)]), fill=c, width=lw + 4, joint="curve")
    elif kind == "heart":
        d.ellipse(L([(14, 22), (52, 58)]), fill=c); d.ellipse(L([(48, 22), (86, 58)]), fill=c); d.polygon(L([(16, 46), (84, 46), (50, 86)]), fill=c)
    elif kind == "money":
        d.rounded_rectangle(L([(10, 28), (90, 72)]), radius=int(8 * k), outline=c, width=lw); d.ellipse(L([(38, 38), (62, 62)]), outline=c, width=lw)
    elif kind == "box":
        d.polygon(L([(50, 12), (88, 30), (50, 48), (12, 30)]), fill=c); d.polygon(L([(12, 36), (46, 54), (46, 90), (12, 72)]), fill=c); d.polygon(L([(54, 54), (88, 36), (88, 72), (54, 90)]), fill=c)
    elif kind == "laptop":
        d.rounded_rectangle(L([(20, 20), (80, 62)]), radius=int(6 * k), outline=c, width=lw); d.rectangle(L([(8, 68), (92, 78)]), fill=c)
    elif kind == "mail":
        d.rectangle(L([(12, 24), (88, 76)]), outline=c, width=lw); d.line(L([(12, 24), (50, 54), (88, 24)]), fill=c, width=lw)
    elif kind == "calendar":
        d.rounded_rectangle(L([(14, 20), (86, 86)]), radius=int(8 * k), outline=c, width=lw); d.rectangle(L([(14, 20), (86, 38)]), fill=c)
        for x0 in (30, 50, 70):
            d.ellipse(L([(x0 - 5, 55), (x0 + 5, 65)]), fill=c)
    elif kind == "bolt":
        d.polygon(L([(56, 8), (22, 56), (46, 56), (40, 92), (78, 40), (54, 40)]), fill=c)
    elif kind == "rocket":
        d.ellipse(L([(36, 8), (64, 70)]), fill=c); d.polygon(L([(36, 50), (20, 76), (40, 66)]), fill=c); d.polygon(L([(64, 50), (80, 76), (60, 66)]), fill=c)
        d.ellipse(L([(45, 26), (55, 36)]), fill=hole); d.polygon(L([(42, 72), (58, 72), (50, 94)]), fill=(255, 200, 80, 255))
    elif kind == "warning":
        d.polygon(L([(50, 10), (92, 86), (8, 86)]), fill=c); d.rectangle(L([(46, 36), (54, 62)]), fill=hole); d.ellipse(L([(45, 68), (55, 78)]), fill=hole)
    elif kind == "idea":
        d.ellipse(L([(26, 10), (74, 58)]), fill=c); d.rectangle(L([(38, 58), (62, 80)]), fill=c); d.rectangle(L([(42, 84), (58, 90)]), fill=c)
    elif kind == "home":
        d.polygon(L([(50, 12), (90, 48), (10, 48)]), fill=c); d.rectangle(L([(22, 48), (78, 86)]), fill=c); d.rectangle(L([(42, 60), (58, 86)]), fill=hole)
    elif kind == "chart":
        for i, hgt in enumerate((24, 40, 58, 76)):
            d.rectangle(L([(14 + i * 20, 88 - hgt), (28 + i * 20, 88)]), fill=c)
    else:
        pts = [(50 + 40 * math.cos(a), 50 + 40 * math.sin(a)) if j % 2 == 0 else (50 + 17 * math.cos(a), 50 + 17 * math.sin(a))
               for j, a in enumerate([-math.pi / 2 + j * math.pi / 5 for j in range(10)])]
        d.polygon(L(pts), fill=c)
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


def _font(path, size):
    return ImageFont.truetype(str(path), size)


# ====================================================================== overlay
class StoryOverlay:
    def __init__(self, post, cfg, tl, pal, fps, words, first_frame=None):
        self.post, self.tl, self.fps, self.words, self.first = post, tl, fps, words, first_frame
        self.accent = tuple(pal["_rgb"]["accent"])
        self.red, self.green = (226, 72, 60), (24, 168, 112)
        acc = (cfg.get("_account") or {}).get("assets") or {}
        from .account import local_logo, logo_png
        lb = acc.get("avatar_bytes") or local_logo()[0]
        self.logo = logo_png(lb, 220) if lb else None
        self.brand = cfg["brand"]["name"]
        self.handle = "@" + acc["username"] if acc.get("username") else cfg["brand"]["handle"]
        self._cap, self._cache = {}, {}
        # sepia + grain for the past
        g = np.random.default_rng(7).normal(0, 9, (H // 2, W // 2)).astype(np.float32)
        self.grain = np.asarray(Image.fromarray(np.clip(g + 128, 0, 255).astype(np.uint8)).resize((W, H)), np.float32) - 128
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.sqrt(((xx - W / 2) / (W * 0.62)) ** 2 + ((yy - H / 2) / (H * 0.62)) ** 2)
        self.vig = np.clip(1.15 - 0.55 * r ** 2, 0.45, 1)[..., None]
        # tracker
        self.slots = [(i, s) for i, s in enumerate(tl["shots"]) if s["ui"]["type"] != "endcard"]
        n = max(1, len(self.slots))
        self.slot = 84 if n <= 8 else 70
        self.gap = 14 if n <= 8 else 8
        self.bar_w = n * self.slot + (n - 1) * self.gap + 44
        self.bar, self.bar_m = card(self.bar_w, self.slot + 28, (self.slot + 28) // 2, fill=(255, 255, 255, 232))
        self.icons = []
        for i, s in self.slots:
            col = self.red if s["mood"] == "bad" else (self.green if s["mood"] == "good" else INK)
            disc = rounded(self.slot, self.slot, self.slot // 2, col + (255,))
            disc.alpha_composite(_icon(s["icon"], int(self.slot * 0.62), WHITE), (int(self.slot * 0.19), int(self.slot * 0.19)))
            self.icons.append(disc)
        self.cap_font = _font(FONT_BOLD, 128)
        self._endcard_build()

    # ---------------------------------------------------------------- small helpers
    def _ring(self, f, cx, cy, q, rmin, rmax, col=None, width=10):
        rad = int(rmin + (rmax - rmin) * ease_out_cubic(q))
        im = Image.new("RGBA", (rad * 2 + 20, rad * 2 + 20), (0, 0, 0, 0))
        ImageDraw.Draw(im).ellipse((10, 10, rad * 2 + 10, rad * 2 + 10), outline=(col or self.accent) + (int(230 * (1 - q)),),
                                   width=max(2, int(width * (1 - q))))
        _paste_rgba(f, im, cx - rad - 10, cy - rad - 10)

    @staticmethod
    def _fit(t, font, max_w):
        t = str(t)
        while font.getlength(t) > max_w and len(t) > 4:
            t = t[:-2].rstrip() + "…"
        return t.replace("……", "…")

    def _pop(self, im, k):
        if k >= 0.999:
            return im
        s = max(0.05, min(1.12, k))
        return im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))))

    # ---------------------------------------------------------------- captions + tracker
    def _caption(self, f, t, y=430):
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
            size, font = 128, self.cap_font
            while font.getlength(word) > W - 120 and size > 60:
                size -= 8
                font = _font(FONT_BOLD, size)
            asc, desc = font.getmetrics()
            im = Image.new("RGBA", (int(font.getlength(word)) + 60, asc + desc + 60), (0, 0, 0, 0))
            ImageDraw.Draw(im).text((30, 30), word, font=font, fill=col + (255,), stroke_width=9, stroke_fill=(24, 24, 30, 255))
            sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
            sh.putalpha(im.getchannel("A").point(lambda a: int(a * 0.35)))
            out = Image.new("RGBA", (im.width, im.height + 10), (0, 0, 0, 0))
            out.alpha_composite(sh.filter(ImageFilter.GaussianBlur(10)), (0, 10))
            out.alpha_composite(im)
            self._cap[key] = out
        k = ease_out_back((t - cur[0] + 0.03) / 0.16)
        im = self._cap[key]
        s = 0.82 + 0.18 * min(1.08, k)
        if abs(s - 1) > 0.01:
            im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))))
        _paste_rgba(f, im, (W - im.width) // 2, y - im.height // 2, min(1.0, max(0.0, k * 1.5)))

    def _tracker(self, f, t, si):
        x0 = (W - self.bar_w) // 2
        kb = ease_out_cubic(t / 0.4)
        _paste_rgba(f, self.bar, x0 - self.bar_m, 150 - self.bar_m - int((1 - kb) * 40), kb)
        for j, (i, s) in enumerate(self.slots):
            cx = x0 + 22 + j * (self.slot + self.gap)
            if t < s["start"]:
                _paste_rgba(f, rounded(self.slot, self.slot, self.slot // 2, INK + (18,)), cx, 164, kb)
                continue
            ic = self._pop(self.icons[j], ease_out_back((t - s["start"]) / 0.45))
            _paste_rgba(f, ic, cx + (self.slot - ic.width) // 2, 164 + (self.slot - ic.height) // 2)
            if i == si:
                self._ring(f, cx + self.slot // 2, 164 + self.slot // 2, ((t - s["start"]) % 1.2) / 1.2, self.slot // 2 + 2, self.slot // 2 + 28,
                           self.red if s["mood"] == "bad" else self.green if s["mood"] == "good" else self.accent, 6)

    # ---------------------------------------------------------------- UI moments
    def _title(self, f, lt, d, u, shot):
        """Big centred title card, then it shrinks into a chip under the tracker."""
        key = ("title", u["text"], u.get("sub"))
        if key not in self._cache:
            tf, sf = _font(FONT_BOLD, 150 if len(u["text"]) <= 8 else 104), _font(FONT_SEMI, 44)
            tt = text(u["text"], tf, INK + (255,))
            st = text(u["sub"], sf, INK + (150,)) if u.get("sub") else None
            cw = max(tt.width, st.width if st else 0) + 120
            ch = tt.height + (st.height + 10 if st else 0) + 80
            im, m = card(cw, ch, 56)
            im.alpha_composite(tt, (m + (cw - tt.width) // 2, m + 30))
            if st:
                im.alpha_composite(st, (m + (cw - st.width) // 2, m + 40 + tt.height))
            ImageDraw.Draw(im).rounded_rectangle((m + cw // 2 - 70, m + ch - 34, m + cw // 2 + 70, m + ch - 22), radius=6, fill=self.accent + (255,))
            chip_t = text(u["text"], _font(FONT_BOLD, 40), WHITE + (255,))
            chip = rounded(chip_t.width + 56, 74, 37, INK + (255,))
            chip.alpha_composite(chip_t, (28, (74 - chip_t.height) // 2))
            self._cache[key] = (im, m, chip)
        im, m, chip = self._cache[key]
        k = ease_out_back((lt - 0.05) / 0.4)
        if lt < 1.25:
            if k > 0:
                pim = self._pop(im, k)
                _paste_rgba(f, pim, (W - pim.width) // 2, 820 - pim.height // 2, min(1.0, k * 1.4))
        else:
            kc = ease_out_back((lt - 1.25) / 0.35)
            pc = self._pop(chip, kc)
            _paste_rgba(f, pc, 60, 300, min(1.0, kc * 1.5))

    def _notes(self, f, lt, d, u):
        tf, bf, sf = _font(FONT_BOLD, 34), _font(FONT_MED, 34), _font(FONT_MED, 26)
        items = u["items"]
        for j, m_ in enumerate(items):
            key = ("note", m_)
            if key not in self._cache:
                im, mm = card(W - 140, 128, 36)
                dd = ImageDraw.Draw(im)
                ic = rounded(80, 80, 22, self.accent + (255,))
                ic.alpha_composite(_icon("chat", 56, WHITE), (12, 12))
                im.alpha_composite(ic, (mm + 24, mm + 14))
                dd.text((mm + 128, mm + 14), "New message", font=tf, fill=INK + (255,))
                dd.text((W - 140 + mm - 90, mm + 20), "now", font=sf, fill=INK + (120,))
                dd.text((mm + 128, mm + 60), self._fit(m_, bf, W - 140 - 170), font=bf, fill=INK + (170,))
                self._cache[key] = (im, mm)
            im, mm = self._cache[key]
            t0 = 0.35 + j * min(0.6, (d - 1.0) / max(1, len(items)))
            k = ease_out_back((lt - t0) / 0.4)
            if k <= 0:
                continue
            y = 1250 + j * 150 - int((1 - min(1.0, k)) * 120)
            _paste_rgba(f, im, 70 - mm, y - mm, min(1.0, k) * (1 - ease_out_cubic((lt - (d - 0.3)) / 0.3)))
        cnt = min(99, int(max(0, lt - 0.3) * 5) + len(items))
        key = ("unans", cnt)
        if key not in self._cache:
            tt = text(f"{cnt} unanswered", _font(FONT_BOLD, 40), WHITE + (255,))
            pill = rounded(tt.width + 56, 76, 38, self.red + (255,))
            pill.alpha_composite(tt, (28, (76 - tt.height) // 2))
            self._cache[key] = pill
        p = self._cache[key]
        _paste_rgba(f, p, (W - p.width) // 2, 1130, ease_out_cubic(lt / 0.4))

    def _chat(self, f, lt, d, u):
        key = ("chat", json.dumps(u))
        pw, ph = 700, 1180
        if key not in self._cache:
            body = rounded(pw, ph, 96, (22, 22, 26, 255))
            body.alpha_composite(rounded(pw - 36, ph - 36, 80, (246, 244, 240, 255)), (18, 18))
            dd = ImageDraw.Draw(body)
            dd.rounded_rectangle((pw // 2 - 90, 40, pw // 2 + 90, 92), radius=26, fill=(10, 10, 12, 255))
            hdr = rounded(pw - 36, 190, 0, self.accent + (255,))
            body.paste(hdr, (18, 18), rounded(pw - 36, 260, 80, (255, 255, 255, 255)).crop((0, 0, pw - 36, 190)).getchannel("A"))
            if self.logo:
                body.alpha_composite(rounded(96, 96, 48, (255, 255, 255, 255)), (54, 104))
                body.alpha_composite(self.logo.resize((86, 86), Image.LANCZOS), (59, 109))
            dd.text((170, 108), f"{self.brand} AI", font=_font(FONT_BOLD, 40), fill=WHITE + (255,))
            dd.text((170, 158), f"for {self.post.get('business_name', '')}", font=_font(FONT_MED, 28), fill=WHITE + (210,))
            dd.ellipse((pw - 160, 128, pw - 142, 146), fill=(120, 255, 170, 255))
            dd.text((pw - 132, 118), "Live", font=_font(FONT_SEMI, 30), fill=WHITE + (255,))
            dd.text((60, 30), "9:41", font=_font(FONT_SEMI, 30), fill=WHITE + (255,))
            bf = _font(FONT_MED, 34)
            bubbles = []
            for c in u["messages"]:
                ai = c["from"] == "ai"
                lines = _wrap(c["text"], bf, pw - 240)
                bw, bh = int(max(bf.getlength(x) for x in lines)) + 56, len(lines) * 44 + 34
                b = rounded(bw, bh, 30, (self.accent if ai else (228, 225, 219)) + (255,))
                bd = ImageDraw.Draw(b)
                for k_, ln in enumerate(lines):
                    bd.text((28, 14 + k_ * 44), ln, font=bf, fill=(WHITE if ai else INK) + (255,))
                bubbles.append((b, ai))
            bt = text("✓  " + u["badge"], _font(FONT_BOLD, 38), WHITE + (255,))
            badge = rounded(bt.width + 60, 92, 46, (22, 22, 26, 255))
            badge.alpha_composite(bt, (30, (92 - bt.height) // 2))
            self._cache[key] = (body, bubbles, badge)
        body, bubbles, badge = self._cache[key]
        y = int(H - (H - 860) * ease_out_cubic(lt / 0.55) + 900 * ease_out_cubic((lt - (d - 0.35)) / 0.35))
        ph_ = body.copy()
        span = max(0.8, (d - 1.9) / max(1, len(bubbles)))
        cy = 250
        for j, (b, ai) in enumerate(bubbles):
            t0 = 0.55 + j * span
            if ai and t0 - 0.45 <= lt < t0:
                ty = rounded(120, 64, 32, (228, 225, 219, 255))
                for q in range(3):
                    ty.alpha_composite(rounded(16, 16, 8, (90, 90, 90, int(255 * (0.45 + 0.55 * abs(math.sin(lt * 7 - q * 0.7)))))), (24 + q * 28, 24))
                ph_.alpha_composite(ty, (44, cy))
            if lt < t0:
                break
            sb = self._pop(b, ease_out_back((lt - t0) / 0.32))
            ph_.alpha_composite(sb, (44 if ai else pw - 44 - sb.width, cy + (b.height - sb.height) // 2))
            cy += b.height + 22
        kb = ease_out_back((lt - (d - 1.15)) / 0.4)
        if kb > 0:
            bb = self._pop(badge, kb)
            ph_.alpha_composite(bb, ((pw - bb.width) // 2, min(cy + 20, ph - 220)))
        sh, sm = shadow(pw, ph, 96, 40, 110)
        _paste_rgba(f, sh, (W - pw) // 2 - sm, y - sm + 20)
        _paste_rgba(f, ph_, (W - pw) // 2, y)
        q = (lt - (d - 1.1)) / 0.8
        if 0 <= q < 1:
            self._ring(f, W // 2, y + min(cy + 66, ph - 174), q, 80, 360)

    def _compare(self, f, lt, d, u):
        cw, ch = W - 120, 560
        key = ("cmp", json.dumps(u))
        if key not in self._cache:
            im, m = card(cw, ch, 50)
            dd = ImageDraw.Draw(im)
            hw = (cw - 60) // 2
            for side, (title, col, x) in enumerate(((u["left_title"], self.red, m + 20), (u["right_title"], self.green, m + 40 + hw))):
                hdr = rounded(hw, 96, 30, col + (255,))
                tt = text(title, _font(FONT_BOLD, 50), WHITE + (255,))
                hdr.alpha_composite(tt, ((hw - tt.width) // 2, (96 - tt.height) // 2))
                im.alpha_composite(hdr, (x, m + 22))
            self._cache[key] = (im, m, hw)
        im, m, hw = self._cache[key]
        k = ease_out_back((lt - 0.1) / 0.5)
        if k <= 0:
            return
        y = 1210 + int((1 - min(1.0, k)) * 700)
        base = im.copy()
        dd = ImageDraw.Draw(base)
        f_it = _font(FONT_SEMI, 38)
        n = max(len(u["left"]), len(u["right"]))
        for side, items in enumerate((u["left"], u["right"])):
            x = m + 20 + side * (hw + 20)
            for j, it in enumerate(items):
                tq = (lt - 0.6 - (j * 2 + side) * min(0.35, (d - 1.5) / max(1, 2 * n))) / 0.25
                if tq <= 0:
                    continue
                yy = m + 150 + j * 112
                mark = "✕" if side == 0 else "✓"
                col = self.red if side == 0 else self.green
                dd.ellipse((x + 10, yy, x + 70, yy + 60), fill=col + (int(255 * min(1, tq)),))
                dd.text((x + 26 if side else x + 27, yy + 6), mark, font=_font(FONT_BOLD, 40), fill=WHITE + (int(255 * min(1, tq)),))
                dd.text((x + 88, yy + 8), self._fit(it, f_it, hw - 100), font=f_it, fill=INK + (int(255 * min(1, tq)),))
        _paste_rgba(f, base, 60 - m, y - m)

    def _checklist(self, f, lt, d, u):
        cw = W - 140
        items = u["items"]
        ch = 140 + len(items) * 104
        k = ease_out_back((lt - 0.1) / 0.5)
        if k <= 0:
            return
        im, m = card(cw, ch, 48)
        dd = ImageDraw.Draw(im)
        dd.text((m + 44, m + 34), u["title"].upper(), font=_font(FONT_BOLD, 40), fill=INK + (255,))
        fi = _font(FONT_SEMI, 38)
        for j, it in enumerate(items):
            tq = (lt - 0.6 - j * min(0.55, (d - 1.4) / max(1, len(items)))) / 0.3
            yy = m + 120 + j * 104
            done = tq >= 1
            dd.rounded_rectangle((m + 44, yy, m + 112, yy + 68), radius=20, fill=(self.green if done else (230, 228, 222)) + (255,))
            if tq > 0:
                q = min(1, tq)
                pts = [(m + 58, yy + 34), (m + 74, yy + 50), (m + 100, yy + 20)]
                seg = pts[:2] if q < 0.5 else pts
                dd.line(seg, fill=WHITE + (255,), width=9, joint="curve")
            dd.text((m + 136, yy + 12), self._fit(it, fi, cw - 180), font=fi, fill=INK + (255 if tq > 0 else 110,))
        y = 1880 - ch - 60 + int((1 - min(1.0, k)) * 600)
        _paste_rgba(f, im, 70 - m, y - m)

    def _timer(self, f, lt, d, u):
        k = ease_out_back((lt - 0.1) / 0.5)
        if k <= 0:
            return
        cw, ch = W - 140, 360
        im, m = card(cw, ch, 50)
        dd = ImageDraw.Draw(im)
        dd.text((m + 50, m + 36), u["label"].upper(), font=_font(FONT_SEMI, 34), fill=INK + (140,))
        ft = _font(FONT_BOLD, 84)
        q = ease_out_cubic((lt - 0.6) / 0.6)
        x = m + 50
        dd.text((x, m + 100), u["from"], font=ft, fill=self.red + (255,))
        wf = ft.getlength(u["from"])
        if q > 0:
            dd.line((x - 6, m + 152, x - 6 + (wf + 12) * q, m + 152), fill=INK + (255,), width=9)
        k2 = ease_out_back((lt - 1.1) / 0.4)
        if k2 > 0:
            dd.text((x, m + 210), "→ " + u["to"], font=ft, fill=self.green + (int(255 * min(1, k2)),))
        # stopwatch icon
        cx, cy = m + cw - 130, m + 190
        dd.ellipse((cx - 90, cy - 90, cx + 90, cy + 90), outline=INK + (255,), width=12)
        a = -math.pi / 2 + lt * 6
        dd.line((cx, cy, cx + 70 * math.cos(a), cy + 70 * math.sin(a)), fill=self.accent + (255,), width=10)
        dd.rectangle((cx - 16, cy - 118, cx + 16, cy - 96), fill=INK + (255,))
        y = 1300 + int((1 - min(1.0, k)) * 600)
        _paste_rgba(f, im, 70 - m, y - m)

    def _stat(self, f, lt, d, u):
        k = ease_out_back((lt - 0.2) / 0.5)
        if k <= 0:
            return
        cw, ch = W - 140, 300
        im, m = card(cw, ch, 48)
        dd = ImageDraw.Draw(im)
        dd.text((m + 50, m + 34), u["label"].upper(), font=_font(FONT_SEMI, 34), fill=INK + (140,))
        q = ease_out_cubic((lt - 0.5) / max(0.8, d - 1.4))
        dd.text((m + 46, m + 80), str(int(round(u["from"] + (u["to"] - u["from"]) * q))), font=_font(FONT_BOLD, 110), fill=INK + (255,))
        pct = int(round((u["to"] - u["from"]) / max(1, u["from"]) * 100 * q))
        chip = rounded(190, 64, 32, self.green + (255,))
        ct = text(f"▲ {pct}%", _font(FONT_BOLD, 34), WHITE + (255,))
        chip.alpha_composite(ct, ((190 - ct.width) // 2, (64 - ct.height) // 2))
        im.alpha_composite(chip, (m + 50, m + 210))
        for b in range(6):
            hb = int((40 + b * 26) * max(0.0, min(1.0, q * 1.3 - b * 0.08)))
            if hb > 0:
                col = self.green if b == 5 else _mix(self.green, WHITE, 0.55)
                dd.rounded_rectangle((m + cw - 360 + b * 52, m + 250 - hb, m + cw - 324 + b * 52, m + 250), radius=10, fill=col + (255,))
        _paste_rgba(f, im, 70 - m, 1300 + int((1 - min(1.0, k)) * 200) - m, min(1.0, k))

    def _endcard_build(self):
        ew, eh = W - 120, 560
        self.end, self.end_m = card(ew, eh, 60)
        if self.logo:
            self.end.alpha_composite(self.logo.resize((170, 170), Image.LANCZOS), (self.end_m + (ew - 170) // 2, self.end_m + 34))
        bt = text(self.brand, _font(FONT_BOLD, 76), INK + (255,))
        self.end.alpha_composite(bt, (self.end_m + (ew - bt.width) // 2, self.end_m + 214))
        ct = text(self.post.get("cta") or "", _font(FONT_MED, 36), INK + (150,))
        if ct.width > ew - 60:
            ct = ct.resize((ew - 60, int(ct.height * (ew - 60) / ct.width)), Image.LANCZOS)
        self.end.alpha_composite(ct, (self.end_m + (ew - ct.width) // 2, self.end_m + 312))
        bf = _font(FONT_BOLD, 46)
        self.btn, self.btn2 = rounded(470, 112, 56, self.accent + (255,)), rounded(470, 112, 56, INK + (255,))
        for b, lab in ((self.btn, "Follow  →"), (self.btn2, "Following ✓")):
            t_ = text(lab, bf, WHITE + (255,))
            b.alpha_composite(t_, ((470 - t_.width) // 2, (112 - t_.height) // 2))
        self.end_handle = text(self.handle, _font(FONT_SEMI, 32), INK + (130,))

    def _end(self, f, lt, d):
        k = ease_out_back((lt - 0.15) / 0.6)
        if k <= 0:
            return
        y = 1180 + int((1 - min(1.0, k)) * 700)
        _paste_rgba(f, self.end, 60 - self.end_m, y - self.end_m)
        press = 6 if 1.55 < lt < 1.8 else 0
        bx, by = (W - 470) // 2, y + 400 + press
        _paste_rgba(f, self.btn2 if lt > 1.75 else self.btn, bx, by)
        _paste_rgba(f, self.end_handle, (W - self.end_handle.width) // 2, y + 514)
        q = (lt - 1.55) / 0.7
        if 0 <= q < 1:
            self._ring(f, bx + 330, by + 56, q, 20, 130, INK, 6)

    # ---------------------------------------------------------------- looks + transitions
    def _sepia(self, f, t, night=False):
        x = f.astype(np.float32)
        if night:  # keep night scenes in the past readable
            x = 255 * (x / 255) ** 0.62
        g = x @ np.array([[0.393, 0.349, 0.272], [0.769, 0.686, 0.534], [0.189, 0.168, 0.131]], np.float32)
        g = g * 0.92 + 14
        off = int(t * 97) % 40
        g += np.roll(self.grain, off, axis=0)[..., None] * 0.9
        g *= self.vig * (1 + 0.025 * math.sin(t * 37))
        return np.clip(g, 0, 255).astype(np.uint8)

    @staticmethod
    def _whip(f, amt):
        sh = int(30 * amt)
        if sh <= 1:
            return f
        acc = sum(np.roll(f, int(o), axis=1).astype(np.float32) for o in np.linspace(-sh, sh, 7)) / 7
        return acc.clip(0, 255).astype(np.uint8)

    @staticmethod
    def _zoomblur(f, amt):
        im = Image.fromarray(f)
        acc = np.asarray(im, np.float32)
        n = 4
        for i in range(1, n + 1):
            s = 1 + 0.06 * amt * i
            cw, ch = int(W / s), int(H / s)
            crop = im.crop(((W - cw) // 2, (H - ch) // 2, (W + cw) // 2, (H + ch) // 2)).resize((W, H), Image.BILINEAR)
            acc += np.asarray(crop, np.float32)
        return (acc / (n + 1)).clip(0, 255).astype(np.uint8)

    def compose_raw(self, i, frame_path):
        img = Image.open(frame_path).transpose(Image.FLIP_TOP_BOTTOM)
        if img.size != (W, H):
            img = img.resize((W, H), Image.BICUBIC)
        t = i / self.fps
        shots = self.tl["shots"]
        si = next((k for k, s in enumerate(shots) if s["start"] <= t < s["start"] + s["dur"]), len(shots) - 1)
        s = shots[si]
        lt, d = t - s["start"], s["dur"]
        f = np.asarray(img).copy()
        if s.get("transition") == "zoom" and lt < 0.35:
            z = 1 + 0.18 * (1 - ease_out_cubic(lt / 0.35))
            cw, ch = int(W / z), int(H / z)
            f = np.asarray(img.crop(((W - cw) // 2, (H - ch) // 2, (W + cw) // 2, (H + ch) // 2)).resize((W, H), Image.BILINEAR)).copy()
        if s["era"] == "past":
            f = self._sepia(f, t, s.get("time") == "night")
        # transitions around the cut into the NEXT shot / from the previous one
        nxt = shots[si + 1] if si + 1 < len(shots) else None
        for tr, q in ((s.get("transition"), lt), ((nxt or {}).get("transition"), lt - d)):
            if tr is None or (q is lt and si == 0):
                continue
            if tr == "time_travel" and -0.45 <= q < 0.45:
                amt = 1 - abs(q) / 0.45
                f = self._zoomblur(f, amt * 1.6)
                flash = max(0.0, 1 - abs(q) / 0.18)
                if flash > 0:
                    f = (f.astype(np.float32) * (1 - flash) + 255 * flash).astype(np.uint8)
            elif tr == "later" and -0.35 <= q < 0.35:
                a = 1 - abs(q) / 0.35
                f = (f.astype(np.float32) * (1 - a) + np.array((243, 239, 232), np.float32) * a).astype(np.uint8)
            elif tr in ("cut", "zoom") and -0.09 <= q < 0.09 and not (q is lt and si == 0):
                f = self._whip(f, 1 - abs(q) / 0.09)
        f = np.ascontiguousarray(f)
        u = s["ui"]
        self._tracker(f, t, si)
        cap_y = 430
        if u["type"] == "title":
            self._title(f, lt, d, u, s)
        elif u["type"] == "notifications":
            self._notes(f, lt, d, u)
        elif u["type"] == "chat":
            self._chat(f, lt, d, u)
        elif u["type"] == "compare":
            self._compare(f, lt, d, u)
        elif u["type"] == "checklist":
            self._checklist(f, lt, d, u)
        elif u["type"] == "timer":
            self._timer(f, lt, d, u)
        elif u["type"] == "stat":
            self._stat(f, lt, d, u)
        elif u["type"] == "endcard":
            self._end(f, lt, d)
        if not (u["type"] == "endcard" and lt > 1.0) and not (u["type"] == "title" and lt < 1.25):
            self._caption(f, t, cap_y)
        return f

    def compose(self, i, frame_path):
        f = self.compose_raw(i, frame_path)
        t, total = i / self.fps, self.tl["total"]
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
    pal_name, pal = pick_light_palette(cfg, random.Random(seed))
    tl = build_timeline(post, vo)
    sets = sorted({s["set"] for s in post["shots"]})
    post["_plan"] = {"style": "story", "theme": "light", "palette": pal_name, "business": post["business"],
                     "story_type": post.get("story_type"), "sets": sets, "names": [c["name"] for c in post["cast"]]}
    job = {"mode": "reel", "page": "story", "width": W, "height": H, "fps": fps, "seed": seed,
           "render_scale": cfg["video"].get("render_scale", 0.6667),
           "palette": {k: v for k, v in pal.items() if not k.startswith("_")},
           "story": {"business": post["business"], "business_name": post["business_name"], "services": post.get("services", []),
                     "office_name": post.get("office_name"), "warehouse_name": post.get("warehouse_name"),
                     "cast": post["cast"], "shots": tl["shots"], "total": tl["total"]}}
    print(f"[story] {post.get('story_type')} | {post['business']} '{post['business_name']}' | sets {sets} | "
          f"{len(tl['shots'])} shots, {tl['total']:.1f}s, palette {pal_name}")
    rdir = work / "3d"
    run_renderer(job, rdir)
    frames = sorted((rdir / "frames").glob("*.jpg"))
    words, voice = word_track(post, tl, vo)
    total = round(len(frames) / fps, 3)
    audio = build_soundtrack(total, cues_for(tl), cfg, work / "audio.wav", seed=seed, style="classic", voice=voice)
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


if __name__ == "__main__":  # local check: python -m autoposter.story sample.json out.mp4 [--voice]
    import sys
    import tempfile
    from .config import load_config
    cfg = load_config()
    post = json.loads(Path(sys.argv[1]).read_text())
    normalize(post, BUSINESSES, post.get("business", "salon"))
    w = Path(tempfile.mkdtemp())
    vo = make_story_voice(post, cfg, 1, w) if "--voice" in sys.argv else None
    render_story_reel(post, cfg, Path(sys.argv[2]), w, 7, vo)
