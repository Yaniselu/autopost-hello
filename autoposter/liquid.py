"""Liquid Glass reel (v2): animated liquid colour background, floating refractive glass
bubbles, frosted glass cards. Same story as the cinematic reel:
HOOK -> THE PROBLEM (alerts) -> THE FIX (3 steps) -> THE RESULT -> CTA (logo + real profile card).
Frames are independent, so they're drawn in parallel on all CPU cores.
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
from .glass import PALETTES, Glass, LiquidBackground, _blend, _gradient_fill, _paste_rgba, _spaced, _text_img
from .render import FONT_BOLD, FONT_MED, FONT_SEMI, ease_out_back, ease_out_cubic, parse_rich, render_line

W, H = 1080, 1920
WHITE = (255, 255, 255)


def _words(s) -> int:
    return len(str(s or "").replace("*", "").split())


def timeline(post: dict, durations: dict | None = None) -> dict:
    D = durations or {}
    hook = max(2.6, 1.4 + _words(post["hook"]) * 0.22, D.get("hook", 0))
    problem = max(4.0, 2.4 + _words(post["problem"]["text"]) * 0.22, D.get("problem", 0))
    steps = [max(2.1, 1.2 + (_words(s["title"]) + _words(s["text"])) * 0.17, (D.get("steps") or [0] * 9)[i])
             for i, s in enumerate(post["solution"]["steps"])]
    solution = 0.6 + sum(steps)
    result = max(2.8, 1.6 + _words(post["result"]) * 0.2, D.get("result", 0))
    cta = max(3.4, D.get("cta", 0))
    S, t = {}, 0.0
    for k, d in (("hook", hook), ("problem", problem), ("solution", solution), ("result", result), ("cta", cta)):
        S[k] = {"start": t, "dur": d}
        t += d
    st, step_t = S["solution"]["start"] + 0.6, []
    for d in steps:
        step_t.append({"start": st, "dur": d})
        st += d
    alerts = [S["problem"]["start"] + 1.2 + i * 0.5 for i in range(len(post["problem"].get("alerts", [])[:3]))]
    cues = [(0.0, "impact"), (0.05, "whoosh")]
    cues += [(S["problem"]["start"] - 0.2, "whoosh"), (S["problem"]["start"] + 0.1, "glitch")] + [(a, "alert") for a in alerts]
    cues += [(S["solution"]["start"] - 0.2, "whoosh")] + [c for s in step_t for c in ((s["start"], "pop"), (s["start"] + 0.35, "tick"))]
    cues += [(S["result"]["start"] - 0.2, "whoosh"), (S["result"]["start"] + 0.25, "chime")]
    cues += [(S["cta"]["start"] - 1.0, "riser"), (S["cta"]["start"], "impact"), (S["cta"]["start"] + 1.75, "pop")]
    return {"total": round(t, 2), "sections": S, "steps": step_t, "alerts": alerts, "cues": cues}


def _clamp(x):
    return min(1.0, max(0.0, x))


def _rgba_fill(img: Image.Image) -> np.ndarray:
    a = np.asarray(img, np.float32)
    out = np.zeros(a.shape[:2] + (4,), np.float32)
    out[..., :3], out[..., 3] = a[..., :3], a[..., 3] / 255
    return out


def _decode(data_url: str | None) -> Image.Image | None:
    if not data_url:
        return None
    try:
        return Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1]))).convert("RGB")
    except Exception:  # noqa: BLE001
        return None


class LiquidReel:
    def __init__(self, post: dict, cfg: dict, tl: dict, seed: int, palette: str | None = None):
        rng = random.Random(seed)
        name = palette if palette in PALETTES else rng.choice(list(PALETTES))
        self.pal_name, self.pal = name, PALETTES[name]
        self.accent, self.accent2 = tuple(self.pal["accent"]), tuple(self.pal["accent2"])
        self.post, self.tl, self.S = post, tl, tl["sections"]
        self.bg = LiquidBackground(W, H, self.pal, rng)

        self.bubbles = []
        for r in (130, 70, 98, 52, 64, 160, 40):
            self.bubbles.append({"g": Glass(2 * r, 2 * r, r, bevel=r, strength=-r * 0.55, blur=0, tint_alpha=0.0,
                                            gain=1.08, rim=1.25, specular_dot=True, shadow=0.0, sheen=False),
                                 "r": r, "x0": rng.uniform(0.04, 0.96) * W, "y0": rng.uniform(0, H),
                                 "sp": rng.uniform(22, 55), "ph": rng.uniform(0, 6.28)})

        acc = (cfg.get("_account") or {}).get("assets") or {}
        if not acc.get("avatar_bytes"):
            from .account import local_logo
            jb, _ = local_logo()
            acc = dict(acc, avatar_bytes=jb)
        self.logo = self.logo_sm = None
        if acc.get("avatar_bytes"):
            from .account import logo_png
            self.logo, self.logo_sm = logo_png(acc["avatar_bytes"], 190), logo_png(acc["avatar_bytes"], 52)
            self.logo_md = logo_png(acc["avatar_bytes"], 96)

        # ---- headlines (kinetic words inside glass cards)
        self.heads = {sec: self._words(txt, size) for sec, txt, size in (
            ("hook", post["hook"], 118), ("problem", post["problem"]["text"], 80), ("result", post["result"], 86))}
        cw = W - 120
        self.hook_card = Glass(cw, self.heads["hook"]["h"] + 260, 72)
        self.prob_card = Glass(cw, self.heads["problem"]["h"] + 120, 60)
        self.res_card = Glass(cw, self.heads["result"]["h"] + 380, 72)

        # ---- label chips
        cf = ImageFont.truetype(str(FONT_SEMI), 32)
        self.chips = {}
        for sec, txt, dot in (("problem", "THE PROBLEM", (255, 77, 109)), ("solution", "THE FIX", self.accent),
                              ("result", "THE RESULT", self.accent)):
            w = int(sum(cf.getlength(c) + 3 for c in txt)) + 110
            img = Image.new("RGBA", (w, 76), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.ellipse((30, 29, 48, 47), fill=dot + (255,))
            x = 66
            for ch in txt:
                d.text((x, 18), ch, font=cf, fill=WHITE + (255,))
                x += cf.getlength(ch) + 3
            self.chips[sec] = (Glass(w, 76, 38, bevel=18, strength=12, shadow=0.25), _rgba_fill(img))

        # ---- alert notifications (problem)
        af, nf = ImageFont.truetype(str(FONT_SEMI), 38), ImageFont.truetype(str(FONT_MED), 26)
        self.alerts = []
        for a in post["problem"].get("alerts", [])[:3]:
            img = Image.new("RGBA", (W - 160, 130), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.rounded_rectangle((28, 28, 102, 102), radius=20, fill=(255, 77, 109, 255))
            d.text((57, 36), "!", font=ImageFont.truetype(str(FONT_BOLD), 52), fill=WHITE + (255,))
            d.text((126, 26), (post.get("app_name") or "WORK").upper(), font=nf, fill=(255, 255, 255, 150))
            d.text((126, 60), str(a)[:34], font=af, fill=WHITE + (255,))
            self.alerts.append((Glass(W - 160, 130, 38, bevel=26, strength=18, tint=(40, 10, 20), tint_alpha=0.35), _rgba_fill(img)))

        # ---- step cards
        tf, df, numf = (ImageFont.truetype(str(FONT_BOLD), 48), ImageFont.truetype(str(FONT_MED), 32),
                        ImageFont.truetype(str(FONT_BOLD), 44))
        self.cards = []
        ch = 190
        for i, s in enumerate(post["solution"]["steps"]):
            img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            grad = Image.fromarray(np.clip(_gradient_fill(92, 92, self.accent, self.accent2, 1)[..., :3], 0, 255).astype(np.uint8))
            m = Image.new("L", (92, 92), 0)
            ImageDraw.Draw(m).ellipse((0, 0, 91, 91), fill=255)
            img.paste(grad, (36, (ch - 92) // 2), m)
            d.text((36 + 46 - numf.getlength(str(i + 1)) / 2, (ch - 92) // 2 + 18), str(i + 1), font=numf, fill=(7, 16, 24, 255))
            d.text((160, 40), self._fit(s["title"], tf, cw - 200), font=tf, fill=WHITE + (255,))
            d.text((160, 108), self._fit(s["text"], df, cw - 200), font=df, fill=(255, 255, 255, 205))
            self.cards.append((Glass(cw, ch, 50, bevel=34, strength=26, tint_alpha=0.32), _rgba_fill(img)))
        self.card_h = ch

        # ---- result icon
        ic = Image.new("RGBA", (180, 180), (0, 0, 0, 0))
        grad = Image.fromarray(np.clip(_gradient_fill(180, 180, self.accent, self.accent2, 1)[..., :3], 0, 255).astype(np.uint8))
        m = Image.new("L", (180, 180), 0)
        ImageDraw.Draw(m).ellipse((0, 0, 179, 179), fill=255)
        ic.paste(grad, (0, 0), m)
        ImageDraw.Draw(ic).line([(48, 94), (78, 124), (134, 60)], fill=(7, 16, 24, 255), width=18, joint="curve")
        self.check = ic

        # ---- CTA: brand + profile card with the real account + follow button
        self.brand = _spaced(cfg["brand"]["name"].upper(), ImageFont.truetype(str(FONT_BOLD), 92), WHITE, self.accent)
        handle = "@" + acc["username"] if acc.get("username") else cfg["brand"]["handle"]
        pcw, pch = W - 140, 860
        prof = Image.new("RGBA", (pcw, pch), (0, 0, 0, 0))
        d = ImageDraw.Draw(prof)
        if self.logo:
            ring = Image.new("RGBA", (156, 156), (0, 0, 0, 0))
            ImageDraw.Draw(ring).ellipse((0, 0, 155, 155), fill=self.accent2 + (255,))
            prof.alpha_composite(ring, (40, 40))
            prof.alpha_composite(self.logo.resize((140, 140), Image.LANCZOS), (48, 48))
        d.text((220, 52), acc.get("name") or cfg["brand"]["name"], font=ImageFont.truetype(str(FONT_BOLD), 50), fill=WHITE + (255,))
        d.text((220, 114), handle, font=ImageFont.truetype(str(FONT_MED), 32), fill=(255, 255, 255, 170))

        def fmt(n):
            return "—" if n is None else (f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.1f}K" if n >= 1e4 else str(n))
        sf, lf = ImageFont.truetype(str(FONT_BOLD), 36), ImageFont.truetype(str(FONT_MED), 24)
        for k, (n, lab) in enumerate(((acc.get("posts"), "posts"), (acc.get("followers"), "followers"))):
            x = 220 + k * 190
            d.text((x, 160), fmt(n), font=sf, fill=WHITE + (255,))
            d.text((x, 202), lab, font=lf, fill=(255, 255, 255, 150))
        tiles = [t for t in (_decode(u) for u in acc.get("grid", [])) if t][:6]
        tw = (pcw - 80 - 24) // 3
        for k in range(6):
            x, y = 40 + (k % 3) * (tw + 12), 270 + (k // 3) * (tw + 12)
            mask = Image.new("L", (tw, tw), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, tw - 1, tw - 1), radius=22, fill=255)
            if k < len(tiles):
                t0 = tiles[k]
                s0 = max(tw / t0.width, tw / t0.height)
                t1 = t0.resize((int(t0.width * s0) + 1, int(t0.height * s0) + 1), Image.LANCZOS)
                t1 = t1.crop(((t1.width - tw) // 2, (t1.height - tw) // 2, (t1.width - tw) // 2 + tw, (t1.height - tw) // 2 + tw))
            else:
                t1 = Image.fromarray(np.clip(_gradient_fill(tw, tw, self.accent if k % 2 else self.accent2, (30, 30, 60), 1)[..., :3],
                                             0, 255).astype(np.uint8))
            prof.paste(t1, (x, y), mask)
        self.prof_card, self.prof_fill = Glass(pcw, pch, 64), _rgba_fill(prof)

        bw, bh = 560, 136
        bf = ImageFont.truetype(str(FONT_BOLD), 54)
        self.btn = Glass(bw, bh, bh // 2, bevel=30, strength=24, tint_alpha=0.08, shadow=0.35)
        b1 = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        ImageDraw.Draw(b1).text(((bw - bf.getlength("FOLLOW  →")) / 2, 34), "FOLLOW  →", font=bf, fill=(7, 16, 24, 255))
        fill = _gradient_fill(bw, bh, self.accent, self.accent2, 0.78)
        ta = np.asarray(b1, np.float32)
        k = ta[..., 3:4] / 255
        fill[..., :3] = fill[..., :3] * (1 - k) + ta[..., :3] * k
        self.btn_fill = fill
        b2 = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        ImageDraw.Draw(b2).text(((bw - bf.getlength("FOLLOWING ✓")) / 2, 34), "FOLLOWING ✓", font=bf, fill=WHITE + (255,))
        self.btn_done = _rgba_fill(b2)
        self.btn_done[..., 3] = np.maximum(self.btn_done[..., 3], 0.1)

        # ---- persistent UI
        self.bar = Glass(W - 140, 18, 9, bevel=8, strength=5, blur=6, shadow=0.15, sheen=False)
        self.handle_img = _text_img(handle, ImageFont.truetype(str(FONT_MED), 36), (255, 255, 255, 235))
        self.pill = Glass(self.handle_img.width + 50 + (62 if self.logo_sm else 0), 76, 38, bevel=18, strength=12, shadow=0.2)
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.sqrt(((xx - W / 2) / (W * 0.62)) ** 2 + ((yy - H * 0.46) / (H * 0.6)) ** 2)
        self.edge = np.clip((r - 0.45) * 1.6, 0, 1).astype(np.float32)[..., None]
        from .subtitles import Subtitles
        self.subs = Subtitles(cfg.get("_voice_words") or [], self.accent)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _fit(text, font, max_w):
        text = str(text).replace("*", "")
        while font.getlength(text) > max_w and len(text) > 4:
            text = text[:-2].rstrip() + "…"
        return text.replace("……", "…")

    def _words(self, text, size):
        while True:
            font = ImageFont.truetype(str(FONT_BOLD), size)
            words, space, max_w = parse_rich(text), font.getlength(" "), W - 260
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
        out, lh = [], int(size * 1.1)
        for li, line in enumerate(lines):
            lw = sum(font.getlength(w) for w, _ in line) + space * (len(line) - 1)
            x = (W - lw) / 2
            for w, hl in line:
                out.append((render_line([(w, hl)], font, WHITE, self.accent), int(x) - 30, li * lh - 30))
                x += font.getlength(w) + space
        return {"words": out, "h": len(lines) * lh}

    def _kinetic(self, f, head, top, lt, out, delay=0.2):
        for j, (im, x, y) in enumerate(head["words"]):
            k = ease_out_cubic((lt - delay - j * 0.05) / 0.42)
            a = k * (1 - out)
            if a > 0.01:
                _paste_rgba(f, im, x, top + y + int((1 - k) * 60 - out * 40), a)

    def _ring(self, f, cx, cy, q, color, rmin=40, rmax=180, width=9):
        if not 0 <= q < 1:
            return
        rad = int(rmin + (rmax - rmin) * ease_out_cubic(q))
        ring = Image.new("RGBA", (rad * 2 + 20, rad * 2 + 20), (0, 0, 0, 0))
        ImageDraw.Draw(ring).ellipse((10, 10, rad * 2 + 10, rad * 2 + 10), outline=color + (int(230 * (1 - q)),),
                                     width=max(2, int(width * (1 - q))))
        _paste_rgba(f, ring, cx - rad - 10, cy - rad - 10)

    def section(self, t):
        for k, s in self.S.items():
            if s["start"] <= t < s["start"] + s["dur"]:
                return k
        return "cta"

    # ------------------------------------------------------------------ frame
    def frame(self, i: int, fps: int) -> bytes:
        t = i / fps
        f = self.bg.frame(t, i)
        for b in self.bubbles:
            r = b["r"]
            y = (b["y0"] - b["sp"] * t) % (H + 4 * r) - 2 * r
            b["g"].draw(f, b["x0"] + 40 * math.sin(t * 0.6 + b["ph"]) - r, y - r, 1.0, t)

        sec = self.section(t)
        S = self.S[sec]
        lt, dur = t - S["start"], S["dur"]
        enter = ease_out_back(lt / 0.55)
        a_in = _clamp(lt / 0.3)
        out = _clamp((lt - (dur - 0.3)) / 0.3) if sec != "cta" else 0.0
        a = a_in * (1 - out)
        dy = int((1 - min(1.0, enter)) * 160 - out * 60)

        # progress + handle
        if sec != "cta":
            p = min(1.0, t / self.tl["total"])
            fill = np.zeros((18, self.bar.w, 4), np.float32)
            fw = int(self.bar.w * p)
            if fw:
                fill[:, :fw] = _gradient_fill(fw, 18, self.accent, self.accent2, 0.95)
            self.bar.draw(f, 70, 92, 1.0, t, extra=fill)
            hx, hy = (W - self.pill.w) // 2, H - 200
            self.pill.draw(f, hx, hy, 1.0, t)
            if self.logo_sm:
                _paste_rgba(f, self.logo_sm, hx + 14, hy + 12)
                _paste_rgba(f, self.handle_img, hx + 72, hy + 10)
            else:
                _paste_rgba(f, self.handle_img, hx + 25, hy + 10)
        if sec in self.chips:
            g, chip = self.chips[sec]
            kc = ease_out_back(lt / 0.5)
            g.draw(f, 70 - int((1 - min(1.0, kc)) * 60), 160, _clamp(kc) * (1 - out), t, extra=chip)

        if sec == "hook":
            c = self.hook_card
            y0 = (H - c.h) // 2 - 80 + dy
            c.draw(f, 60, y0, a, t)
            if self.logo_sm:
                _paste_rgba(f, self.logo_md, (W - 96) // 2, y0 + 24, a)
            self._kinetic(f, self.heads["hook"], y0 + 150, lt, out, 0.25)
            k = ease_out_cubic((lt - 0.5) / 0.6) * (1 - out)
            if k > 0:
                w = int(260 * k)
                bar = _gradient_fill(w, 10, self.accent, self.accent2, 1.0)
                _blend(f, (W - w) // 2, y0 + c.h - 70, bar[..., :3], bar[..., 3])
        elif sec == "problem":
            c = self.prob_card
            y0 = 280 + dy
            c.draw(f, 60, y0, a, t)
            self._kinetic(f, self.heads["problem"], y0 + 60, lt, out)
            ay = y0 + c.h + 50
            for j, (g, fill_) in enumerate(self.alerts):
                ta = self.tl["alerts"][j]
                k = ease_out_back((t - ta) / 0.45)
                if k > 0:
                    g.draw(f, 80 + int((1 - min(1.0, k)) * 400), ay + j * 160, _clamp(k) * (1 - out), t, extra=fill_)
                q = (t - ta) / 0.4
                if 0 <= q < 1:  # red danger pulse
                    f[:] = np.clip(f + (np.array([255, 40, 70], np.float32) - f) * self.edge * (0.5 * (1 - q)), 0, 255).astype(np.uint8)
        elif sec == "solution":
            base = (H - len(self.cards) * (self.card_h + 26)) // 2 - 20
            for j, (g, fill_) in enumerate(self.cards):
                st = self.tl["steps"][j]["start"]
                k = ease_out_back((t - st) / 0.5)
                if k <= 0:
                    continue
                active = j == len(self.cards) - 1 or t < self.tl["steps"][j + 1]["start"]
                x, y = 60 + int((1 - min(1.0, k)) * 220), base + j * (self.card_h + 26)
                g.draw(f, x, y, _clamp(k) * (1.0 if active else 0.62) * (1 - out), t, extra=fill_)
                self._ring(f, x + 82, y + self.card_h // 2, (t - st - 0.15) / 0.6, self.accent)
        elif sec == "result":
            c = self.res_card
            y0 = (H - c.h) // 2 - 60 + dy
            c.draw(f, 60, y0, a, t)
            ki = ease_out_back((lt - 0.2) / 0.5)
            if ki > 0:
                s = max(1, int(180 * min(1.2, ki)))
                _paste_rgba(f, self.check.resize((s, s), Image.LANCZOS), (W - s) // 2, y0 + 140 - s // 2, _clamp(ki) * (1 - out))
                self._ring(f, W // 2, y0 + 140, (lt - 0.3) / 0.8, self.accent2, 90, 320, 12)
            self._kinetic(f, self.heads["result"], y0 + 280, lt, out, 0.4)
        else:  # CTA
            top = 70
            if self.logo:
                lk = ease_out_back((lt - 0.05) / 0.55)
                if lk > 0:
                    sz = max(1, int(190 * (0.5 + 0.5 * min(1.0, lk)) * (1 + 0.04 * math.sin(lt * 6))))
                    glow = Image.new("RGBA", (sz + 140, sz + 140), (0, 0, 0, 0))
                    ImageDraw.Draw(glow).ellipse((50, 50, sz + 90, sz + 90), fill=self.accent + (150,))
                    _paste_rgba(f, glow.filter(ImageFilter.GaussianBlur(24)), (W - glow.width) // 2, top + 95 - glow.height // 2, _clamp(lk))
                    _paste_rgba(f, self.logo.resize((sz, sz), Image.LANCZOS), (W - sz) // 2, top + 95 - sz // 2, _clamp(lk))
            kb = ease_out_back((lt - 0.15) / 0.6)
            if kb > 0:
                bi = self.brand
                s = 0.7 + 0.15 * min(1.0, kb)
                im = bi.resize((int(bi.width * s), int(bi.height * s)), Image.BICUBIC)
                _paste_rgba(f, im, (W - im.width) // 2, top + 215, _clamp(kb))
            kp = ease_out_back((lt - 0.35) / 0.6)
            if kp > 0:
                self.prof_card.draw(f, 70, 450 + int((1 - min(1.0, kp)) * 200), _clamp(kp), t, extra=self.prof_fill)
            bk = ease_out_back((lt - 0.8) / 0.5)
            if bk > 0:
                tapped = lt > 1.85
                fill2 = (self.btn_done if tapped else self.btn_fill).copy()
                bx, by = (W - self.btn.w) // 2, 1360 + int((1 - min(1.0, bk)) * 60) + (6 if 1.65 < lt < 1.9 else 0)
                self.btn.draw(f, bx, by, _clamp(bk), t * 2.5, extra=fill2)
                q = (lt - 1.65) / 0.7
                if 0 <= q < 1:
                    self._ring(f, bx + self.btn.w // 2 + 100, by + self.btn.h // 2, q, WHITE, 26, 150, 7)
        if sec != "cta":
            self.subs.draw(f, t, H - 300, _paste_rgba)
        return f.tobytes()


_R = None


def _init(post, cfg, tl, seed, palette):
    global _R
    _R = LiquidReel(post, cfg, tl, seed, palette)


def _work(args):
    i, fps = args
    return _R.frame(i, fps)


def render_liquid_reel(post: dict, cfg: dict, out: Path, work: Path, seed: int, vo: dict | None = None) -> Path:
    from .voice import assemble, section_durations
    fps = int(cfg["video"].get("fps_cinematic", 24))
    tl = timeline(post, section_durations(vo))
    palette = cfg["video"].get("palette", "random")
    palette = palette if palette in PALETTES else random.Random(seed).choice(list(PALETTES))
    post["_plan"] = {"style": "liquid_glass", "palette": palette}
    print(f"[liquid] palette {palette}, {tl['total']:.1f}s")
    voice, words = assemble(vo, tl, tl["total"])
    cfg["_voice_words"] = words
    audio = build_soundtrack(tl["total"], tl["cues"], cfg, work / "audio.wav", seed=seed, style="cinematic", voice=voice)
    n = int(math.ceil(tl["total"] * fps))
    cmd = [FFMPEG, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "pipe:0",
           "-i", str(audio), "-map", "0:v", "-map", "1:a", "-shortest", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-maxrate", "10M", "-bufsize", "20M", "-pix_fmt", "yuv420p", "-profile:v", "high", "-c:a", "aac", "-b:a", "192k",
           "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    procs = max(1, min(os.cpu_count() or 2, 6))
    try:
        with get_context("fork").Pool(procs, initializer=_init, initargs=(post, cfg, tl, seed, palette)) as pool:
            for k, buf in enumerate(pool.imap(_work, [(i, fps) for i in range(n)], chunksize=4)):
                proc.stdin.write(buf)
                if k % 120 == 0:
                    print(f"[liquid] {k}/{n}")
    finally:
        proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed while encoding the liquid glass reel")
    print(f"[liquid] saved {out}")
    return out
