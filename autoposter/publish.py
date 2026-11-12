"""Publishing to Instagram + Facebook Page (official Graph API) and media hosting.

Instagram needs a public URL for images (carousels, stories), so images are
uploaded to Vercel Blob first and deleted again after publishing.
"""
import json
import os
import time
from pathlib import Path

import requests

from .config import env
from .instagram import InstagramError, _check, publish_reel
from .llm import redact

BLOB_API = "https://blob.vercel-storage.com"


# ====================================================================== Vercel Blob
def blob_upload(path: Path, folder: str = "media") -> str:
    token = env("BLOB_READ_WRITE_TOKEN")
    ctype = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".mp4": "video/mp4"}[path.suffix.lower()]
    with open(path, "rb") as f:
        r = requests.put(f"{BLOB_API}/{folder}/{path.name}", data=f, timeout=300, headers={
            "authorization": f"Bearer {token}", "x-api-version": "7", "x-content-type": ctype,
            "x-add-random-suffix": "1", "x-cache-control-max-age": "86400"})
    if r.status_code >= 400:
        raise RuntimeError(f"Blob upload failed: HTTP {r.status_code} {redact(r.text)[:200]}")
    return r.json()["url"]


def blob_delete(urls: list[str]) -> None:
    if not urls:
        return
    try:
        requests.post(f"{BLOB_API}/delete", json={"urls": urls}, timeout=60, headers={
            "authorization": f"Bearer {env('BLOB_READ_WRITE_TOKEN')}", "x-api-version": "7"})
    except Exception as e:  # noqa: BLE001 - cleanup is best effort
        print(f"[blob] delete failed: {redact(e)}")


def blob_cleanup(prefix: str, older_than_days: float) -> None:
    """Deletes old preview files (test videos/images)."""
    try:
        r = requests.get(BLOB_API, params={"prefix": prefix, "limit": 1000}, timeout=60, headers={
            "authorization": f"Bearer {env('BLOB_READ_WRITE_TOKEN')}", "x-api-version": "7"})
        if r.status_code >= 400:
            return
        cutoff = time.time() - older_than_days * 86400
        old = []
        for b in r.json().get("blobs", []):
            ts = b.get("uploadedAt", "")
            try:
                import datetime as dt
                t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
            if t < cutoff:
                old.append(b["url"])
        blob_delete(old)
    except Exception as e:  # noqa: BLE001
        print(f"[blob] cleanup failed: {redact(e)}")


# ====================================================================== Graph helpers
def _base(cfg):
    return f"https://graph.facebook.com/{cfg['instagram']['graph_version']}"


def _wait(cfg, container_id, token, tries=60, delay=5):
    for _ in range(tries):
        st = _check(requests.get(f"{_base(cfg)}/{container_id}", params={
            "fields": "status_code,status", "access_token": token}, timeout=30))
        code = st.get("status_code")
        if code in (None, "FINISHED", "PUBLISHED"):
            return
        if code in ("ERROR", "EXPIRED"):
            raise InstagramError(f"processing failed: {st}")
        time.sleep(delay)
    raise InstagramError("timed out waiting for Instagram")


def _permalink(cfg, media_id, token):
    try:
        return _check(requests.get(f"{_base(cfg)}/{media_id}", params={
            "fields": "permalink", "access_token": token}, timeout=30)).get("permalink")
    except InstagramError:
        return None


def _ig_publish(cfg, container_id, token):
    user = env("IG_USER_ID")
    for attempt in range(3):
        try:
            return _check(requests.post(f"{_base(cfg)}/{user}/media_publish", data={
                "creation_id": container_id, "access_token": token}, timeout=60))["id"]
        except InstagramError as e:
            if attempt == 2 or "not ready" not in str(e).lower():
                raise
            time.sleep(10)


# ====================================================================== Instagram
def safe_encode(video: Path) -> Path:
    """Conservative re-encode (constant 30 fps, H.264 high@4.1, AAC 44.1 kHz stereo) - what Instagram never rejects."""
    import subprocess
    from .ff import FFMPEG
    out = video.with_name(video.stem + "-safe.mp4")
    subprocess.run([FFMPEG, "-y", "-v", "error", "-i", str(video), "-r", "30", "-vsync", "cfr", "-c:v", "libx264",
                    "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "21",
                    "-maxrate", "8M", "-bufsize", "16M", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "160k",
                    "-movflags", "+faststart", str(out)], check=True)
    return out


