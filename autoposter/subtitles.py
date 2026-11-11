"""Subtitles synced to the voice-over: 1-4 words at a time, the word being spoken is highlighted."""
from PIL import Image, ImageDraw, ImageFont

from .render import FONT_BOLD, render_line

W = 1080


class Subtitles:
    def __init__(self, words: list, accent: tuple, size: int = 54, theme: str = "dark"):
        light = theme == "light"
        self.chunks = []
        font = ImageFont.truetype(str(FONT_BOLD), size)
        cur = []
        for w in words or []:
            t0, t1, text, sec = w
            if cur and (len(cur) == 4 or t0 - cur[-1][1] > 0.35 or sec != cur[-1][3] or cur[-1][2][-1:] in ".!?,"):
                self.chunks.append(cur)
                cur = []
            cur.append(w)
        if cur:
            self.chunks.append(cur)
        self.imgs = []
        for ch in self.chunks:
            states = []
            for k in range(len(ch)):
                line = [(w[2], j == k) for j, w in enumerate(ch)]
                im = (render_line(line, font, (22, 22, 26), accent, shadow_a=0.0, glow=False) if light
                      else render_line(line, font, (255, 255, 255), accent))
                if im.width > W - 80:
                    im = im.resize((W - 80, int(im.height * (W - 80) / im.width)), Image.LANCZOS)
                pill = Image.new("RGBA", (im.width - 20, im.height - 46), (0, 0, 0, 0))
                ImageDraw.Draw(pill).rounded_rectangle((0, 0, pill.width - 1, pill.height - 1), radius=pill.height // 2,
                                                       fill=(255, 255, 255, 235) if light else (0, 0, 0, 120))
                full = Image.new("RGBA", im.size, (0, 0, 0, 0))
                full.alpha_composite(pill, (10, 23))
                full.alpha_composite(im)
                states.append(full)
            self.imgs.append(states)

    def draw(self, frame, t: float, cy: int, paste) -> None:
        for ci, ch in enumerate(self.chunks):
            if ch[0][0] - 0.05 <= t <= ch[-1][1] + 0.25:
                k = 0
                for j, w in enumerate(ch):
                    if t >= w[0] - 0.02:
                        k = j
                im = self.imgs[ci][k]
                pop = min(1.0, (t - ch[0][0] + 0.05) / 0.12)
                paste(frame, im, (W - im.width) // 2, cy - im.height // 2 + int((1 - pop) * 14), max(0.0, min(1.0, pop)))
                return
