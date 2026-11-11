"""'Repost to story': after a reel or carousel is published, a 9:16 story announcing it.

The Instagram API has no "share this post to my story" endpoint (and no clickable
stickers), so we build the same look ourselves: the post's frame/cover in a card
over a blurred version of itself, with a "NEW REEL" label.
"""
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .ff import FFMPEG
from .render import FONT_BOLD, FONT_MED, FONT_SEMI

W, H = 1080, 1920


def frame_from_video(video: Path, out: Path, at: float = 1.6) -> Path:
    subprocess.run([FFMPEG, "-y", "-v", "error", "-ss", str(at), "-i", str(video), "-frames:v", "1", "-q:v", "2", str(out)],
                   check=True)
    return out


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    s = max(w / img.width, h / img.height)
    im = img.resize((int(img.width * s) + 1, int(img.height * s) + 1), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def make_repost_light(src: Image.Image, kind: str, cfg: dict, out: Path, accent, accent2) -> Path:
    """Light version: warm paper, dotted texture, the post as a tilted card with a soft shadow, ink typography."""
    import math
    from .light import INK, PAPER, rounded, shadow, spaced
    canvas = Image.new("RGBA", (W, H), PAPER + (255,))
    d = ImageDraw.Draw(canvas)
    for y in range(20, 640, 32):  # dot grid fading down
        a = int(24 * (1 - y / 640))
        for x in range(20, W, 32):
            d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=INK + (a,))
    # soft accent blob behind the card
    blob = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(blob).ellipse((140, 520, 940, 1320), fill=tuple(int(c * 0.5 + 255 * 0.5) for c in accent) + (70,))
    canvas.alpha_composite(blob.filter(ImageFilter.GaussianBlur(120)))
    # dashed ring
    ring = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring)
    for k in range(40):
        rd.arc((90, 470, 990, 1370), k * 9, k * 9 + 4, fill=tuple(accent) + (150,), width=4)
    canvas.alpha_composite(ring)

    max_w, max_h = 760, 1140
    s = min(max_w / src.width, max_h / src.height)
    cw, ch = int(src.width * s), int(src.height * s)
    pad = 18
    card = rounded(cw + 2 * pad, ch + 2 * pad, 52, (255, 255, 255, 255))
    img = src.resize((cw, ch), Image.LANCZOS).convert("RGBA")
    m = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, cw - 1, ch - 1), radius=38, fill=255)
    card.paste(img, (pad, pad), m)
    sh, sm = shadow(card.width, card.height, 52, 34, 90)
    full = Image.new("RGBA", (sh.width, sh.height), (0, 0, 0, 0))
    full.alpha_composite(sh, (0, 24))
    full.alpha_composite(card, (sm, sm))
    full = full.rotate(-3, resample=Image.BICUBIC, expand=True)
    canvas.alpha_composite(full, ((W - full.width) // 2, 330 + (max_h + 2 * pad - full.height) // 2 + 20))

    # label pill (ink) with accent play dot
    label = "NEW REEL" if kind == "reel" else "NEW POST"
    lab = spaced(label, ImageFont.truetype(str(FONT_BOLD), 42), (255, 255, 255, 255), 6)
    lw = lab.width + 140
    pill = rounded(lw, 100, 50, INK + (255,))
    pd = ImageDraw.Draw(pill)
    pd.ellipse((24, 22, 80, 78), fill=tuple(accent) + (255,))
    if kind == "reel":
        pd.polygon([(44, 36), (44, 64), (66, 50)], fill=(255, 255, 255, 255))
    else:
        pd.line([(42, 58), (62, 38)], fill=(255, 255, 255, 255), width=6)
        pd.line([(48, 38), (62, 38), (62, 52)], fill=(255, 255, 255, 255), width=6)
    pill.alpha_composite(lab, (100, (100 - lab.height) // 2))
    canvas.alpha_composite(pill, ((W - lw) // 2, 170))
    # sparkles around the card
    for (x, y, r) in ((150, 420, 26), (950, 560, 20), (120, 1380, 18), (960, 1300, 28)):
        pts = [(x + math.cos(a * math.pi / 4) * (r if a % 2 == 0 else r * 0.25), y + math.sin(a * math.pi / 4) * (r if a % 2 == 0 else r * 0.25)) for a in range(8)]
        d.polygon(pts, fill=tuple(accent if x < 500 else accent2) + (255,))

    bf = ImageFont.truetype(str(FONT_BOLD), 50)
    hf = ImageFont.truetype(str(FONT_MED), 38)
    msg = "Watch it on our profile" if kind == "reel" else "Swipe through it on our profile"
    d.text(((W - bf.getlength(msg)) / 2, 1610), msg, font=bf, fill=INK + (255,))
    d.rounded_rectangle(((W - 140) / 2, 1690, (W + 140) / 2, 1700), radius=5, fill=tuple(accent) + (255,))
    handle = cfg["brand"]["handle"]
    d.text(((W - hf.getlength(handle)) / 2, 1726), handle, font=hf, fill=INK + (150,))
    canvas.convert("RGB").save(out, quality=93)
    return out


def make_repost_story(source: Path, kind: str, cfg: dict, out: Path, accent=(120, 240, 255), accent2=(190, 140, 255)) -> Path:
    src = Image.open(source).convert("RGB")
    if cfg.get("video", {}).get("theme", "light") == "light":
        return make_repost_light(src, kind, cfg, out, accent, accent2)
    bg = _cover(src, W, H).resize((W // 6, H // 6)).filter(ImageFilter.GaussianBlur(6)).resize((W, H), Image.BICUBIC)
    bg = ImageEnhance.Brightness(bg).enhance(0.45)
    canvas = bg.convert("RGBA")

    # card with the post itself
    max_w, max_h = 820, 1230
    s = min(max_w / src.width, max_h / src.height)
    cw, ch = int(src.width * s), int(src.height * s)
    card = src.resize((cw, ch), Image.LANCZOS).convert("RGBA")
    mask = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, cw - 1, ch - 1), radius=44, fill=255)
    card.putalpha(mask)
    cx, cy = (W - cw) // 2, 330 + (max_h - ch) // 2
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((cx + 6, cy + 30, cx + cw + 6, cy + ch + 40), radius=50, fill=(0, 0, 0, 170))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(28)))
    canvas.alpha_composite(card, (cx, cy))
    ring = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(ring).rounded_rectangle((cx - 2, cy - 2, cx + cw + 1, cy + ch + 1), radius=46, outline=(255, 255, 255, 120), width=3)
    canvas.alpha_composite(ring)

    d = ImageDraw.Draw(canvas)
    # top label pill with gradient
    label = "NEW REEL  ▶" if kind == "reel" else "NEW POST  ↗"
    lf = ImageFont.truetype(str(FONT_BOLD), 46)
    lw = int(lf.getlength(label)) + 90
    pill = Image.new("RGBA", (lw, 96), (0, 0, 0, 0))
    grad = Image.linear_gradient("L").rotate(90).resize((lw, 96))
    col = Image.composite(Image.new("RGBA", (lw, 96), accent2 + (255,)), Image.new("RGBA", (lw, 96), accent + (255,)), grad)
    pm = Image.new("L", (lw, 96), 0)
    ImageDraw.Draw(pm).rounded_rectangle((0, 0, lw - 1, 95), radius=48, fill=255)
    pill.paste(col, (0, 0), pm)
    ImageDraw.Draw(pill).text((45, 20), label, font=lf, fill=(7, 16, 24, 255))
    canvas.alpha_composite(pill, ((W - lw) // 2, 170))

    # bottom text
    bf = ImageFont.truetype(str(FONT_SEMI), 44)
    hf = ImageFont.truetype(str(FONT_MED), 38)
    msg = "Watch it on our profile" if kind == "reel" else "Swipe through it on our profile"
    d.text(((W - bf.getlength(msg)) / 2, 1640), msg, font=bf, fill=(255, 255, 255, 240))
    handle = cfg["brand"]["handle"]
    d.text(((W - hf.getlength(handle)) / 2, 1712), handle, font=hf, fill=(255, 255, 255, 190))
    canvas.convert("RGB").save(out, quality=93)
    return out