def ig_reel(video: Path, caption: str, cfg: dict) -> dict:
    """Upload with automatic fallbacks: resumable -> safe re-encode -> Instagram fetches it from a public URL."""
    from .llm import redact
    try:
        media_id, link = publish_reel(video, caption, cfg)
        return {"ig_id": media_id, "permalink": link}
    except InstagramError as e:
        if "oauth" in str(e).lower() or "permission" in str(e).lower():
            raise
        print(f"[instagram] upload failed ({redact(e)[:160]}) -> retrying with a safe re-encode")
    safe = safe_encode(video)
    time.sleep(5)
    try:
        media_id, link = publish_reel(safe, caption, cfg)
        return {"ig_id": media_id, "permalink": link, "ig_note": "posted after safe re-encode"}
    except InstagramError as e:
        print(f"[instagram] resumable upload failed again ({redact(e)[:160]}) -> letting Instagram fetch it from a URL")
    url = blob_upload(safe, "media")
    try:
        media_id, link = publish_reel(safe, caption, cfg, video_url=url)
        return {"ig_id": media_id, "permalink": link, "ig_note": "posted via URL upload"}
    finally:
        blob_delete([url])


def ig_carousel(image_urls: list[str], caption: str, cfg: dict) -> dict:
    user, token = env("IG_USER_ID"), env("IG_ACCESS_TOKEN")
    children = []
    for url in image_urls[:10]:
        c = _check(requests.post(f"{_base(cfg)}/{user}/media", data={
            "image_url": url, "is_carousel_item": "true", "access_token": token}, timeout=60))
        children.append(c["id"])
    for c in children:
        _wait(cfg, c, token, tries=30, delay=3)
    box = _check(requests.post(f"{_base(cfg)}/{user}/media", data={
        "media_type": "CAROUSEL", "children": ",".join(children), "caption": caption, "access_token": token}, timeout=60))
    _wait(cfg, box["id"], token, tries=30, delay=4)
    media_id = _ig_publish(cfg, box["id"], token)
    return {"ig_id": media_id, "permalink": _permalink(cfg, media_id, token)}


def ig_story(image_url: str, cfg: dict) -> dict:
    user, token = env("IG_USER_ID"), env("IG_ACCESS_TOKEN")
    c = _check(requests.post(f"{_base(cfg)}/{user}/media", data={
        "media_type": "STORIES", "image_url": image_url, "access_token": token}, timeout=60))
    _wait(cfg, c["id"], token, tries=30, delay=3)
    return {"ig_id": _ig_publish(cfg, c["id"], token)}


# ====================================================================== Facebook Page
def fb_enabled(cfg: dict) -> bool:
    return bool(cfg.get("post_to_facebook", True) and os.environ.get("FB_PAGE_ID"))


def fb_reel(video: Path, caption: str, cfg: dict) -> dict:
    page, token = env("FB_PAGE_ID"), env("IG_ACCESS_TOKEN")
    start = _check(requests.post(f"{_base(cfg)}/{page}/video_reels", data={
        "upload_phase": "start", "access_token": token}, timeout=60))
    vid, upload_url = start["video_id"], start["upload_url"]
    size = video.stat().st_size
    with open(video, "rb") as f:
        _check(requests.post(upload_url, data=f, timeout=600, headers={
            "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)}))
    _check(requests.post(f"{_base(cfg)}/{page}/video_reels", data={
        "upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
        "description": caption, "access_token": token}, timeout=120))
    return {"fb_id": vid, "fb_link": f"https://www.facebook.com/reel/{vid}"}


def _fb_photo(cfg, url, token, page):
    return _check(requests.post(f"{_base(cfg)}/{page}/photos", data={
        "url": url, "published": "false", "access_token": token}, timeout=120))["id"]


def fb_carousel(image_urls: list[str], caption: str, cfg: dict) -> dict:
    page, token = env("FB_PAGE_ID"), env("IG_ACCESS_TOKEN")
    ids = [_fb_photo(cfg, u, token, page) for u in image_urls[:10]]
    data = {"message": caption, "access_token": token}
    for i, pid in enumerate(ids):
        data[f"attached_media[{i}]"] = json.dumps({"media_fbid": pid})
    post = _check(requests.post(f"{_base(cfg)}/{page}/feed", data=data, timeout=120))
    return {"fb_id": post["id"], "fb_link": f"https://www.facebook.com/{post['id']}"}


def fb_story(image_url: str, cfg: dict) -> dict:
    page, token = env("FB_PAGE_ID"), env("IG_ACCESS_TOKEN")
    pid = _fb_photo(cfg, image_url, token, page)
    out = _check(requests.post(f"{_base(cfg)}/{page}/photo_stories", data={
        "photo_id": pid, "access_token": token}, timeout=120))
    return {"fb_id": out.get("post_id") or pid}


def both(ig_fn, fb_fn, cfg) -> dict:
    """Publishes on Instagram, then Facebook; a Facebook failure doesn't undo Instagram."""
    res = ig_fn()
    if fb_enabled(cfg):
        try:
            res.update(fb_fn())
        except Exception as e:  # noqa: BLE001
            res["fb_error"] = redact(f"{type(e).__name__}: {e}")[:400]
            print(f"[facebook] failed: {res['fb_error']}")
    return res
