"""Renders the animated text Reel: background video + animated text + soundtrack."""
import math
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .audio import build_soundtrack
from .config import ASSETS
from .ff import FFMPEG

def _font(name: str) -> Path:
    """Bundled font, else the system Inter (apt: fonts-inter), else DejaVu."""
    for p in (ASSETS / "fonts" / name, Path("/usr/share/fonts/opentype/inter") / name):
        if p.exists():
            return p
    return Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


FONT_BOLD = _font("InterDisplay-ExtraBold.otf")
FONT_SEMI = _font("Inter-SemiBold.otf")
FONT_MED = _font("Inter-Medium.otf")


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def ease_out_cubic(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


def ease_out_back(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


# ------------------------------------------------------------------ text layout
def parse_rich(text: str) -> list[tuple[str, bool]]:
    """'Use *AI* daily.' -> [('Use', False), ('AI', True), ('daily.', False)]"""
    words, hl, glued = [], False, False
    for part in re.split(r"(\*)", text.strip()):
        if part == "*":
            hl = not hl
            continue
        if not part:
            continue
        tokens = part.split()
        if tokens and words and glued and not part[0].isspace():
            # text glued to the previous word, e.g. "*workflow*." keeps the "." attached
            prev, prev_hl = words.pop()
            words.append((prev + tokens.pop(0), prev_hl))
        words.extend((w, hl) for w in tokens)
        glued = not part[-1].isspace()
    return words


def layout_lines(words, font, max_width) -> list[list[tuple[str, bool]]]:
    lines, cur, cur_w = [], [], 0
    space = font.getlength(" ")
    for w, hl in words:
        ww = font.getlength(w)
        if cur and cur_w + space + ww > max_width:
            lines.append(cur)
            cur, cur_w = [], 0
        cur_w += (space if cur else 0) + ww
        cur.append((w, hl))
    if cur:
        lines.append(cur)
    return lines


def render_line(line, font, color, accent) -> Image.Image:
    """Renders one line of rich text to an RGBA image with soft shadow + accent glow."""
    space = font.getlength(" ")
    width = int(sum(font.getlength(w) for w, _ in line) + space * (len(line) - 1)) + 60
    asc, desc = font.getmetrics()
    height = asc + desc + 60
    text = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    dt, dg = ImageDraw.Draw(text), ImageDraw.Draw(glow)
    x = 30
    for w, hl in line:
        dt.text((x, 30), w, font=font, fill=accent if hl else color)
        if hl:
            dg.text((x, 30), w, font=font, fill=accent + (170,))
        x += font.getlength(w) + space
    shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    shadow.putalpha(text.getchannel("A").point(lambda a: int(a * 0.75)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    out = Image.alpha_composite(shadow, glow.filter(ImageFilter.GaussianBlur(14)))
    return Image.alpha_composite(out, text)


def fit_text(text, font_path, start_size, max_width, max_lines, min_size=48):
    size = start_size
    while True:
        font = ImageFont.truetype(str(font_path), size)
        words = parse_rich(text)
        lines = layout_lines(words, font, max_width)
        if len(lines) <= max_lines or size <= min_size:
            # balance: shrink the wrap width as long as the line count stays the same
            lo, hi = max_width * 0.4, max_width
            for _ in range(12):
                mid = (lo + hi) / 2
                if len(layout_lines(words, font, mid)) <= len(lines):
                    hi = mid
                else:
                    lo = mid
            return font, layout_lines(words, font, hi + 1)
        size -= 6


def with_alpha(img: Image.Image, alpha: float) -> Image.Image:
    if alpha >= 0.999:
        return img
    out = img.copy()
    out.putalpha(img.getchannel("A").point(lambda a: int(a * alpha)))
    return out


# ------------------------------------------------------------------ scenes
@dataclass
class Scene:
    kind: str               # hook | slide | cta
    start: float
    duration: float
    lines: list = field(default_factory=list)    # rendered line images
    label: str = ""
    align: str = "left"
    line_gap: int = 0


def build_scenes(post: dict, cfg: dict) -> tuple[list[Scene], float]:
    v, c = cfg["video"], cfg["video"]["colors"]
    W = v["width"]
    color, accent = hex_rgb(c["text"]), hex_rgb(c["accent"])
    scenes, t = [], 0.0

    font, lines = fit_text(post["hook"], FONT_BOLD, 128, W - 160, 4)
    scenes.append(Scene("hook", t, v["hook_seconds"],
                        [render_line(l, font, color, accent) for l in lines],
                        align="center", line_gap=int(font.size * 0.02)))
    t += v["hook_seconds"]

    n = len(post["slides"])
    for i, s in enumerate(post["slides"]):
        words = len(s.replace("*", "").split())
        dur = max(v["slide_seconds"], 1.2 + words * 0.24)  # time to read
        font, lines = fit_text(s, FONT_BOLD, 92, W - 180, 6)
        scenes.append(Scene("slide", t, dur,
                            [render_line(l, font, color, accent) for l in lines],
                            label=f"{i + 1:02d} / {n:02d}", line_gap=int(font.size * 0.04)))
        t += dur

    font, lines = fit_text(post.get("cta") or cfg["brand"]["call_to_action"], FONT_SEMI, 70, W - 200, 3)
    scenes.append(Scene("cta", t, v["cta_seconds"],
                        [render_line(l, font, color, accent) for l in lines], align="center"))
    t += v["cta_seconds"]
    return scenes, t


# ------------------------------------------------------------------ overlay frames
class OverlayRenderer:
    def __init__(self, post, cfg, scenes, total, has_background=True):
        v, c = cfg["video"], cfg["video"]["colors"]
        self.W, self.H, self.fps = v["width"], v["height"], v["fps"]
        self.scenes, self.total = scenes, total
        self.accent, self.accent2 = hex_rgb(c["accent"]), hex_rgb(c["accent2"])
        self.text_color = hex_rgb(c["text"])
        self.brand = cfg["brand"]
        darken = v.get("background_darken", 0.55) if has_background else 0.1
        self.base = self._make_base(darken)
        self.label_font = ImageFont.truetype(str(FONT_SEMI), 36)
        self.brand_img = self._text_img(cfg["brand"]["handle"], ImageFont.truetype(str(FONT_MED), 38),
                                        self.text_color + (210,))
        self.name_img = self._spaced_text(cfg["brand"]["name"].upper(), ImageFont.truetype(str(FONT_BOLD), 96))
        self.label_cache = {}

    def _make_base(self, darken):
        """Static dark layer + vignette so text is always readable."""
        W, H = self.W, self.H
        base = Image.new("RGBA", (W, H), (0, 0, 0, int(255 * darken)))
        vign = Image.new("L", (W, H), 0)
        d = ImageDraw.Draw(vign)
        d.ellipse((-W * 0.35, H * 0.08, W * 1.35, H * 0.92), fill=255)
        vign = vign.filter(ImageFilter.GaussianBlur(180))
        edge = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        edge.putalpha(vign.point(lambda a: int((255 - a) * 0.55)))
        return Image.alpha_composite(base, edge)

    @staticmethod
    def _text_img(text, font, fill):
        w = int(font.getlength(text)) + 20
        asc, desc = font.getmetrics()
        img = Image.new("RGBA", (w, asc + desc + 10), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((10, 5), text, font=font, fill=fill)
        return img

    def _spaced_text(self, text, font, spacing=10):
        widths = [font.getlength(ch) for ch in text]
        w = int(sum(widths) + spacing * (len(text) - 1)) + 80
        asc, desc = font.getmetrics()
        img = Image.new("RGBA", (w, asc + desc + 80), (0, 0, 0, 0))
        glow = img.copy()
        d, dg = ImageDraw.Draw(img), ImageDraw.Draw(glow)
        x = 40
        for ch, cw in zip(text, widths):
            d.text((x, 40), ch, font=font, fill=self.text_color)
            dg.text((x, 40), ch, font=font, fill=self.accent + (200,))
            x += cw + spacing
        return Image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(22)), img)

    def frame(self, t: float) -> Image.Image:
        W, H = self.W, self.H
        f = self.base.copy()
        d = ImageDraw.Draw(f)

        # progress bar
        p = min(1.0, t / self.total)
        d.rounded_rectangle((60, 90, W - 60, 98), radius=4, fill=(255, 255, 255, 50))
        if p > 0:
            x2 = 60 + int((W - 120) * p)
            for i in range(60, x2, 6):  # accent -> accent2 gradient
                k = (i - 60) / (W - 120)
                col = tuple(int(self.accent[j] * (1 - k) + self.accent2[j] * k) for j in range(3))
                d.rectangle((i, 90, min(i + 6, x2), 98), fill=col + (255,))

        # brand handle bottom
        f.alpha_composite(self.brand_img, ((W - self.brand_img.width) // 2, H - 190))

        scene = next((s for s in self.scenes if s.start <= t < s.start + s.duration), self.scenes[-1])
        lt = t - scene.start
        exit_k = ease_out_cubic((lt - (scene.duration - 0.28)) / 0.28) if scene.kind != "cta" else 0.0

        if scene.kind == "cta":
            self._draw_cta(f, scene, lt)
        else:
            self._draw_text_block(f, scene, lt, exit_k)
        return f

    def _draw_text_block(self, f, scene, lt, exit_k):
        W, H = self.W, self.H
        heights = [im.height - 60 + scene.line_gap for im in scene.lines]
        block_h = sum(heights)
        y = (H - block_h) // 2 - 40
        x_left = 90 - 30

        if scene.kind == "slide" and scene.label:
            k = ease_out_cubic(lt / 0.4) * (1 - exit_k)
            lab = self.label_cache.get(scene.label)
            if lab is None:
                lab = self._text_img(scene.label, self.label_font, self.accent + (255,))
                self.label_cache[scene.label] = lab
            f.alpha_composite(with_alpha(lab, k), (x_left + 20 - int(30 * (1 - k)), y - 90))
            dd = ImageDraw.Draw(f)
            bar_w = int(90 * k)
            if bar_w > 0:
                dd.rectangle((x_left + 30, y - 30, x_left + 30 + bar_w, y - 24), fill=self.accent + (int(255 * k),))

        for i, im in enumerate(scene.lines):
            delay = 0.05 + i * 0.09
            k = (lt - delay) / 0.5
            if scene.kind == "hook":
                e = ease_out_back(k)
                a = ease_out_cubic(k * 1.6)
                scale = 0.82 + 0.18 * e
                img = im if abs(scale - 1) < 0.01 else im.resize(
                    (max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.BICUBIC)
                dy = int(40 * (1 - a))
            else:
                a = ease_out_cubic(k)
                img, dy = im, int(70 * (1 - a))
            a *= (1 - exit_k)
            dy -= int(40 * exit_k)
            if a <= 0.01:
                y += heights[i]
                continue
            x = (W - img.width) // 2 if scene.align == "center" else x_left
            yy = y + dy - (img.height - im.height) // 2
            f.alpha_composite(with_alpha(img, a), (x, max(0, yy)))
            y += heights[i]

        if scene.kind == "hook":  # animated accent underline
            k = ease_out_cubic((lt - 0.35) / 0.6) * (1 - exit_k)
            if k > 0:
                w = int(260 * k)
                yy = (H + block_h) // 2 - 10
                ImageDraw.Draw(f).rounded_rectangle(((W - w) // 2, yy, (W + w) // 2, yy + 10),
                                                    radius=5, fill=self.accent + (255,))

    def _draw_cta(self, f, scene, lt):
        W, H = self.W, self.H
        k = ease_out_back(lt / 0.55)
        a = ease_out_cubic(lt / 0.35)
        name = self.name_img
        s = 0.7 + 0.3 * k
        img = name.resize((max(1, int(name.width * s)), max(1, int(name.height * s))), Image.BICUBIC)
        cy = H // 2 - 170
        f.alpha_composite(with_alpha(img, a), ((W - img.width) // 2, cy - img.height // 2))

        # pulsing ring
        d = ImageDraw.Draw(f)
        r = 70 + 18 * math.sin(lt * 6)
        ring_a = int(180 * a)
        cx, ry = W // 2, H // 2 + 330
        d.ellipse((cx - r, ry - r, cx + r, ry + r), outline=self.accent + (ring_a,), width=5)
        d.polygon([(cx - 22, ry - 18), (cx + 22, ry - 18), (cx, ry + 20)], fill=self.accent + (ring_a,))

        y = H // 2 - 20
        for i, im in enumerate(scene.lines):
            k2 = ease_out_cubic((lt - 0.25 - i * 0.08) / 0.45)
            if k2 > 0:
                f.alpha_composite(with_alpha(im, k2), ((W - im.width) // 2, y + int(40 * (1 - k2))))
            y += im.height - 50


# ------------------------------------------------------------------ main render
def sfx_cues(scenes) -> list[tuple[float, str]]:
    cues = [(0.0, "impact")]
    for s in scenes[1:]:
        if s.kind == "slide":
            cues += [(s.start - 0.22, "whoosh"), (s.start + 0.08, "pop")]
        else:  # cta
            cues += [(s.start - 0.9, "riser"), (s.start, "impact"), (s.start + 0.3, "tick")]
    return cues


def render_video(post: dict, cfg: dict, background: Path | None, out: Path, work: Path, seed=None) -> Path:
    v = cfg["video"]
    W, H, fps = v["width"], v["height"], v["fps"]
    scenes, total = build_scenes(post, cfg)
    total = round(total, 2)
    print(f"[render] {len(scenes)} scenes, {total:.1f}s")

    audio = build_soundtrack(total, sfx_cues(scenes), cfg, work / "audio.wav", seed=seed)

    if background:
        bg_in = ["-stream_loop", "-1", "-i", str(background)]
        bg_filter = (
            f"[0:v]scale={int(W * 1.12)}:{int(H * 1.12)}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H}:x='(iw-{W})/2+(iw-{W})/2*sin(t/5)':y='(ih-{H})*t/{total}',"
            f"fps={fps},eq=saturation=1.15:contrast=1.05,setsar=1[bg]"
        )
    else:
        c = v["colors"]
        bg_in = ["-f", "lavfi", "-i",
                 f"gradients=s={W}x{H}:r={fps}:c0={c['bg_top'].lstrip('#')}:c1={c['bg_bottom'].lstrip('#')}"
                 f":c2={c['accent2'].lstrip('#')}:c3={c['bg_top'].lstrip('#')}:n=4:speed=0.012:d={total}"]
        bg_filter = f"[0:v]setsar=1,format=yuv420p[bg]"

    cmd = [
        FFMPEG, "-y", "-v", "error",
        *bg_in,
        "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}", "-r", str(fps), "-i", "pipe:0",
        "-i", str(audio),
        "-filter_complex", f"{bg_filter};[bg][1:v]overlay=format=auto,format=yuv420p[v]",
        "-map", "[v]", "-map", "2:a",
        "-t", f"{total}", "-r", str(fps),
        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-profile:v", "high",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
        "-movflags", "+faststart", str(out),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    renderer = OverlayRenderer(post, cfg, scenes, total, has_background=background is not None)
    frames = int(math.ceil(total * fps))
    try:
        for i in range(frames):
            proc.stdin.write(renderer.frame(i / fps).tobytes())
    except BrokenPipeError:
        pass
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed while rendering the video")
    print(f"[render] saved {out}")
    return out
