"""Light theme ("alb murdar" / warm off-white paper): honest, editorial, lots of motion design.

Used by both reel styles:
  * cinematic  -> 3D iPhone/Mac rendered in a bright studio, this overlay on top
  * liquid     -> paper background with soft pastel liquid blobs + refractive bubbles

Motion design: masked word reveals, marker highlights that swipe behind key words,
drawn lines/arrows, rotating dashed rings, orbiting dots, check marks that draw
themselves, sparkle bursts, accent wipe transitions, punch-ins, tap ripples,
drifting dot grid, word-synced subtitles.
"""
import base64
import io
import math
import os
import random
import subprocess
from multiprocessing import get_context
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .audio import build_soundtrack
from .ff import FFMPEG
from .glass import Glass, _blend, _paste_rgba
from .render import FONT_BOLD, FONT_MED, FONT_SEMI, ease_out_back, ease_out_cubic, parse_rich

W, H = 1080, 1920
PAPER = (243, 239, 232)
INK = (22, 22, 26)
WHITE = (255, 255, 255)

# accents that read well on warm paper (accent2 = softer partner colour)
LIGHT_PALETTES = {
    "cobalt": {"accent": (38, 86, 255), "accent2": (120, 92, 255), "blobs": [(170, 190, 255), (210, 190, 255), (180, 230, 255)]},
    "tangerine": {"accent": (255, 96, 36), "accent2": (255, 170, 60), "blobs": [(255, 205, 170), (255, 225, 160), (255, 190, 200)]},
    "emerald": {"accent": (0, 150, 105), "accent2": (40, 190, 170), "blobs": [(170, 230, 205), (190, 235, 230), (215, 240, 190)]},
    "violet": {"accent": (112, 64, 255), "accent2": (220, 80, 200), "blobs": [(215, 195, 255), (250, 195, 235), (195, 210, 255)]},
    "coral": {"accent": (238, 64, 98), "accent2": (255, 140, 90), "blobs": [(255, 195, 205), (255, 215, 185), (240, 200, 230)]},
}


def _hex(c):
    return "#%02x%02x%02x" % tuple(int(x) for x in c)


def pick_light_palette(cfg: dict, rng: random.Random) -> tuple[str, dict]:
    name = cfg["video"].get("palette", "random")
    if name not in LIGHT_PALETTES:
        name = rng.choice(list(LIGHT_PALETTES))
    p = LIGHT_PALETTES[name]
    # palette for the 3D scene (job.palette)
    job = {"bg": [_hex((226, 220, 210)), _hex((246, 243, 237))], "accent": _hex(p["accent"]), "accent2": _hex(p["accent2"]),
           "glow": [_hex(c) for c in p["blobs"]], "_rgb": p}
    return name, job


def _clamp(x):
    return min(1.0, max(0.0, x))


def _mix(a, b, k):
    return tuple(int(a[i] * (1 - k) + b[i] * k) for i in range(3))


