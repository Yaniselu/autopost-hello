"""Cinematic reel: 3D laptop/phone scene (rendered by renderer/ in headless
Chromium) + liquid-glass typography composited here at full 1080x1920,
+ cinematic soundtrack and sound effects.

Structure of every reel:  HOOK -> THE PROBLEM -> THE FIX (3 steps) -> THE RESULT -> CTA
"""
import datetime as dt
import json
import math
import os
import random
import shutil
import subprocess
from multiprocessing import get_context
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .audio import build_soundtrack
from .config import ROOT
from .ff import FFMPEG
from .glass import PALETTES, Glass, _blend, _gradient_fill, _paste_rgba, _spaced, _text_img
from .render import FONT_BOLD, FONT_MED, FONT_SEMI, ease_out_back, ease_out_cubic, parse_rich, render_line

RENDERER = ROOT / "renderer"
W, H = 1080, 1920


# ====================================================================== job / palette
def _hex(c) -> str:
    return "#%02x%02x%02x" % tuple(int(x) for x in c)


def pick_palette(cfg: dict, rng: random.Random) -> tuple[str, dict]:
    name = cfg["video"].get("palette", "random")
    if name not in PALETTES:
        name = rng.choice(list(PALETTES))
    p = PALETTES[name]
    top = tuple(int(p["bg"][i] * 0.6 + p["blobs"][1][i] * 0.18) for i in range(3))
    return name, {"bg": [_hex(p["bg"]), _hex(top)], "accent": _hex(p["accent"]), "accent2": _hex(p["accent2"]),
                  "glow": [_hex(c) for c in p["blobs"]], "_rgb": p}


