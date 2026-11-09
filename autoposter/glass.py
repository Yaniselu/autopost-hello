""""Liquid Glass" style renderer.

Everything is drawn in Python, frame by frame:
  * animated liquid background (moving colour blobs) or a Pexels video
  * floating glass bubbles that refract what's behind them
  * frosted glass cards with edge refraction, chromatic aberration,
    specular rims, moving light sheen and soft shadows
  * glass chips, glass progress bar, glass "FOLLOW" button
Frames are piped straight into ffmpeg together with the soundtrack.
"""
import math
import random
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .audio import build_soundtrack
from .ff import FFMPEG
from .render import (FONT_BOLD, FONT_MED, FONT_SEMI, ease_out_back, ease_out_cubic,
                     fit_text, hex_rgb, render_line)

PALETTES = {
    "aurora": {"bg": (8, 6, 22), "blobs": [(0, 210, 255), (124, 77, 255), (255, 64, 170), (40, 90, 255), (0, 255, 190)],
               "accent": (120, 240, 255), "accent2": (190, 140, 255)},
    "sunset": {"bg": (20, 6, 16), "blobs": [(255, 120, 60), (255, 50, 120), (150, 60, 255), (255, 190, 80), (255, 80, 80)],
               "accent": (255, 214, 120), "accent2": (255, 120, 170)},
    "ocean": {"bg": (3, 10, 24), "blobs": [(0, 140, 255), (0, 220, 200), (60, 60, 255), (0, 255, 140), (120, 180, 255)],
              "accent": (110, 255, 220), "accent2": (120, 170, 255)},
    "neon": {"bg": (6, 4, 14), "blobs": [(255, 0, 200), (0, 230, 255), (120, 0, 255), (0, 120, 255), (255, 80, 255)],
             "accent": (255, 120, 240), "accent2": (90, 230, 255)},
    "mint": {"bg": (4, 14, 14), "blobs": [(0, 230, 160), (0, 160, 255), (160, 255, 80), (0, 100, 200), (80, 255, 220)],
             "accent": (170, 255, 140), "accent2": (90, 220, 255)},
}

WHITE = np.array([255, 255, 255], np.float32)


# ====================================================================== utils
def _crop_padded(frame: np.ndarray, y0: int, x0: int, h: int, w: int) -> np.ndarray:
    H, W = frame.shape[:2]
    ya, yb, xa, xb = max(0, y0), min(H, y0 + h), max(0, x0), min(W, x0 + w)
    if ya >= yb or xa >= xb:
        return np.zeros((h, w, 3), frame.dtype)
    crop = frame[ya:yb, xa:xb]
    pads = ((ya - y0, y0 + h - yb), (xa - x0, x0 + w - xb), (0, 0))
    if any(p for pair in pads for p in pair):
        crop = np.pad(crop, pads, mode="edge")
    return crop


def _blend(frame: np.ndarray, x: int, y: int, rgb: np.ndarray, alpha: np.ndarray) -> None:
    """frame[y:y+h, x:x+w] = lerp(frame, rgb, alpha), clipped to the frame."""
    H, W = frame.shape[:2]
    h, w = alpha.shape
    ya, yb, xa, xb = max(0, y), min(H, y + h), max(0, x), min(W, x + w)
    if ya >= yb or xa >= xb:
        return
    sa = alpha[ya - y:yb - y, xa - x:xb - x, None]
    dst = frame[ya:yb, xa:xb].astype(np.float32)
    src = rgb[ya - y:yb - y, xa - x:xb - x] if rgb.ndim == 3 else rgb
    frame[ya:yb, xa:xb] = (dst + (src - dst) * sa).astype(np.uint8)


def _paste_rgba(frame: np.ndarray, img: Image.Image, x: int, y: int, opacity: float = 1.0) -> None:
    if opacity <= 0.01:
        return
    arr = np.asarray(img, dtype=np.float32)
    _blend(frame, x, y, arr[..., :3], arr[..., 3] / 255.0 * opacity)


def _sdf_round_rect(w: int, h: int, r: float) -> np.ndarray:
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    px, py = np.abs(xs + 0.5 - w / 2), np.abs(ys + 0.5 - h / 2)
    qx, qy = px - (w / 2 - r), py - (h / 2 - r)
    outside = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0))
    inside = np.minimum(np.maximum(qx, qy), 0)
    return outside + inside - r


