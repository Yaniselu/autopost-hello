"""Publishes a Reel through the official Instagram Graph API (no password, no ban risk).

Uses the resumable upload flow, so the video is uploaded directly from this
machine — no need to host it on a public URL.
"""
import time
from pathlib import Path

import requests

from .config import env


class InstagramError(RuntimeError):
    pass


def _check(r: requests.Response) -> dict:
    try:
        data = r.json()
    except ValueError:
        raise InstagramError(f"HTTP {r.status_code}: {r.text[:500]}")
    if r.status_code >= 400 or "error" in data:
        raise InstagramError(f"HTTP {r.status_code}: {data.get('error', data)}")
    return data


def publish_reel(video: Path, caption: str, cfg: dict) -> tuple[str, str | None]:
    ig = cfg["instagram"]
    base = f"https://graph.facebook.com/{ig['graph_version']}"
    user_id, token = env("IG_USER_ID"), env("IG_ACCESS_TOKEN")

    # 1) create an upload container
    data = _check(requests.post(f"{base}/{user_id}/media", data={
        "media_type": "REELS",
        "upload_type": "resumable",
        "caption": caption,
        "share_to_feed": "true" if ig.get("share_to_feed", True) else "false",
        "access_token": token,
    }, timeout=60))
    container_id, upload_uri = data["id"], data["uri"]
    print(f"[instagram] container {container_id}")

    # 2) upload the bytes
    size = video.stat().st_size
    with open(video, "rb") as f:
        _check(requests.post(upload_uri, headers={
            "Authorization": f"OAuth {token}",
            "offset": "0",
            "file_size": str(size),
        }, data=f, timeout=600))
    print(f"[instagram] uploaded {size / 1e6:.1f} MB")

    # 3) wait until Instagram finishes processing
    for _ in range(60):
        status = _check(requests.get(f"{base}/{container_id}", params={
            "fields": "status_code,status", "access_token": token}, timeout=30))
        code = status.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise InstagramError(f"processing failed: {status}")
        time.sleep(10)
    else:
        raise InstagramError("timed out waiting for Instagram to process the video")

    # 4) publish
    media = _check(requests.post(f"{base}/{user_id}/media_publish", data={
        "creation_id": container_id, "access_token": token}, timeout=60))
    media_id = media["id"]
    try:
        link = _check(requests.get(f"{base}/{media_id}", params={
            "fields": "permalink", "access_token": token}, timeout=30)).get("permalink")
    except InstagramError:
        link = None
    print(f"[instagram] published {media_id} {link or ''}")
    return media_id, link


# ---------------------------------------------------------------- account connection
def check_connection(cfg: dict) -> str:
    """Returns the @username the token is connected to (raises if the token is bad)."""
    base = f"https://graph.facebook.com/{cfg['instagram']['graph_version']}"
    data = _check(requests.get(f"{base}/{env('IG_USER_ID')}", params={
        "fields": "username", "access_token": env("IG_ACCESS_TOKEN")}, timeout=30))
    return data.get("username", "?")


def connect_account(app_id: str, app_secret: str, short_token: str, graph_version: str) -> list[dict]:
    """Turns a Graph API Explorer token into a never-expiring Page token and finds
    the Instagram business accounts it can post to."""
    base = f"https://graph.facebook.com/{graph_version}"
    long_token = _check(requests.get(f"{base}/oauth/access_token", params={
        "grant_type": "fb_exchange_token", "client_id": app_id,
        "client_secret": app_secret, "fb_exchange_token": short_token,
    }, timeout=30))["access_token"]
    pages = _check(requests.get(f"{base}/me/accounts", params={
        "fields": "name,access_token,instagram_business_account{id,username}",
        "access_token": long_token, "limit": 100,
    }, timeout=30))
    accounts = []
    for page in pages.get("data", []):
        ig = page.get("instagram_business_account")
        if ig:
            accounts.append({"page": page["name"], "username": ig.get("username"),
                             "ig_user_id": ig["id"], "token": page["access_token"]})
    return accounts
