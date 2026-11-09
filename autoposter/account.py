"""Reads the real Instagram account (profile photo/logo, bio, followers, latest posts)
and learns its style from the existing reels and carousels.

* profile + grid -> shown on the phone in the CTA ("Follow") scene and on the last carousel slide
* style guide    -> built by Gemini from the captions, engagement and thumbnails of the
                    latest posts; cached in data/style_guide.json and refreshed every few
                    days, so it costs one request every ~3 days.
"""
import base64
import datetime as dt
import io
import json
import os

import requests
from PIL import Image, ImageDraw

from .config import ASSETS, DATA, env

LOGO_FILE = ASSETS / "logo.png"


def local_logo() -> tuple[bytes | None, str | None]:
    """assets/logo.png -> (square JPEG bytes for round avatars, white-on-transparent PNG data URL for 3D/overlays)."""
    if not LOGO_FILE.exists():
        return None, None
    im = Image.open(LOGO_FILE).convert("RGB")
    side = min(im.size)
    im = im.crop(((im.width - side) // 2, (im.height - side) // 2, (im.width + side) // 2, (im.height + side) // 2))
    buf = io.BytesIO()
    im.resize((512, 512), Image.LANCZOS).save(buf, "JPEG", quality=95)
    # mark only: luminance becomes alpha, colour white (works on any background)
    mark = im.convert("L")
    bbox = mark.point(lambda v: 255 if v > 60 else 0).getbbox() or (0, 0, side, side)
    mark = mark.crop(bbox)
    pad = int(max(mark.size) * 0.06)
    canvas = Image.new("L", (max(mark.size) + 2 * pad, max(mark.size) + 2 * pad), 0)
    canvas.paste(mark, ((canvas.width - mark.width) // 2, (canvas.height - mark.height) // 2))
    canvas = canvas.resize((512, 512), Image.LANCZOS)
    rgba = Image.new("RGBA", canvas.size, (255, 255, 255, 0))
    rgba.putalpha(canvas)
    b2 = io.BytesIO()
    rgba.save(b2, "PNG")
    return buf.getvalue(), "data:image/png;base64," + base64.b64encode(b2.getvalue()).decode()
from .llm import generate, redact

STYLE_FILE = DATA / "style_guide.json"
FIELDS = "id,caption,media_type,media_product_type,media_url,thumbnail_url,permalink,timestamp,like_count,comments_count"


def _base(cfg):
    return f"https://graph.facebook.com/{cfg['instagram']['graph_version']}"


def _get(cfg, path, **params):
    params["access_token"] = env("IG_ACCESS_TOKEN")
    r = requests.get(f"{_base(cfg)}/{path}", params=params, timeout=30)
    data = r.json()
    if r.status_code >= 400 or "error" in data:
        raise RuntimeError(redact(str(data.get("error", data)))[:300])
    return data


def _img_bytes(url: str, size: int) -> bytes | None:
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        im = Image.open(io.BytesIO(r.content)).convert("RGB")
        im.thumbnail((size, size))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        return None


def _data_url(b: bytes | None) -> str | None:
    return "data:image/jpeg;base64," + base64.b64encode(b).decode() if b else None


def fetch_account(cfg: dict, media_limit: int = 30) -> dict | None:
    """Profile + latest media. Returns None when the account isn't connected."""
    if not (os.environ.get("IG_USER_ID") and os.environ.get("IG_ACCESS_TOKEN")):
        return None
    try:
        uid = env("IG_USER_ID")
        prof = _get(cfg, uid, fields="username,name,biography,profile_picture_url,followers_count,media_count,website")
        media = _get(cfg, f"{uid}/media", fields=FIELDS, limit=media_limit).get("data", [])
        prof["media"] = media
        return prof
    except Exception as e:  # noqa: BLE001
        print(f"[account] could not read the account: {redact(e)}")
        return None


def logo_png(avatar_jpeg: bytes, size: int = 512) -> Image.Image:
    """Circular logo with transparent corners."""
    im = Image.open(io.BytesIO(avatar_jpeg)).convert("RGBA").resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    im.putalpha(mask.resize((size, size), Image.LANCZOS))
    return im


def render_assets(acct: dict | None) -> dict:
    """What the renderer needs: logo, avatar + 9 real grid thumbnails (as data URLs) and the numbers."""
    logo_jpeg, logo_mark = local_logo()
    if not acct:
        return {"avatar": _data_url(logo_jpeg), "avatar_bytes": logo_jpeg, "logo_mark": logo_mark} if logo_jpeg else {}
    avatar = _img_bytes(acct.get("profile_picture_url", ""), 512) if acct.get("profile_picture_url") else None
    avatar = logo_jpeg or avatar  # the official logo file wins over the (compressed) profile photo
    grid = []
    for m in acct.get("media", [])[:12]:
        url = m.get("thumbnail_url") or (m.get("media_url") if m.get("media_type") != "VIDEO" else None)
        b = _img_bytes(url, 300) if url else None
        if b:
            grid.append(_data_url(b))
        if len(grid) == 9:
            break
    return {"username": acct.get("username"), "name": acct.get("name") or acct.get("username"),
            "followers": acct.get("followers_count"), "posts": acct.get("media_count"),
            "avatar": _data_url(avatar), "avatar_bytes": avatar, "logo_mark": logo_mark, "grid": grid}


STYLE_PROMPT = """You are a senior social media strategist. Study this Instagram account so new posts
fit it perfectly and perform better.
Account: @{username} - {name}. Bio: "{bio}". Followers: {followers}.
Latest posts (newest first) with engagement:
{posts}
The attached images are thumbnails of the top-performing posts.

Write a compact style guide (be specific, this guides an AI that writes new reels/carousels):
Return ONLY JSON: {{
 "what_they_sell": "1 sentence, from the bio/posts",
 "audience": "...", "language": "language used in captions", "tone": "...",
 "recurring_topics": ["..."], "best_performing_patterns": ["what the top posts have in common"],
 "hook_examples": ["2-4 hooks in their voice"], "cta_style": "...",
 "visual_notes": "colours, layouts, typical on-screen text seen in the thumbnails",
 "do": ["..."], "dont": ["..."]
}}"""


def style_guide(cfg: dict, acct: dict | None, max_age_days: float = 3) -> dict:
    """Cached style guide learned from the account's own posts."""
    cached = {}
    try:
        cached = json.loads(STYLE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if not acct:
        return cached.get("guide", {})
    media = acct.get("media", [])
    fresh = cached.get("time") and (dt.datetime.now(dt.timezone.utc) -
                                    dt.datetime.fromisoformat(cached["time"])).days < max_age_days
    if fresh and abs(cached.get("media_count", 0) - len(media)) < 3:
        return cached.get("guide", {})
    if not media:
        return cached.get("guide", {})

    def score(m):
        return (m.get("like_count") or 0) + 3 * (m.get("comments_count") or 0)

    lines = []
    for m in media[:25]:
        kind = m.get("media_product_type") or m.get("media_type")
        cap = (m.get("caption") or "").replace("\n", " ")[:220]
        lines.append(f"- [{kind}] likes={m.get('like_count', 0)} comments={m.get('comments_count', 0)}: {cap}")
    top = sorted(media, key=score, reverse=True)[:6]
    images = [b for b in (_img_bytes(m.get("thumbnail_url") or m.get("media_url") or "", 384) for m in top) if b]
    try:
        guide = generate(STYLE_PROMPT.format(username=acct.get("username"), name=acct.get("name", ""),
                                             bio=acct.get("biography", ""), followers=acct.get("followers_count"),
                                             posts="\n".join(lines)), cfg, images=images)
    except Exception as e:  # noqa: BLE001
        print(f"[account] style guide failed: {redact(e)}")
        return cached.get("guide", {})
    STYLE_FILE.write_text(json.dumps({"time": dt.datetime.now(dt.timezone.utc).isoformat(), "media_count": len(media),
                                      "guide": guide}, indent=1, ensure_ascii=False), encoding="utf-8")
    print("[account] style guide updated from the account's own posts")
    return guide


def recent_topics(acct: dict | None) -> list[str]:
    """First line of the latest captions, so new posts don't repeat them."""
    out = []
    for m in (acct or {}).get("media", [])[:20]:
        first = (m.get("caption") or "").strip().split("\n")[0][:90]
        if first:
            out.append(first)
    return out