# ====================================================================== glass element
class Glass:
    """A refractive glass shape (rounded rect / pill / circle) with precomputed maps."""

    def __init__(self, w, h, radius, bevel=40.0, strength=34.0, blur=8, tint=(14, 14, 28),
                 tint_alpha=0.30, gain=1.04, rim=1.0, specular_dot=False, shadow=0.35, sheen=True):
        self.w, self.h = w, h
        self.blur, self.tint_alpha, self.gain = blur, tint_alpha, gain
        self.tint = np.array(tint, np.float32)
        self.sheen = sheen
        sdf = _sdf_round_rect(w, h, radius)
        self.mask = np.clip(0.5 - sdf, 0, 1).astype(np.float32)

        gy, gx = np.gradient(sdf)
        norm = np.hypot(gx, gy) + 1e-6
        nx, ny = gx / norm, gy / norm
        e = np.clip(1 + sdf / bevel, 0, 1) ** 2  # 1 at the edge -> 0 deeper inside

        self.M = M = int(abs(strength) * 1.25) + 3
        ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
        self.maps = []
        for k in (1.12, 1.0, 0.88):  # R, G, B -> chromatic aberration
            sx = np.clip(xs + M + nx * strength * k * e, 0, w + 2 * M - 1).astype(np.int32)
            sy = np.clip(ys + M + ny * strength * k * e, 0, h + 2 * M - 1).astype(np.int32)
            self.maps.append((sy, sx))

        # specular rim (light from the top-left, weaker reflection bottom-right)
        light = np.clip(-(nx * 0.6 + ny * 0.8), 0, 1)
        back = np.clip(nx * 0.6 + ny * 0.8, 0, 1)
        line = np.exp(-((sdf + 1.6) / 1.3) ** 2)
        inner = np.exp(-((sdf + 5) / 4.0) ** 2)
        spec = line * (0.25 + 0.75 * light) + line * back * 0.45 + inner * light * 0.18
        spec += e * 0.10                                       # bright bevel
        spec += 0.07 * np.clip(1 - ys / (h * 0.55), 0, 1) ** 2  # top inner glow
        if specular_dot:
            spec += 0.75 * np.exp(-(((xs - w * 0.32) / (w * 0.09)) ** 2 + ((ys - h * 0.27) / (h * 0.06)) ** 2))
            spec += 0.25 * np.exp(-(((xs - w * 0.68) / (w * 0.12)) ** 2 + ((ys - h * 0.78) / (h * 0.05)) ** 2))
        self.spec = np.clip(spec * rim, 0, 0.95).astype(np.float32) * self.mask
        self.proj = ((xs * 0.8 + ys * 0.6) / (w * 0.8 + h * 0.6)).astype(np.float32)

        # soft shadow
        self.shadow = None
        if shadow:
            S = 46
            m = Image.fromarray((self.mask * 255).astype(np.uint8)).resize((w // 2, h // 2))
            pad = Image.new("L", (w // 2 + S, h // 2 + S), 0)
            pad.paste(m, (S // 2, S // 2))
            pad = pad.filter(ImageFilter.GaussianBlur(14)).resize((w + 2 * S, h + 2 * S))
            self.shadow = np.asarray(pad, np.float32) / 255 * shadow
            self.S = S

    def draw(self, frame: np.ndarray, x: int, y: int, opacity: float = 1.0, t: float = 0.0,
             extra: np.ndarray | None = None) -> None:
        if opacity <= 0.01:
            return
        x, y = int(x), int(y)
        if self.shadow is not None:
            S = self.S
            _blend(frame, x - S, y - S + 24, np.zeros(3, np.float32), self.shadow * opacity)

        M = self.M
        crop = _crop_padded(frame, y - M, x - M, self.h + 2 * M, self.w + 2 * M)
        if self.blur:
            ch, cw = crop.shape[:2]
            small = Image.fromarray(crop).resize((max(1, cw // 8), max(1, ch // 8)), Image.BILINEAR)
            crop = np.asarray(small.filter(ImageFilter.GaussianBlur(self.blur / 8 * 2.2))
                              .resize((cw, ch), Image.BILINEAR))
        g = np.stack([crop[sy, sx, c] for c, (sy, sx) in enumerate(self.maps)], -1).astype(np.float32)
        g = (g * (1 - self.tint_alpha) + self.tint * self.tint_alpha) * self.gain

        spec = self.spec
        if self.sheen:  # light sweep travelling across the glass
            pos = (t * 0.35) % 1.8 - 0.4
            spec = spec + 0.16 * np.exp(-((self.proj - pos) / 0.07) ** 2) * self.mask
        g = g + (WHITE - g) * spec[..., None]
        if extra is not None:  # RGBA overlay drawn "inside" the glass (fills, text)
            g = g + (extra[..., :3] - g) * extra[..., 3:4]
        np.clip(g, 0, 255, out=g)
        _blend(frame, x, y, g, self.mask * opacity)


# ====================================================================== backgrounds
class LiquidBackground:
    def __init__(self, W, H, palette, rng: random.Random):
        self.W, self.H = W, H
        self.lw, self.lh = W // 4, H // 4
        ys, xs = np.mgrid[0:self.lh, 0:self.lw].astype(np.float32)
        self.xs, self.ys = xs / self.lw, ys / self.lh * (H / W)
        self.base = np.array(palette["bg"], np.float32) / 255
        self.blobs = []
        for i, col in enumerate(palette["blobs"] + palette["blobs"][:2]):
            self.blobs.append({
                "col": np.array(col, np.float32) / 255,
                "cx": rng.uniform(0.1, 0.9), "cy": rng.uniform(0.1, 1.7),
                "ax": rng.uniform(0.15, 0.4), "ay": rng.uniform(0.2, 0.5),
                "fx": rng.uniform(0.15, 0.45), "fy": rng.uniform(0.1, 0.35),
                "ph": rng.uniform(0, 6.28), "r": rng.uniform(0.17, 0.33),
                "k": 0.9 if i < len(palette["blobs"]) else 0.5,
            })
        self.grain = np.random.default_rng(1).integers(-4, 5, (H + 64, W, 1), dtype=np.int16)

    def frame(self, t: float, i: int) -> np.ndarray:
        img = np.zeros((self.lh, self.lw, 3), np.float32)
        for b in self.blobs:
            cx = b["cx"] + b["ax"] * math.sin(t * b["fx"] + b["ph"])
            cy = b["cy"] + b["ay"] * math.cos(t * b["fy"] + b["ph"] * 1.3)
            d2 = ((self.xs - cx) ** 2 + (self.ys - cy) ** 2) / (b["r"] ** 2)
            img += np.exp(-d2)[..., None] * b["col"] * b["k"]
        img = self.base + (1 - np.exp(-img * 1.3)) * 0.98
        small = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8))
        big = np.asarray(small.resize((self.W, self.H), Image.BICUBIC), np.int16)
        off = (i * 7) % 64
        return np.clip(big + self.grain[off:off + self.H], 0, 255).astype(np.uint8)


class VideoBackground:
    def __init__(self, path: Path, W, H, fps):
        self.size = W * H * 3
        self.W, self.H = W, H
        self.proc = subprocess.Popen([
            FFMPEG, "-v", "error", "-stream_loop", "-1", "-i", str(path),
            "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={fps},"
                   "eq=saturation=1.35:contrast=1.05",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)

    def frame(self, t, i):
        buf = self.proc.stdout.read(self.size)
        return np.frombuffer(buf, np.uint8).reshape(self.H, self.W, 3).copy()

    def close(self):
        self.proc.kill()


# ====================================================================== text helpers
def _text_img(text, font, fill, pad=10):
    w = int(font.getlength(text)) + pad * 2
    asc, desc = font.getmetrics()
    img = Image.new("RGBA", (w, asc + desc + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((pad, pad), text, font=font, fill=fill)
    return img


def _spaced(text, font, color, glow_col, spacing=12):
    widths = [font.getlength(ch) for ch in text]
    w = int(sum(widths) + spacing * (len(text) - 1)) + 80
    asc, desc = font.getmetrics()
    img = Image.new("RGBA", (w, asc + desc + 80), (0, 0, 0, 0))
    glow = img.copy()
    d, dg = ImageDraw.Draw(img), ImageDraw.Draw(glow)
    x = 40
    for ch, cw in zip(text, widths):
        d.text((x, 40), ch, font=font, fill=color)
        dg.text((x, 40), ch, font=font, fill=glow_col + (220,))
        x += cw + spacing
    return Image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(20)), img)


def _gradient_fill(w, h, c1, c2, alpha):
    k = np.linspace(0, 1, w, dtype=np.float32)[None, :, None]
    rgb = np.array(c1, np.float32) * (1 - k) + np.array(c2, np.float32) * k
    rgb = np.broadcast_to(rgb, (h, w, 3))
    return np.concatenate([rgb, np.full((h, w, 1), alpha, np.float32)], -1)


def _stack_lines(lines, gap):
    heights = [im.height - 60 + gap for im in lines]
    return heights, sum(heights)


# ====================================================================== the renderer
class GlassReel:
    def __init__(self, post, cfg, background: Path | None, seed: int):
        v = cfg["video"]
        self.W, self.H, self.fps = v["width"], v["height"], v["fps"]
        W, H = self.W, self.H
        rng = random.Random(seed)
        name = v.get("palette", "random")
        self.pal = PALETTES[name] if name in PALETTES else PALETTES[rng.choice(list(PALETTES))]
        accent, accent2 = self.pal["accent"], self.pal["accent2"]
        white = hex_rgb(v["colors"]["text"])
        self.accent, self.accent2 = accent, accent2

        self.bg = (VideoBackground(background, W, H, self.fps) if background
                   else LiquidBackground(W, H, self.pal, rng))

        # ---------- bubbles
        self.bubbles = []
        for r in (120, 70, 95, 48, 60, 150):
            self.bubbles.append({
                "glass": Glass(2 * r, 2 * r, r, bevel=r, strength=-r * 0.55, blur=0, tint_alpha=0.0,
                               gain=1.08, rim=1.2, specular_dot=True, shadow=0.0, sheen=False),
                "r": r, "x0": rng.uniform(0.05, 0.95) * W, "y0": rng.uniform(0, H),
                "sp": rng.uniform(25, 60), "ph": rng.uniform(0, 6.28),
            })

        # ---------- scenes
        self.scenes, t = [], 0.0
        card_w = W - 120
        f_hook, l_hook = fit_text(post["hook"], FONT_BOLD, 120, card_w - 140, 4)
        lines = [render_line(l, f_hook, white, accent) for l in l_hook]
        hs, th = _stack_lines(lines, int(f_hook.size * 0.02))
        card_h = th + 220
        self.scenes.append({"kind": "hook", "start": t, "dur": v["hook_seconds"], "lines": lines,
                            "heights": hs, "text_h": th,
                            "card": Glass(card_w, card_h, 70), "card_h": card_h})
        t += v["hook_seconds"]

        chip_font = ImageFont.truetype(str(FONT_SEMI), 34)
        n = len(post["slides"])
        for i, s in enumerate(post["slides"]):
            words = len(s.replace("*", "").split())
            dur = max(v["slide_seconds"], 1.2 + words * 0.24)
            f, ls = fit_text(s, FONT_BOLD, 86, card_w - 150, 6)
            lines = [render_line(l, f, white, accent) for l in ls]
            hs, th = _stack_lines(lines, int(f.size * 0.04))
            card_h = th + 250
            label = _text_img(f"{i + 1:02d} / {n:02d}", chip_font, accent + (255,))
            self.scenes.append({"kind": "slide", "start": t, "dur": dur, "lines": lines, "heights": hs,
                                "text_h": th, "card": Glass(card_w, card_h, 64), "card_h": card_h,
                                "label": label})
            t += dur

        cta_font, cta_lines = fit_text(post.get("cta") or cfg["brand"]["call_to_action"], FONT_SEMI, 62,
                                       card_w - 160, 3)
        lines = [render_line(l, cta_font, white, accent) for l in cta_lines]
        hs, th = _stack_lines(lines, 0)
        self.name_img = _spaced(cfg["brand"]["name"].upper(), ImageFont.truetype(str(FONT_BOLD), 92),
                                white, accent)
        card_h = 220 + th + 330
        self.scenes.append({"kind": "cta", "start": t, "dur": v["cta_seconds"], "lines": lines,
                            "heights": hs, "text_h": th, "card": Glass(card_w, card_h, 80), "card_h": card_h})
        t += v["cta_seconds"]
        self.total = round(t, 2)

        # ---------- persistent UI
        self.chip = Glass(220, 70, 35, bevel=16, strength=10, shadow=0.2)
        self.btn_w, self.btn_h = 420, 120
        self.button = Glass(self.btn_w, self.btn_h, 60, bevel=28, strength=22, tint_alpha=0.1, shadow=0.3)
        btn = Image.new("RGBA", (self.btn_w, self.btn_h), (0, 0, 0, 0))
        bf = ImageFont.truetype(str(FONT_BOLD), 46)
        label = "FOLLOW  →"
        ImageDraw.Draw(btn).text(((self.btn_w - bf.getlength(label)) / 2, 30), label, font=bf, fill=(255, 255, 255))
        fill = _gradient_fill(self.btn_w, self.btn_h, accent, accent2, 0.55)
        txt = np.asarray(btn, np.float32)
        a = txt[..., 3:4] / 255
        fill[..., :3] = fill[..., :3] * (1 - a) + txt[..., :3] * a
        fill[..., 3:4] = np.maximum(fill[..., 3:4], a)
        self.button_fill = fill

        self.bar = Glass(W - 140, 20, 10, bevel=8, strength=5, blur=6, shadow=0.15, sheen=False)
        self.handle_img = _text_img(cfg["brand"]["handle"], ImageFont.truetype(str(FONT_MED), 36),
                                    (255, 255, 255, 235))
        hw = self.handle_img.width + 50
        self.handle_pill = Glass(hw, 76, 38, bevel=18, strength=12, shadow=0.2)

    # ------------------------------------------------------------------
    def sfx_cues(self):
        cues = [(0.0, "impact")]
        for s in self.scenes[1:]:
            if s["kind"] == "slide":
                cues += [(s["start"] - 0.22, "whoosh"), (s["start"] + 0.08, "pop")]
            else:
                cues += [(s["start"] - 0.9, "riser"), (s["start"], "impact"), (s["start"] + 0.55, "pop")]
        return cues

    def frame(self, i: int) -> np.ndarray:
        W, H = self.W, self.H
        t = i / self.fps
        f = self.bg.frame(t, i)

        for b in self.bubbles:  # floating glass bubbles
            r = b["r"]
            y = (b["y0"] - b["sp"] * t) % (H + 4 * r) - 2 * r
            x = b["x0"] + 40 * math.sin(t * 0.6 + b["ph"]) - r
            b["glass"].draw(f, x, y - r, 1.0, t)

        # progress bar (glass + gradient fill)
        p = min(1.0, t / self.total)
        bw = self.bar.w
        fill = np.zeros((20, bw, 4), np.float32)
        fw = int(bw * p)
        if fw > 0:
            fill[:, :fw] = _gradient_fill(fw, 20, self.accent, self.accent2, 0.9)
        self.bar.draw(f, 70, 96, 1.0, t, extra=fill)

        # handle pill
        hp = self.handle_pill
        hx, hy = (W - hp.w) // 2, H - 230
        hp.draw(f, hx, hy, 1.0, t)
        _paste_rgba(f, self.handle_img, hx + 25, hy + 10)

        scene = next((s for s in self.scenes if s["start"] <= t < s["start"] + s["dur"]), self.scenes[-1])
        lt = t - scene["start"]
        getattr(self, f"_draw_{scene['kind']}")(f, scene, lt, t)
        return f

    def _enter_exit(self, scene, lt, has_exit=True):
        k = ease_out_back(lt / 0.55)
        a = ease_out_cubic(lt / 0.35)
        ex = ease_out_cubic((lt - (scene["dur"] - 0.3)) / 0.3) if has_exit else 0.0
        dy = int(140 * (1 - k)) - int(60 * ex)
        return a * (1 - ex), dy, ex

    def _draw_lines(self, f, scene, x_center_or_left, y, align, lt, ex, delay0=0.12):
        for j, im in enumerate(scene["lines"]):
            k = ease_out_cubic((lt - delay0 - j * 0.09) / 0.45)
            a = k * (1 - ex)
            x = (self.W - im.width) // 2 if align == "center" else x_center_or_left
            _paste_rgba(f, im, x, y + int(50 * (1 - k)), a)
            y += scene["heights"][j]

    def _draw_hook(self, f, scene, lt, t):
        a, dy, ex = self._enter_exit(scene, lt)
        card = scene["card"]
        cx, cy = 60, (self.H - scene["card_h"]) // 2 - 60 + dy
        card.draw(f, cx, cy, a, t)
        ty = cy + (scene["card_h"] - scene["text_h"]) // 2 - 30
        self._draw_lines(f, scene, 0, ty, "center", lt, ex)
        k = ease_out_cubic((lt - 0.45) / 0.6) * (1 - ex)  # accent underline
        if k > 0:
            w = int(240 * k)
            y = ty + scene["text_h"] + 44
            bar = _gradient_fill(w, 10, self.accent, self.accent2, 1.0)
            _blend(f, (self.W - w) // 2, y, bar[..., :3], bar[..., 3])

    def _draw_slide(self, f, scene, lt, t):
        a, dy, ex = self._enter_exit(scene, lt)
        card = scene["card"]
        cx, cy = 60, (self.H - scene["card_h"]) // 2 - 60 + dy
        card.draw(f, cx, cy, a, t)
        # glass chip with the slide number (glass on glass)
        ck = ease_out_back((lt - 0.1) / 0.5)
        self.chip.draw(f, cx + 60, cy + 60 + int(30 * (1 - ck)), a * min(1, ck), t)
        lab = scene["label"]
        _paste_rgba(f, lab, cx + 60 + (220 - lab.width) // 2, cy + 60 + (70 - lab.height) // 2 + int(30 * (1 - ck)),
                    a * min(1, max(0, ck)))
        self._draw_lines(f, scene, cx + 45, cy + 160, "left", lt, ex, delay0=0.18)

    def _draw_cta(self, f, scene, lt, t):
        a, dy, _ = self._enter_exit(scene, lt, has_exit=False)
        card = scene["card"]
        cx, cy = 60, (self.H - scene["card_h"]) // 2 - 60 + dy
        card.draw(f, cx, cy, a, t)
        k = ease_out_back(lt / 0.6)
        name = self.name_img
        s = 0.75 + 0.25 * k
        img = name.resize((max(1, int(name.width * s)), max(1, int(name.height * s))), Image.BICUBIC)
        _paste_rgba(f, img, (self.W - img.width) // 2, cy + 120 - img.height // 2 + 20, a)
        self._draw_lines(f, scene, 0, cy + 200, "center", lt, 0.0, delay0=0.25)
        bk = ease_out_back((lt - 0.45) / 0.5)
        pulse = 0.5 + 0.5 * math.sin(lt * 7)
        fill = self.button_fill.copy()
        fill[..., 3] = np.clip(fill[..., 3] * (0.85 + 0.3 * pulse), 0, 1)
        bx = (self.W - self.btn_w) // 2
        by = cy + scene["card_h"] - self.btn_h - 80 + int(60 * (1 - bk))
        self.button.draw(f, bx, by, a * min(1, max(0, bk)), t * 2.5, extra=fill)


def render_glass_video(post: dict, cfg: dict, background: Path | None, out: Path, work: Path, seed=None) -> Path:
    seed = seed if seed is not None else random.randint(0, 10 ** 9)
    reel = GlassReel(post, cfg, background, seed)
    total, fps, W, H = reel.total, reel.fps, reel.W, reel.H
    print(f"[render] liquid glass, {len(reel.scenes)} scenes, {total:.1f}s")
    audio = build_soundtrack(total, reel.sfx_cues(), cfg, work / "audio.wav", seed=seed)
    cmd = [FFMPEG, "-y", "-v", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "pipe:0",
           "-i", str(audio), "-map", "0:v", "-map", "1:a", "-t", f"{total}",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-profile:v", "high",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for i in range(int(math.ceil(total * fps))):
            proc.stdin.write(reel.frame(i).tobytes())
    finally:
        proc.stdin.close()
        if isinstance(reel.bg, VideoBackground):
            reel.bg.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed while rendering the video")
    print(f"[render] saved {out}")
    return out