def run_renderer(job: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    job_file = out_dir / "job.json"
    job_file.write_text(json.dumps(job), encoding="utf-8")
    env = dict(os.environ, FFMPEG=FFMPEG)
    subprocess.run(["node", str(RENDERER / "render.mjs"), str(job_file), str(out_dir)], check=True, env=env)


def date_label(cfg) -> str:
    try:
        from zoneinfo import ZoneInfo
        now = dt.datetime.now(ZoneInfo(cfg.get("timezone", "Europe/Bucharest")))
    except Exception:  # noqa: BLE001
        now = dt.datetime.now()
    return now.strftime("%A, %-d %B")


# ====================================================================== director
# camera/staging variants per section (must match renderer/scene/scene.js SHOTS) and
# where the headline goes so it never covers the devices.
SHOTS = {
    "hook": {"drop_spin": "top", "rise_turn": "top", "lid_open": "bottom", "macro_pull": "top"},
    "problem": {"orbit_left": "top", "high_angle": "bottom", "screen_push": "bottom"},
    "solution": {"orbit_right": "top", "phone_focus": "top", "side_track": "top"},
    "result": {"duo_front": "top", "low_hero": "top", "phone_result": "top"},
    "cta": {"phone_spin": "top", "duo_cta": "top"},
}
BACKGROUNDS = ["bokeh", "grid", "spot"]
TYPE_STYLES = ["kinetic", "caption", "typewriter"]
TRANSITIONS = ["whip", "zoom", "glitch", "flash"]
PHONE_FINISHES = ["natural", "black", "white", "desert", "blue"]
LAPTOP_FINISHES = ["spaceblack", "silver"]


def make_plan(rng: random.Random, previous: dict | None = None) -> dict:
    """A different look for every video; avoids repeating the previous video's main choices."""
    best = None
    for _ in range(8):
        plan = {sec: rng.choice(list(opts)) for sec, opts in SHOTS.items()}
        plan.update(bg=rng.choice(BACKGROUNDS), type=rng.choice(TYPE_STYLES), transition=rng.choice(TRANSITIONS),
                    finish_phone=rng.choice(PHONE_FINISHES), finish_laptop=rng.choice(LAPTOP_FINISHES))
        if not previous:
            return plan
        same = sum(plan.get(k) == previous.get(k) for k in ("hook", "problem", "solution", "bg", "type", "transition"))
        if best is None or same < best[0]:
            best = (same, plan)
        if same <= 1:
            break
    return best[1]


# ====================================================================== overlay
def _ease_in_out(x):
    x = min(1.0, max(0.0, x))
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


class Overlay:
    """Everything drawn on top of the 3D frames. Built once per worker process."""

    def __init__(self, post: dict, cfg: dict, tl: dict, pal: dict, fps: int, plan: dict | None = None):
        self.post, self.tl, self.fps = post, tl, fps
        self.plan = plan or {}
        self.type_style = self.plan.get("type", "kinetic")
        self.transition = self.plan.get("transition", "whip")
        rgb = pal["_rgb"]
        self.accent, self.accent2 = tuple(rgb["accent"]), tuple(rgb["accent2"])
        white = (255, 255, 255)
        S = tl["sections"]
        self.S = S

        # ---------- headlines (per-word images for kinetic type)
        self.heads = {}
        for sec, text, size, center in (("hook", post["hook"], 112, True), ("problem", post["problem"]["text"], 84, False),
                                        ("result", post["result"], 88, False)):
            self.heads[sec] = self._layout_words(text, size, center, white)
        # caption style: 1-3 word chunks, big, centred (CapCut-like)
        self.chunks = {}
        cap_font = ImageFont.truetype(str(FONT_BOLD), 104)
        for sec, text in (("hook", post["hook"]), ("problem", post["problem"]["text"]), ("result", post["result"])):
            words = parse_rich(text)
            n = max(1, math.ceil(len(words) / 3))
            per = len(words) / n
            groups = [words[round(k * per):round((k + 1) * per)] for k in range(n)]
            groups = [g for g in groups if g]
            imgs = []
            for g in groups:
                im = render_line(g, cap_font, white, self.accent)
                while im.width > W - 60 and cap_font.size > 60:
                    im = render_line(g, ImageFont.truetype(str(FONT_BOLD), int(cap_font.size * 0.85)), white, self.accent)
                    break
                imgs.append(im)
            self.chunks[sec] = imgs
        # typewriter style: whole lines, revealed left to right
        self.lines_img = {}
        for sec, head in self.heads.items():
            rows = {}
            for wimg, x, y in head["words"]:
                rows.setdefault(y, []).append((wimg, x))
            out = []
            for y in sorted(rows):
                xs = rows[y]
                x0 = min(x for _, x in xs)
                x1 = max(x + im.width for im, x in xs)
                hh = max(im.height for im, _ in xs)
                line = Image.new("RGBA", (x1 - x0, hh), (0, 0, 0, 0))
                for im, x in xs:
                    line.alpha_composite(im, (x - x0, 0))
                out.append((line, x0, y))
            self.lines_img[sec] = out

        # ---------- label chips
        chip_font = ImageFont.truetype(str(FONT_SEMI), 32)
        self.labels = {}
        for sec, txt, dot in (("problem", "THE PROBLEM", (255, 77, 109)), ("solution", "THE FIX", self.accent),
                              ("result", "THE RESULT", self.accent)):
            tw = int(chip_font.getlength(txt) + 4 * 3)
            w, h = tw + 110, 76
            glass = Glass(w, h, h // 2, bevel=18, strength=12, shadow=0.25)
            fill = np.zeros((h, w, 4), np.float32)
            img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.ellipse((30, h // 2 - 9, 48, h // 2 + 9), fill=dot + (255,))
            x = 66
            for ch in txt:  # letter-spaced
                d.text((x, h // 2 - 20), ch, font=chip_font, fill=(255, 255, 255, 255))
                x += chip_font.getlength(ch) + 3
            a = np.asarray(img, np.float32)
            fill[..., :3], fill[..., 3] = a[..., :3], a[..., 3] / 255
            self.labels[sec] = (glass, fill)

        # ---------- step cards
        self.cards = []
        nf, tf, df = (ImageFont.truetype(str(FONT_BOLD), 40), ImageFont.truetype(str(FONT_BOLD), 46),
                      ImageFont.truetype(str(FONT_MED), 32))
        cw, ch = W - 120, 178
        for i, s in enumerate(post["solution"]["steps"]):
            glass = Glass(cw, ch, 48, bevel=34, strength=26, tint_alpha=0.34)
            img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            g = _gradient_fill(84, 84, self.accent, self.accent2, 1.0)
            circle = Image.new("L", (84, 84), 0)
            ImageDraw.Draw(circle).ellipse((0, 0, 83, 83), fill=255)
            gi = Image.fromarray(np.clip(g[..., :3], 0, 255).astype(np.uint8)).convert("RGBA")
            gi.putalpha(circle)
            img.alpha_composite(gi, (34, (ch - 84) // 2))
            num = str(i + 1)
            d.text((34 + 42 - nf.getlength(num) / 2, (ch - 84) // 2 + 14), num, font=nf, fill=(7, 16, 24, 255))
            title = self._fit(s["title"], tf, cw - 190)
            d.text((150, 34), title, font=tf, fill=(255, 255, 255, 255))
            desc = self._fit(s["text"], df, cw - 190)
            d.text((150, 98), desc, font=df, fill=(255, 255, 255, 200))
            a = np.asarray(img, np.float32)
            fill = np.zeros((ch, cw, 4), np.float32)
            fill[..., :3], fill[..., 3] = a[..., :3], a[..., 3] / 255
            self.cards.append((glass, fill))
        self.card_size = (cw, ch)

        # ---------- CTA
        self.brand_img = _spaced(cfg["brand"]["name"].upper(), ImageFont.truetype(str(FONT_BOLD), 108), white, self.accent)
        cta_font = ImageFont.truetype(str(FONT_SEMI), 54)
        self.cta_lines = [render_line([(w, False) for w in line.split()], cta_font, white, self.accent)
                          for line in self._wrap(post.get("cta") or cfg["brand"]["call_to_action"], cta_font, W - 200)]
        bw, bh = 520, 130
        self.btn = Glass(bw, bh, bh // 2, bevel=30, strength=24, tint_alpha=0.08, shadow=0.35)
        bimg = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        bf = ImageFont.truetype(str(FONT_BOLD), 52)
        ImageDraw.Draw(bimg).text(((bw - bf.getlength("FOLLOW  →")) / 2, 32), "FOLLOW  →", font=bf, fill=(7, 16, 24, 255))
        bfill = _gradient_fill(bw, bh, self.accent, self.accent2, 0.72)
        ta = np.asarray(bimg, np.float32)
        k = ta[..., 3:4] / 255
        bfill[..., :3] = bfill[..., :3] * (1 - k) + ta[..., :3] * k
        bfill[..., 3:4] = np.maximum(bfill[..., 3:4], k)
        self.btn_fill = bfill

        # ---------- persistent UI
        self.bar = Glass(W - 140, 18, 9, bevel=8, strength=5, blur=6, shadow=0.15, sheen=False)
        self.handle_img = _text_img(cfg["brand"]["handle"], ImageFont.truetype(str(FONT_MED), 36), (255, 255, 255, 235))
        self.handle_pill = Glass(self.handle_img.width + 50, 76, 38, bevel=18, strength=12, shadow=0.2)

        # ---------- film look
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.sqrt(((xx - W / 2) / (W * 0.62)) ** 2 + ((yy - H * 0.46) / (H * 0.6)) ** 2)
        self.vignette = (1 - 0.5 * np.clip(r - 0.55, 0, 1) ** 1.3).astype(np.float32)[..., None]
        self.grain = np.random.default_rng(3).normal(0, 3.5, (H + 64, W, 1)).astype(np.float32)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _fit(text, font, max_w):
        text = str(text).replace("*", "")
        while font.getlength(text) > max_w and len(text) > 4:
            text = text[:-2].rstrip() + "…"
            text = text.replace("……", "…")
        return text

    @staticmethod
    def _wrap(text, font, max_w):
        lines, cur = [], ""
        for w in str(text).replace("*", "").split():
            t = f"{cur} {w}".strip()
            if cur and font.getlength(t) > max_w:
                lines.append(cur)
                cur = w
            else:
                cur = t
        return lines + ([cur] if cur else [])

    def _layout_words(self, text, size, center, color):
        size0 = size
        while True:
            font = ImageFont.truetype(str(FONT_BOLD), size)
            words = parse_rich(text)
            space = font.getlength(" ")
            max_w = W - 140
            lines, cur, cw = [], [], 0
            for w, hl in words:
                ww = font.getlength(w)
                if cur and cw + space + ww > max_w:
                    lines.append(cur)
                    cur, cw = [], 0
                cw += (space if cur else 0) + ww
                cur.append((w, hl))
            if cur:
                lines.append(cur)
            if len(lines) <= 4 or size < 56:
                break
            size -= 6
        out, lh = [], int(size * 1.08)
        for li, line in enumerate(lines):
            lw = sum(font.getlength(w) for w, _ in line) + space * (len(line) - 1)
            x = (W - lw) / 2 if center else 70
            for w, hl in line:
                img = render_line([(w, hl)], font, color, self.accent)
                out.append((img, int(x) - 30, li * lh - 30))
                x += font.getlength(w) + space
        return {"words": out, "height": len(lines) * lh, "size": size0}

    # ------------------------------------------------------------------ frame
    def section(self, t):
        for k, s in self.S.items():
            if s["start"] <= t < s["start"] + s["dur"]:
                return k
        return "cta"

    def compose(self, frame_path: Path, i: int) -> bytes:
        t = i / self.fps
        img = Image.open(frame_path).transpose(Image.FLIP_TOP_BOTTOM)
        if img.size != (W, H):
            img = img.resize((W, H), Image.LANCZOS)
        # transition around section cuts (style chosen per video)
        tk = 0.0
        for k, s in self.S.items():
            if s["start"] == 0:
                continue
            d = abs(t - s["start"])
            if d < 0.22:
                tk = max(tk, 1 - d / 0.22)
        blur = flash = 0.0
        mode = self.transition
        if tk > 0:
            if mode == "whip":
                blur, flash = tk * 18, max(0.0, tk - 0.45) * 0.4
            elif mode == "zoom":
                z = 1 + 0.22 * tk
                cw_, ch_ = int(W / z), int(H / z)
                img = img.crop(((W - cw_) // 2, (H - ch_) // 2, (W + cw_) // 2, (H + ch_) // 2)).resize((W, H), Image.BILINEAR)
                blur = tk * 8
            elif mode == "flash":
                flash = tk ** 1.5 * 0.65
            else:  # glitch: RGB split + sliced offsets
                a = np.asarray(img).copy()
                sh = int(26 * tk)
                a[..., 0] = np.roll(a[..., 0], sh, axis=1)
                a[..., 2] = np.roll(a[..., 2], -sh, axis=1)
                rng = np.random.default_rng(i)
                for _ in range(int(8 * tk)):
                    y0 = int(rng.integers(0, H - 80)); hgt = int(rng.integers(12, 80))
                    a[y0:y0 + hgt] = np.roll(a[y0:y0 + hgt], int(rng.integers(-60, 60)), axis=1)
                img = Image.fromarray(a)
                flash = tk * 0.12
        if blur > 0.5:
            small = img.resize((W // 4, H // 4), Image.BILINEAR).filter(ImageFilter.GaussianBlur(blur / 4))
            img = Image.blend(img, small.resize((W, H), Image.BILINEAR), min(1.0, blur / 10))
        f = np.asarray(img, np.float32)
        f = f * self.vignette
        if flash > 0:
            f = f + (255 - f) * flash
        off = (i * 13) % 64
        f = np.clip(f + self.grain[off:off + H], 0, 255).astype(np.uint8)
        f = np.ascontiguousarray(f)

        sec = self.section(t)
        S = self.S[sec]
        lt, dur = t - S["start"], S["dur"]

        # progress bar + handle
        p = min(1.0, t / self.tl["total"])
        fill = np.zeros((18, self.bar.w, 4), np.float32)
        fw = int(self.bar.w * p)
        if fw > 0:
            fill[:, :fw] = _gradient_fill(fw, 18, self.accent, self.accent2, 0.95)
        self.bar.draw(f, 70, 92, 1.0, t, extra=fill)
        if sec != "cta":
            hp = self.handle_pill
            hx, hy = (W - hp.w) // 2, H - 200
            hp.draw(f, hx, hy, 1.0, t)
            _paste_rgba(f, self.handle_img, hx + 25, hy + 10)

        # label chip
        if sec in self.labels:
            glass, chip = self.labels[sec]
            k = ease_out_back(lt / 0.5)
            out = min(1.0, max(0.0, (lt - (dur - 0.25)) / 0.25))
            a = min(1.0, max(0.0, k)) * (1 - out)
            glass.draw(f, 70 - int((1 - k) * 60), 160, a, t, extra=chip)

        # headline (style chosen per video)
        zone = SHOTS.get(sec, {}).get(self.plan.get(sec), "top")
        if sec in self.heads and self.type_style == "caption":
            chunks = self.chunks[sec]
            span = max(0.4, (dur - 0.35) / len(chunks))
            j = min(len(chunks) - 1, int(max(0.0, lt - 0.15) / span))
            im = chunks[j]
            lk = (lt - 0.15 - j * span) / 0.22
            k = ease_out_back(lk)
            out = min(1.0, max(0.0, (lt - (dur - 0.2)) / 0.2))
            a = min(1.0, max(0.0, k)) * (1 - out)
            if a > 0.01:
                s_ = 0.75 + 0.25 * min(1.0, max(0.0, k))
                im2 = im.resize((max(1, int(im.width * s_)), max(1, int(im.height * s_))), Image.BICUBIC) if s_ < 0.995 else im
                cy = 470 if zone == "top" else H - 640
                pw, ph = im2.width - 20, im2.height - 40
                pill = np.zeros((ph, pw, 4), np.float32)
                pill[..., :3] = 0; pill[..., 3] = 0.5
                mask = Image.new("L", (pw, ph), 0)
                ImageDraw.Draw(mask).rounded_rectangle((0, 0, pw - 1, ph - 1), radius=ph // 2, fill=255)
                pa = np.asarray(mask, np.float32) / 255 * 0.5 * a
                _blend(f, (W - pw) // 2, cy - ph // 2, np.zeros(3, np.float32), pa)
                _paste_rgba(f, im2, (W - im2.width) // 2, cy - im2.height // 2, a)
        elif sec in self.heads and self.type_style == "typewriter":
            rows = self.lines_img[sec]
            top = 280 if zone == "top" else H - 420 - self.heads[sec]["height"]
            out = min(1.0, max(0.0, (lt - (dur - 0.25)) / 0.25))
            total_w = sum(im.width for im, _, _ in rows) or 1
            revealed = max(0.0, (lt - 0.15)) * 1500  # px per second
            for im, x0, y in rows:
                wpx = int(min(im.width, max(0.0, revealed)))
                revealed -= im.width
                if wpx <= 0:
                    continue
                _paste_rgba(f, im.crop((0, 0, wpx, im.height)), x0, top + y, 1 - out)
                if wpx < im.width or revealed < 0 or (revealed < 400 and int(lt * 3) % 2 == 0):
                    cx = x0 + wpx - 22
                    cur = _gradient_fill(10, int(im.height * 0.55), self.accent, self.accent2, 1.0)
                    if wpx < im.width or (im is rows[-1][0]):
                        _blend(f, cx, top + y + int(im.height * 0.22), cur[..., :3], cur[..., 3] * (1 - out))
        elif sec in self.heads:
            head = self.heads[sec]
            top = (270 if sec == "hook" else 280) if zone == "top" else H - 420 - head["height"]
            out = min(1.0, max(0.0, (lt - (dur - 0.28)) / 0.28))
            for j, (wimg, x, y) in enumerate(head["words"]):
                k = ease_out_cubic((lt - 0.2 - j * 0.055) / 0.42)
                a = k * (1 - out)
                if a <= 0.01:
                    continue
                dy = int((1 - k) * 70 - out * 40)
                _paste_rgba(f, wimg, x, top + y + dy, a)

        # step cards
        if sec == "solution":
            cw, chh = self.card_size
            steps = self.tl["steps"]
            out = min(1.0, max(0.0, (lt - (dur - 0.25)) / 0.25))
            base_y = H - 330 - len(self.cards) * (chh + 22)
            for j, (glass, fill_) in enumerate(self.cards):
                st = steps[j]["start"]
                k = ease_out_back((t - st) / 0.5)
                if k <= 0:
                    continue
                active = t >= st and (j == len(steps) - 1 or t < steps[j + 1]["start"])
                a = min(1.0, k) * (1.0 if active else 0.62) * (1 - out)
                glass.draw(f, 60 + int((1 - k) * 180), base_y + j * (chh + 22), a, t, extra=fill_)

        # CTA
        if sec == "cta":
            k = ease_out_back((lt - 0.15) / 0.6)
            if k > 0:
                bi = self.brand_img
                s = 0.8 + 0.2 * k
                im = bi.resize((max(1, int(bi.width * s)), max(1, int(bi.height * s))), Image.BICUBIC)
                _paste_rgba(f, im, (W - im.width) // 2, 230 - im.height // 2 + 40, min(1.0, k))
            y = 330
            for j, li in enumerate(self.cta_lines):
                k2 = ease_out_cubic((lt - 0.4 - j * 0.08) / 0.5)
                if k2 > 0:
                    _paste_rgba(f, li, (W - li.width) // 2, y + int((1 - k2) * 30), k2)
                y += li.height - 50
            bk = ease_out_back((lt - 0.7) / 0.5)
            if bk > 0:
                fill2 = self.btn_fill.copy()
                fill2[..., 3] = np.clip(fill2[..., 3] * (0.85 + 0.25 * (0.5 + 0.5 * math.sin(lt * 7))), 0, 1)
                self.btn.draw(f, (W - self.btn.w) // 2, H - 360 + int((1 - bk) * 60), min(1.0, bk), t * 2.5, extra=fill2)
        return f.tobytes()


# ====================================================================== multiprocessing
_OV = None


def _init(post, cfg, tl, pal, fps, plan):
    global _OV
    _OV = Overlay(post, cfg, tl, pal, fps, plan)


def _work(args):
    path, i = args
    return _OV.compose(Path(path), i)


def render_cinematic_reel(post: dict, cfg: dict, out: Path, work: Path, seed: int,
                          previous_plan: dict | None = None) -> Path:
    rng = random.Random(seed)
    plan = make_plan(rng, previous_plan)
    post["_plan"] = plan
    fps = int(cfg["video"].get("fps_cinematic", 24))
    pal_name, pal = pick_palette(cfg, rng)
    job = {
        "mode": "reel", "width": W, "height": H, "fps": fps, "seed": seed,
        "finish": plan["finish_phone"], "finish_phone": plan["finish_phone"], "finish_laptop": plan["finish_laptop"],
        "plan": plan, "date_label": date_label(cfg),
        "brand": {"name": cfg["brand"]["name"], "handle": cfg["brand"]["handle"]},
        "palette": {k: v for k, v in pal.items() if not k.startswith("_")},
        "render_scale": cfg["video"].get("render_scale", 0.6667),
        "reel": {"hook": post["hook"], "app_name": post.get("app_name", "Workspace"),
                 "problem": post["problem"], "solution": post["solution"], "result": post["result"],
                 "cta": post.get("cta", "")},
    }
    plan["palette"] = pal_name
    print(f"[cinematic] palette {pal_name}, plan {json.dumps(plan)}")
    rdir = work / "3d"
    run_renderer(job, rdir)
    tl = json.loads((rdir / "timeline.json").read_text())
    frames = sorted((rdir / "frames").glob("*.jpg"))
    total = round(len(frames) / fps, 3)
    audio = build_soundtrack(total, [(t, n) for t, n in tl["cues"]], cfg, work / "audio.wav", seed=seed,
                             style="cinematic")
    cmd = [FFMPEG, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps),
           "-i", "pipe:0", "-i", str(audio), "-map", "0:v", "-map", "1:a", "-shortest",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-maxrate", "10M", "-bufsize", "20M",
           "-pix_fmt", "yuv420p", "-profile:v", "high",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    procs = max(1, min(os.cpu_count() or 2, 6))
    pal_clean = dict(pal)
    try:
        with get_context("fork").Pool(procs, initializer=_init, initargs=(post, cfg, tl, pal_clean, fps, plan)) as pool:
            for n, buf in enumerate(pool.imap(_work, [(str(p), i) for i, p in enumerate(frames)], chunksize=4)):
                proc.stdin.write(buf)
                if n % 120 == 0:
                    print(f"[cinematic] composited {n}/{len(frames)}")
    finally:
        proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed while encoding the cinematic reel")
    shutil.rmtree(rdir / "frames", ignore_errors=True)
    print(f"[cinematic] saved {out}")
    return out
