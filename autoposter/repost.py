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


def make_repost_story(source: Path, kind: str, cfg: dict, out: Path, accent=(120, 240, 255), accent2=(190, 140, 255)) -> Path:
    src = Image.open(source).convert("RGB")
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