def rounded(w, h, r, fill):
    w, h = max(2, int(w)), max(2, int(h))
    r = min(r, w // 2, h // 2)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=fill)
    return im


def shadow(w, h, r, blur=26, alpha=70, spread=0):
    w, h = max(2, int(w)), max(2, int(h))
    r = min(r, w // 2, h // 2)
    m = blur * 2
    im = Image.new("RGBA", (w + 2 * m, h + 2 * m), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle((m - spread, m - spread, m + w + spread, m + h + spread), radius=r, fill=(30, 25, 20, alpha))
    return im.filter(ImageFilter.GaussianBlur(blur)), m


def card(w, h, r=48, fill=(255, 255, 255, 255), border=(0, 0, 0, 14)):
    """White paper card with soft drop shadow (returns image incl. shadow margin and the margin)."""
    sh, m = shadow(w, h, r)
    out = sh.copy()
    face = rounded(w, h, r, fill)
    ImageDraw.Draw(face).rounded_rectangle((0, 0, w - 1, h - 1), radius=r, outline=border, width=2)
    out.alpha_composite(face, (m, m - 10))
    return out, m


def text(t, font, color, pad=6):
    w = int(font.getlength(t)) + pad * 2
    asc, desc = font.getmetrics()
    im = Image.new("RGBA", (w, asc + desc + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((pad, pad), t, font=font, fill=color)
    return im


def spaced(t, font, color, spacing=10):
    ws = [font.getlength(c) for c in t]
    asc, desc = font.getmetrics()
    im = Image.new("RGBA", (int(sum(ws) + spacing * len(t)) + 12, asc + desc + 12), (0, 0, 0, 0))
    d, x = ImageDraw.Draw(im), 6
    for c, cw in zip(t, ws):
        d.text((x, 6), c, font=font, fill=color)
        x += cw + spacing
    return im


def _decode(u):
    try:
        return Image.open(io.BytesIO(base64.b64decode(u.split(",", 1)[1]))).convert("RGB")
    except Exception:  # noqa: BLE001
        return None


# ====================================================================== the overlay / composer
class LightReel:
    """Draws every frame of a light-theme reel. `mode` = 'cinematic' (3D frames given) or 'liquid'."""

    def __init__(self, post, cfg, tl, pal, fps, mode, seed=1, words=None):
        self.post, self.tl, self.S, self.fps, self.mode = post, tl, tl["sections"], fps, mode
        rgb = pal["_rgb"]
        self.accent, self.accent2 = tuple(rgb["accent"]), tuple(rgb["accent2"])
        self.marker = _mix(self.accent, WHITE, 0.62)
        rng = random.Random(seed)
        acc = (cfg.get("_account") or {}).get("assets") or {}
        if not acc.get("avatar_bytes"):
            from .account import local_logo
            acc = dict(acc, avatar_bytes=local_logo()[0])
        from .account import logo_png
        self.logo = logo_png(acc["avatar_bytes"], 200) if acc.get("avatar_bytes") else None
        self.logo_sm = logo_png(acc["avatar_bytes"], 54) if acc.get("avatar_bytes") else None
        self.handle = "@" + acc["username"] if acc.get("username") else cfg["brand"]["handle"]

        # ---- paper background (with faint grain) + drifting dot grid
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.sqrt(((xx - W / 2) / (W * 0.7)) ** 2 + ((yy - H * 0.45) / (H * 0.65)) ** 2)
        base = np.array(PAPER, np.float32) * (1 - 0.06 * np.clip(r - 0.4, 0, 1))[..., None]
        noise = np.random.default_rng(seed).normal(0, 2.2, (H, W, 1)).astype(np.float32)
        self.paper = np.clip(base + noise, 0, 255).astype(np.uint8)
        self.vign = (1 - 0.07 * np.clip(r - 0.55, 0, 1) ** 1.2).astype(np.float32)[..., None]
        dots = Image.new("RGBA", (W + 64, 560), (0, 0, 0, 0))
        dd = ImageDraw.Draw(dots)
        for y in range(8, 560, 32):
            for x in range(8, W + 64, 32):
                dd.ellipse((x - 2, y - 2, x + 2, y + 2), fill=INK + (26,))
        fade = Image.linear_gradient("L").resize((W + 64, 560))
        dots.putalpha(Image.fromarray((np.asarray(dots.getchannel("A"), np.float32) * (1 - np.asarray(fade, np.float32) / 255)).astype(np.uint8)))
        self.dots = dots

        # ---- liquid mode: pastel blobs + refractive bubbles
        if mode == "liquid":
            self.blobs = [{"c": np.array(rng.choice(rgb["blobs"]), np.float32), "x": rng.uniform(0.1, 0.9), "y": rng.uniform(0.1, 0.9),
                           "ax": rng.uniform(0.08, 0.22), "ay": rng.uniform(0.08, 0.2), "f": rng.uniform(0.15, 0.35),
                           "ph": rng.uniform(0, 6.3), "r": rng.uniform(0.22, 0.36)} for _ in range(6)]
            lw, lh = W // 6, H // 6
            gy, gx = np.mgrid[0:lh, 0:lw].astype(np.float32)
            self._g = (gx / lw, gy / lh * (H / W), lw, lh)
            self.bubbles = []
            for rad in (120, 70, 95, 52, 150, 44):
                self.bubbles.append({"g": Glass(2 * rad, 2 * rad, rad, bevel=rad, strength=-rad * 0.5, blur=0, tint=(255, 255, 255),
                                                tint_alpha=0.06, gain=1.03, rim=1.3, specular_dot=True, shadow=0.0, sheen=False),
                                     "r": rad, "x0": rng.uniform(0.05, 0.95) * W, "y0": rng.uniform(0, H),
                                     "sp": rng.uniform(20, 48), "ph": rng.uniform(0, 6.3)})

        # ---- headlines (per word images for masked reveals)
        self.heads = {}
        for sec, t, size in (("hook", post["hook"], 116), ("problem", post["problem"]["text"], 82), ("result", post["result"], 88)):
            self.heads[sec] = self._words(t, size)

        # ---- chips (ink pills)
        cf = ImageFont.truetype(str(FONT_SEMI), 30)
        self.chips = {}
        for sec, label, dot in (("problem", "THE PROBLEM", (235, 64, 80)), ("solution", "THE FIX", self.accent), ("result", "THE RESULT", self.accent)):
            lab = spaced(label, cf, WHITE + (255,), 4)
            w = lab.width + 88
            im = rounded(w, 70, 35, INK + (255,))
            ImageDraw.Draw(im).ellipse((26, 26, 44, 44), fill=dot + (255,))
            im.alpha_composite(lab, (58, (70 - lab.height) // 2))
            self.chips[sec] = im

        # ---- alert cards (problem)
        af, nf = ImageFont.truetype(str(FONT_SEMI), 38), ImageFont.truetype(str(FONT_MED), 25)
        self.alerts = []
        for a in post["problem"].get("alerts", [])[:3]:
            im, m = card(W - 170, 128, 34)
            d = ImageDraw.Draw(im)
            d.rounded_rectangle((m + 26, m + 18, m + 26 + 80, m + 18 + 80), radius=22, fill=(235, 64, 80, 255))
            d.text((m + 54, m + 22), "!", font=ImageFont.truetype(str(FONT_BOLD), 56), fill=WHITE + (255,))
            d.text((m + 132, m + 18), (post.get("app_name") or "WORK").upper(), font=nf, fill=INK + (130,))
            d.text((m + 132, m + 50), str(a)[:34], font=af, fill=INK + (255,))
            self.alerts.append((im, m))

        # ---- step cards
        tf, df, numf = ImageFont.truetype(str(FONT_BOLD), 48), ImageFont.truetype(str(FONT_MED), 31), ImageFont.truetype(str(FONT_BOLD), 42)
        self.cards, self.card_h = [], 188
        for i, s in enumerate(post["solution"]["steps"]):
            im, m = card(W - 140, self.card_h, 44)
            d = ImageDraw.Draw(im)
            d.text((m + 150, m + 34), self._fit(s["title"], tf, W - 340), font=tf, fill=INK + (255,))
            d.text((m + 150, m + 104), self._fit(s["text"], df, W - 340), font=df, fill=INK + (150,))
            self.cards.append((im, m))
        self.numf = numf

        # ---- CTA
        self.brand = spaced(cfg["brand"]["name"].upper(), ImageFont.truetype(str(FONT_BOLD), 84), INK + (255,), 12)
        self.cta_line = text(post.get("cta") or cfg["brand"]["call_to_action"], ImageFont.truetype(str(FONT_SEMI), 46), INK + (190,))
        bf = ImageFont.truetype(str(FONT_BOLD), 52)
        self.btn = rounded(560, 132, 66, self.accent + (255,))
        t1 = text("FOLLOW  →", bf, WHITE + (255,))
        self.btn.alpha_composite(t1, ((560 - t1.width) // 2, (132 - t1.height) // 2))
        self.btn_done = rounded(560, 132, 66, INK + (255,))
        t2 = text("FOLLOWING ✓", bf, WHITE + (255,))
        self.btn_done.alpha_composite(t2, ((560 - t2.width) // 2, (132 - t2.height) // 2))
        self.btn_sh = shadow(560, 132, 66, 24, 80)

        if mode == "liquid":  # profile card with the real account (cinematic shows it on the 3D phone)
            pw, ph = W - 140, 820
            prof, pm = card(pw, ph, 56)
            if self.logo:
                prof.alpha_composite(self.logo.resize((140, 140), Image.LANCZOS), (pm + 44, pm + 34))
            d = ImageDraw.Draw(prof)
            d.text((pm + 210, pm + 46), acc.get("name") or cfg["brand"]["name"], font=ImageFont.truetype(str(FONT_BOLD), 48), fill=INK + (255,))
            d.text((pm + 210, pm + 106), self.handle, font=ImageFont.truetype(str(FONT_MED), 31), fill=INK + (140,))

            def fmt(n):
                return "—" if n is None else (f"{n / 1e3:.1f}K" if n >= 1e4 else str(n))
            sf, lf = ImageFont.truetype(str(FONT_BOLD), 34), ImageFont.truetype(str(FONT_MED), 23)
            for k, (n, lab) in enumerate(((acc.get("posts"), "posts"), (acc.get("followers"), "followers"))):
                d.text((pm + 210 + k * 180, pm + 148), fmt(n), font=sf, fill=INK + (255,))
                d.text((pm + 210 + k * 180, pm + 188), lab, font=lf, fill=INK + (130,))
            tiles = [t for t in (_decode(u) for u in acc.get("grid", [])) if t][:6]
            tw = (pw - 88 - 24) // 3
            for k in range(6):
                x, y = pm + 44 + (k % 3) * (tw + 12), pm + 250 + (k // 3) * (tw + 12)
                mask = rounded(tw, tw, 22, (255, 255, 255, 255)).getchannel("A")
                if k < len(tiles):
                    t0 = tiles[k]
                    s0 = max(tw / t0.width, tw / t0.height)
                    t1_ = t0.resize((int(t0.width * s0) + 1, int(t0.height * s0) + 1), Image.LANCZOS)
                    t1_ = t1_.crop(((t1_.width - tw) // 2, (t1_.height - tw) // 2, (t1_.width - tw) // 2 + tw, (t1_.height - tw) // 2 + tw))
                else:
                    t1_ = Image.new("RGB", (tw, tw), _mix(self.accent, WHITE, 0.75 - 0.1 * (k % 3)))
                prof.paste(t1_, (x, y - 10), mask)
            self.prof = (prof, pm)

        # ---- persistent UI
        hf = ImageFont.truetype(str(FONT_SEMI), 34)
        ht = text(self.handle, hf, INK + (230,))
        pw_ = ht.width + 44 + (64 if self.logo_sm else 0)
        self.pill, self.pill_m = card(pw_, 78, 39)
        x0 = self.pill_m + (14 if self.logo_sm else 22)
        if self.logo_sm:
            self.pill.alpha_composite(self.logo_sm.resize((50, 50), Image.LANCZOS), (x0, self.pill_m + 4))
            x0 += 62
        self.pill.alpha_composite(ht, (x0, self.pill_m - 10 + (78 - ht.height) // 2))

        from .subtitles import Subtitles
        self.subs = Subtitles(words or [], self.accent, theme="light")
        self.alert_times = [c[0] for c in tl.get("cues", []) if c[1] == "alert"] or tl.get("alerts", [])

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _fit(t, font, max_w):
        t = str(t).replace("*", "")
        while font.getlength(t) > max_w and len(t) > 4:
            t = t[:-2].rstrip() + "…"
        return t.replace("……", "…")

    def _words(self, t, size):
        while True:
            font = ImageFont.truetype(str(FONT_BOLD), size)
            words, space, max_w = parse_rich(t), font.getlength(" "), W - 150
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
        asc, desc = font.getmetrics()
        lh, out = int(size * 1.12), []
        for li, line in enumerate(lines):
            x = 72
            for w, hl in line:
                im = text(w, font, INK + (255,), pad=0)
                out.append({"im": im, "x": int(x), "y": li * lh, "w": int(font.getlength(w)), "h": asc + desc, "hl": hl})
                x += font.getlength(w) + space
        return {"words": out, "h": len(lines) * lh, "size": size}

    def section(self, t):
        for k, s in self.S.items():
            if s["start"] <= t < s["start"] + s["dur"]:
                return k
        return "cta"

    def _headline(self, f, head, top, lt, out, delay=0.15):
        """Masked reveal (words rise out of their baseline) + marker swipe behind key words."""
        if self.mode == "cinematic":  # paper panel behind the text so it reads over any 3D shot
            k = ease_out_cubic((lt - delay + 0.12) / 0.4)
            if k > 0:
                if "panel" not in head:
                    pw = max(w["x"] + w["w"] for w in head["words"]) - 72 + 80
                    head["panel"] = card(pw, head["h"] + 56, 36, fill=(255, 255, 255, 236))
                im, m = head["panel"]
                cw = max(1, int((im.width - 2 * m) * k))
                _paste_rgba(f, im.crop((0, 0, cw + 2 * m, im.height)), 72 - 40 - m, top - 26 - m - int(out * 40), (1 - out))
        for j, w in enumerate(head["words"]):
            k = ease_out_cubic((lt - delay - j * 0.06) / 0.45)
            if k <= 0:
                continue
            x, y, im = w["x"], top + w["y"] - int(out * 40), w["im"]
            a = 1 - out
            if w["hl"]:
                mk = ease_out_cubic((lt - delay - j * 0.06 - 0.3) / 0.35)
                if mk > 0:
                    mw = int((w["w"] + 24) * mk)
                    bar = np.full((int(w["h"] * 0.42), max(1, mw), 3), self.marker, np.float32)
                    _blend(f, x - 12, y + int(w["h"] * 0.5), bar, np.full(bar.shape[:2], 0.95 * a, np.float32))
            dy = int((1 - k) * im.height)
            vis = im.height - dy
            if vis > 0:
                _paste_rgba(f, im.crop((0, 0, im.width, vis)), x, y + dy, a)

    def _ring(self, f, cx, cy, q, color, rmin=40, rmax=170, width=8):
        if not 0 <= q < 1:
            return
        rad = int(rmin + (rmax - rmin) * ease_out_cubic(q))
        im = Image.new("RGBA", (rad * 2 + 20, rad * 2 + 20), (0, 0, 0, 0))
        ImageDraw.Draw(im).ellipse((10, 10, rad * 2 + 10, rad * 2 + 10), outline=color + (int(220 * (1 - q)),), width=max(2, int(width * (1 - q))))
        _paste_rgba(f, im, cx - rad - 10, cy - rad - 10)

    def _dashed_ring(self, f, cx, cy, rad, t, a, color):
        im = Image.new("RGBA", (rad * 2 + 20, rad * 2 + 20), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        rot = t * 25
        for k in range(36):
            st = rot + k * 10
            d.arc((10, 10, rad * 2 + 10, rad * 2 + 10), st, st + 5, fill=color + (int(160 * a),), width=4)
        _paste_rgba(f, im, cx - rad - 10, cy - rad - 10)

    def _sparkles(self, f, cx, cy, q, color, n=8, spread=260):
        if not 0 <= q < 1:
            return
        for k in range(n):
            ang = k / n * math.tau + 0.3
            dist = spread * ease_out_cubic(q) * (0.6 + 0.4 * ((k * 37) % 10) / 10)
            x, y = cx + math.cos(ang) * dist, cy + math.sin(ang) * dist
            s = int(26 * (1 - q) + 6)
            im = Image.new("RGBA", (s * 2 + 4, s * 2 + 4), (0, 0, 0, 0))
            c = s + 2
            ImageDraw.Draw(im).polygon([(c, c - s), (c + s * 0.22, c - s * 0.22), (c + s, c), (c + s * 0.22, c + s * 0.22),
                                        (c, c + s), (c - s * 0.22, c + s * 0.22), (c - s, c), (c - s * 0.22, c - s * 0.22)],
                                       fill=(color if k % 2 else self.accent2) + (int(255 * (1 - q)),))
            _paste_rgba(f, im, int(x) - c, int(y) - c)

    def _check(self, f, cx, cy, r, prog, color=WHITE, width=16):
        if prog <= 0:
            return
        pts = [(-0.45, 0.02), (-0.12, 0.33), (0.48, -0.32)]
        total = [(pts[i], pts[i + 1]) for i in range(2)]
        im = Image.new("RGBA", (r * 2, r * 2), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        seg = prog * 2
        for i, (p0, p1) in enumerate(total):
            k = _clamp(seg - i)
            if k <= 0:
                break
            x0, y0 = r + p0[0] * r, r + p0[1] * r
            x1, y1 = x0 + (r + p1[0] * r - x0) * k, y0 + (r + p1[1] * r - y0) * k
            d.line([(x0, y0), (x1, y1)], fill=color + (255,), width=width, joint="curve")
        _paste_rgba(f, im, cx - r, cy - r)

    # ------------------------------------------------------------------ background
    def _liquid_bg(self, t):
        gx, gy, lw, lh = self._g
        img = np.zeros((lh, lw, 3), np.float32)
        wsum = np.zeros((lh, lw, 1), np.float32)
        for b in self.blobs:
            cx = b["x"] + b["ax"] * math.sin(t * b["f"] + b["ph"])
            cy = (b["y"] + b["ay"] * math.cos(t * b["f"] * 0.8 + b["ph"])) * (H / W)
            g = np.exp(-((gx - cx) ** 2 + (gy - cy) ** 2) / b["r"] ** 2)[..., None]
            img += g * b["c"]
            wsum += g
        a = np.clip(wsum * 0.75, 0, 0.85)
        col = img / np.maximum(wsum, 1e-3)
        small = (np.array(PAPER, np.float32) * (1 - a) + col * a).astype(np.uint8)
        return np.asarray(Image.fromarray(small).resize((W, H), Image.BICUBIC))

    # ------------------------------------------------------------------ frame
    def compose(self, i: int, frame_path: Path | None = None) -> bytes:
        t = i / self.fps
        sec = self.section(t)
        S = self.S[sec]
        lt, dur = t - S["start"], S["dur"]

        if self.mode == "cinematic":
            img = Image.open(frame_path).transpose(Image.FLIP_TOP_BOTTOM)
            z = 1 + 0.06 * (1 - ease_out_cubic(lt / 0.4)) if lt < 0.4 else 1.0
            if z > 1.001:
                iw, ih = img.size
                cw, ch = int(iw / z), int(ih / z)
                img = img.crop(((iw - cw) // 2, (ih - ch) // 2, (iw + cw) // 2, (ih + ch) // 2))
            if img.size != (W, H):
                img = img.resize((W, H), Image.LANCZOS)
            f = np.asarray(img, np.float32)
        else:
            f = np.asarray(self._liquid_bg(t), np.float32)
            f = f * 0.55 + self.paper.astype(np.float32) * 0.45
        f = np.ascontiguousarray(np.clip(f * self.vign, 0, 255).astype(np.uint8))

        # drifting dot grid (top, parallax)
        off = int(t * 14) % 32
        _paste_rgba(f, self.dots.crop((off, 0, off + W, 560)), 0, 0, 0.9)

        if self.mode == "liquid":
            for b in self.bubbles:
                r = b["r"]
                y = (b["y0"] - b["sp"] * t) % (H + 4 * r) - 2 * r
                b["g"].draw(f, b["x0"] + 36 * math.sin(t * 0.6 + b["ph"]) - r, y - r, 1.0, t)

        out = _clamp((lt - (dur - 0.3)) / 0.3) if sec != "cta" else 0.0

        # progress bar
        if sec != "cta":
            p = min(1.0, t / self.tl["total"])
            _blend(f, 70, 96, np.array(INK, np.float32), np.full((8, W - 140), 0.10, np.float32))
            fw = int((W - 140) * p)
            if fw:
                _blend(f, 70, 96, np.array(self.accent, np.float32), np.full((8, fw), 1.0, np.float32))
            # handle pill
            _paste_rgba(f, self.pill, (W - self.pill.width) // 2, H - 230)

        if sec in self.chips:
            kc = ease_out_back(lt / 0.5)
            _paste_rgba(f, self.chips[sec], 70 - int((1 - min(1.0, kc)) * 80), 150, _clamp(kc) * (1 - out))

        zone_top = 260
        if sec == "hook":
            head = self.heads["hook"]
            top = zone_top + 20 if self.mode == "cinematic" else (H - head["h"]) // 2 - 220
            if self.mode == "liquid":  # big dashed ring + orbiting dots behind the hook
                cx, cy = W // 2, top + head["h"] // 2
                self._dashed_ring(f, cx, cy, 430, t, _clamp(lt / 0.6) * (1 - out), self.accent)
                for k in range(3):
                    ang = t * 1.4 + k * 2.1
                    px, py = int(cx + math.cos(ang) * 430), int(cy + math.sin(ang) * 430)
                    _paste_rgba(f, rounded(22, 22, 11, (self.accent if k else self.accent2) + (255,)), px - 11, py - 11, 1 - out)
            self._headline(f, head, top, lt, out, 0.2)
            k = ease_out_cubic((lt - 0.7) / 0.5) * (1 - out)
            if k > 0:  # underline draws itself
                w = int(300 * k)
                _blend(f, 72, top + head["h"] + 26, np.array(self.accent, np.float32), np.full((10, max(1, w)), 1.0, np.float32))
        elif sec == "problem":
            head = self.heads["problem"]
            self._headline(f, head, zone_top, lt, out)
            ay = zone_top + head["h"] + 70 if self.mode == "liquid" else H - 520 - 3 * 150
            if self.mode == "cinematic":
                ay = max(ay, zone_top + head["h"] + 60)
            for j, (im, m) in enumerate(self.alerts):
                ta = self.alert_times[j] if j < len(self.alert_times) else S["start"] + 1 + j * 0.5
                k = ease_out_back((t - ta) / 0.45)
                if k > 0:
                    shake = int(math.sin((t - ta) * 60) * 10 * max(0.0, 1 - (t - ta) / 0.35))
                    _paste_rgba(f, im, 85 - m + int((1 - min(1.0, k)) * 500) + shake, ay + j * 150 - m, _clamp(k) * (1 - out))
        elif sec == "solution":
            n = len(self.cards)
            base = (H - n * (self.card_h + 30)) // 2 + (40 if self.mode == "liquid" else 260)
            if self.mode == "cinematic":
                base = H - 360 - n * (self.card_h + 30)
            # connector line drawing down through the step numbers
            first = self.tl["steps"][0]["start"]
            lk = _clamp((t - first) / (self.tl["steps"][-1]["start"] + 0.6 - first))
            if lk > 0:
                hgt = int((n - 1) * (self.card_h + 30) * lk)
                _blend(f, 70 + 82 - 3, base + self.card_h // 2, np.array(self.accent, np.float32), np.full((max(1, hgt), 6), 0.5 * (1 - out), np.float32))
            for j, (im, m) in enumerate(self.cards):
                st = self.tl["steps"][j]["start"]
                k = ease_out_back((t - st) / 0.5)
                if k <= 0:
                    continue
                x, y = 70 + int((1 - min(1.0, k)) * 260), base + j * (self.card_h + 30)
                a = _clamp(k) * (1 - out)
                _paste_rgba(f, im, x - m, y - m, a)
                cx, cy = x + 82, y + self.card_h // 2 - 10
                done = t > st + 0.55
                circle = rounded(92, 92, 46, (self.accent if done else _mix(self.accent, WHITE, 0.7)) + (255,))
                _paste_rgba(f, circle, cx - 46, cy - 46, a)
                if done:
                    self._check(f, cx, cy, 34, _clamp((t - st - 0.55) / 0.3), WHITE, 10)
                else:
                    num = text(str(j + 1), self.numf, INK + (255,), 0)
                    _paste_rgba(f, num, cx - num.width // 2, cy - num.height // 2 - 4, a)
                self._ring(f, cx, cy, (t - st - 0.15) / 0.6, self.accent)
        elif sec == "result":
            head = self.heads["result"]
            if self.mode == "liquid":
                cy = 560
                ck = ease_out_back((lt - 0.15) / 0.5)
                if ck > 0:
                    s = int(220 * min(1.15, ck))
                    sh_, sm = shadow(s, s, s // 2, 22, 70)
                    _paste_rgba(f, sh_, W // 2 - s // 2 - sm, cy - s // 2 - sm + 14, _clamp(ck) * (1 - out))
                    _paste_rgba(f, rounded(s, s, s // 2, self.accent + (255,)), W // 2 - s // 2, cy - s // 2, _clamp(ck) * (1 - out))
                    self._check(f, W // 2, cy, int(s * 0.32), _clamp((lt - 0.45) / 0.35), WHITE, 18)
                self._sparkles(f, W // 2, cy, (lt - 0.5) / 0.9, self.accent)
                self._ring(f, W // 2, cy, (lt - 0.4) / 0.8, self.accent, 110, 330, 10)
                self._headline(f, head, 760, lt, out, 0.45)
            else:
                self._headline(f, head, zone_top, lt, out, 0.3)
                self._sparkles(f, W - 180, zone_top + 40, (lt - 0.4) / 0.9, self.accent, 6, 140)
        else:  # CTA
            top = 90
            if self.logo:
                lk = ease_out_back((lt - 0.05) / 0.55)
                if lk > 0:
                    sz = max(1, int(200 * (0.5 + 0.5 * min(1.0, lk)) * (1 + 0.03 * math.sin(lt * 6))))
                    sh_, sm = shadow(sz, sz, sz // 2, 20, 90)
                    _paste_rgba(f, sh_, (W - sz) // 2 - sm, top + 100 - sz // 2 - sm + 14, _clamp(lk))
                    _paste_rgba(f, self.logo.resize((sz, sz), Image.LANCZOS), (W - sz) // 2, top + 100 - sz // 2, _clamp(lk))
                    self._ring(f, W // 2, top + 100, (lt - 0.2) / 0.9, self.accent, 100, 260, 8)
            kb = ease_out_cubic((lt - 0.2) / 0.5)
            if kb > 0:
                _paste_rgba(f, self.brand, (W - self.brand.width) // 2, top + 225 + int((1 - kb) * 30), kb)
                _paste_rgba(f, self.cta_line, (W - self.cta_line.width) // 2, top + 335 + int((1 - kb) * 30), kb)
            if self.mode == "liquid":
                kp = ease_out_back((lt - 0.35) / 0.6)
                if kp > 0:
                    prof, pm = self.prof
                    _paste_rgba(f, prof, 70 - pm, 520 - pm + int((1 - min(1.0, kp)) * 200), _clamp(kp))
                by = 1400
            else:
                by = H - 380
            bk = ease_out_back((lt - 0.8) / 0.5)
            if bk > 0:
                tapped = lt > 1.85
                press = 6 if 1.65 < lt < 1.9 else 0
                bx = (W - 560) // 2
                sh_, sm = self.btn_sh
                _paste_rgba(f, sh_, bx - sm, by - sm + 12 + int((1 - min(1.0, bk)) * 60), _clamp(bk))
                _paste_rgba(f, self.btn_done if tapped else self.btn, bx, by + press + int((1 - min(1.0, bk)) * 60), _clamp(bk))
                self._ring(f, bx + 380, by + 66, (lt - 1.65) / 0.7, INK, 24, 140, 6)
                self._sparkles(f, bx + 280, by + 66, (lt - 1.9) / 0.8, self.accent, 8, 240)

        # accent wipe transition around every cut
        for k_, s_ in self.S.items():
            if s_["start"] == 0:
                continue
            q = (t - (s_["start"] - 0.22)) / 0.44
            if 0 <= q < 1:
                x0 = (-0.25 + 1.5 * ease_out_cubic(q)) * W
                ys = np.arange(H, dtype=np.float32)[:, None]
                xs = x0 - ys / H * 300
                xx = np.arange(W, dtype=np.float32)[None, :]
                m = np.clip(260 - np.abs(xx - xs), 0, 1.5) / 1.5
                _blend(f, 0, 0, np.array(self.accent, np.float32), m.astype(np.float32))
                break

        if sec != "cta":
            self.subs.draw(f, t, H - 330, _paste_rgba)
        return f.tobytes()


# ====================================================================== render entry points
_R = None


def _init(post, cfg, tl, pal, fps, mode, seed, words):
    global _R
    _R = LightReel(post, cfg, tl, pal, fps, mode, seed, words)


def _work(args):
    i, path = args
    return _R.compose(i, Path(path) if path else None)


def _encode(frames, total, fps, audio, out, initargs):
    cmd = [FFMPEG, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "pipe:0",
           "-i", str(audio), "-map", "0:v", "-map", "1:a", "-shortest", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-maxrate", "10M", "-bufsize", "20M", "-pix_fmt", "yuv420p", "-profile:v", "high", "-c:a", "aac", "-b:a", "192k",
           "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    procs = max(1, min(os.cpu_count() or 2, 6))
    try:
        with get_context("fork").Pool(procs, initializer=_init, initargs=initargs) as pool:
            for k, buf in enumerate(pool.imap(_work, frames, chunksize=4)):
                proc.stdin.write(buf)
                if k % 120 == 0:
                    print(f"[light] {k}/{len(frames)}")
    finally:
        proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed while encoding the reel")


def render_light_liquid(post: dict, cfg: dict, out: Path, work: Path, seed: int, vo: dict | None = None) -> Path:
    from .liquid import timeline
    from .voice import assemble, section_durations
    fps = int(cfg["video"].get("fps_cinematic", 24))
    tl = timeline(post, section_durations(vo))
    rng = random.Random(seed)
    pal_name, pal = pick_light_palette(cfg, rng)
    post["_plan"] = {"style": "liquid_glass", "theme": "light", "palette": pal_name}
    voice, words = assemble(vo, tl, tl["total"])
    audio = build_soundtrack(tl["total"], tl["cues"], cfg, work / "audio.wav", seed=seed, style="cinematic", voice=voice)
    n = int(math.ceil(tl["total"] * fps))
    print(f"[light] liquid, palette {pal_name}, {tl['total']:.1f}s")
    _encode([(i, None) for i in range(n)], tl["total"], fps, audio, out, (post, cfg, tl, pal, fps, "liquid", seed, words))
    print(f"[light] saved {out}")
    return out
