"""Carousel slides (1080x1350) and story images (1080x1920) rendered from the
same 3D scene, with liquid-glass cards drawn by the browser (real backdrop blur)."""
import html
import random
import re
from pathlib import Path

from .cinematic import account_for_job, date_label, pick_palette, run_renderer


def _rich(text: str) -> str:
    """*word* -> highlighted span (text is HTML-escaped first)."""
    out, hl = [], False
    for part in re.split(r"(\*)", str(text)):
        if part == "*":
            hl = not hl
            continue
        part = html.escape(part)
        out.append(f'<span class="hl">{part}</span>' if hl and part.strip() else part)
    return "".join(out)


def _job(cfg, mode_w, mode_h, seed, stills, extra=None):
    rng = random.Random(seed)
    light = cfg["video"].get("theme", "light") == "light"
    if light:
        from .light import pick_light_palette
        _, pal = pick_light_palette(cfg, rng)
    else:
        _, pal = pick_palette(cfg, rng)
    if light:  # dotted paper texture at the top of every slide
        for s in stills:
            s["html"] = '<div class="dots"></div>' + s["html"]
    job = {"mode": "stills", "theme": "light" if light else "dark", "width": mode_w, "height": mode_h, "fps": 30, "seed": seed,
           "finish": rng.choice(["black", "blue"] if light else ["graphite", "silver"]), "date_label": date_label(cfg),
           "brand": {"name": cfg["brand"]["name"], "handle": cfg["brand"]["handle"]},
           "account": account_for_job(cfg),
           "palette": {k: v for k, v in pal.items() if not k.startswith("_")}, "stills": stills}
    job.update(extra or {})
    return job


def _logo_html(cfg, size=46):
    av = (((cfg.get("_account") or {}).get("assets") or {}).get("avatar"))
    if not av:
        from .account import _data_url, local_logo
        av = _data_url(local_logo()[0])
    if not av:
        return ""
    return (f'<img src="{av}" style="width:{size}px;height:{size}px;border-radius:50%;vertical-align:middle;'
            f'margin:-8px 14px -6px -10px;box-shadow:0 0 0 3px rgba(255,255,255,.35)">')


def render_carousel(post: dict, cfg: dict, work: Path, seed: int) -> list[Path]:
    b = cfg["brand"]
    logo = _logo_html(cfg)
    slides = post["slides"]
    n = len(slides) + 2
    handle = html.escape(b["handle"])
    stills = [{
        "name": "s00", "scene": "hero", "index": 0,
        "html": f'''<div class="kicker glass" style="position:absolute;left:70px;top:80px">{logo}{html.escape(b["name"].upper())}</div>
          <div class="title" style="position:absolute;left:70px;right:70px;top:180px;font-size:96px">{_rich(post["title"])}</div>
          <div class="body" style="position:absolute;left:72px;right:90px;top:{180 + 96 * 1.1 * 3 + 20}px;margin:0">{html.escape(post.get("subtitle", ""))}</div>
          <div class="swipe glass">SWIPE →</div>''',
    }]
    for i, s in enumerate(slides, 1):
        stills.append({
            "name": f"s{i:02d}", "scene": "bg", "index": i, "blur": 16,
            "html": f'''<div class="card glass" style="top:120px;bottom:170px;display:flex;flex-direction:column;justify-content:center">
                <div class="big hl">{i:02d}</div>
                <div class="title" style="margin-top:36px">{_rich(s["title"])}</div>
                <div class="body">{html.escape(s["body"])}</div></div>
              <div class="page">{_logo_html(cfg, 38)}{handle} · {i + 1}/{n}</div><div class="swipe glass">→</div>''',
        })
    stills.append({
        "name": f"s{n - 1:02d}", "scene": "phone", "index": n - 1,
        "html": f'''<div class="title" style="position:absolute;left:70px;right:70px;top:90px;text-align:center;font-size:84px">{_rich(post.get("cta", ""))}</div>
          <div class="kicker glass" style="position:absolute;left:50%;bottom:70px;transform:translateX(-50%);margin:0;font-size:36px">{logo}{handle}</div>''',
    })
    out = work / "carousel"
    data = {"app_name": post.get("topic", "")[:18], "steps": [{"title": s["title"], "text": ""} for s in slides[:3]],
            "phone_mode": "profile"}
    run_renderer(_job(cfg, 1080, 1350, seed, stills, data), out)
    return [out / f"{s['name']}.jpg" for s in stills]


KICKERS = {"tip": "TIP OF THE DAY", "question": "QUICK QUESTION", "fact": "DID YOU KNOW?"}


def render_stories(stories: list, cfg: dict, work: Path, seed: int) -> list[Path]:
    handle = html.escape(cfg["brand"]["handle"])
    stills = []
    for i, s in enumerate(stories):
        kind = s.get("kind", "tip")
        extra = ('<div class="swipe glass" style="left:50%;right:auto;transform:translateX(-50%);bottom:260px">'
                 'Reply in DMs 💬</div>') if kind == "question" else ""
        stills.append({
            "name": f"story{i}", "scene": "phone" if i % 2 == 0 else "bg", "index": i, "blur": 0 if i % 2 == 0 else 14,
            "html": f'''<div class="card glass" style="top:200px">
                <div class="kicker glass">{KICKERS.get(kind, "TODAY")}</div>
                <div class="title">{_rich(s["title"])}</div>
                <div class="body">{html.escape(s["body"])}</div></div>{extra}
              <div class="page" style="left:50%;transform:translateX(-50%);bottom:120px">{_logo_html(cfg, 40)}{handle}</div>''',
        })
    out = work / "stories"
    run_renderer(_job(cfg, 1080, 1920, seed, stills, {"phone_mode": "lock", "app_name": cfg["brand"]["name"]}), out)
    return [out / f"{s['name']}.jpg" for s in stills]
