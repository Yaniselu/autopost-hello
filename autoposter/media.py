"""Downloads a free vertical stock video background from Pexels."""
import random
from pathlib import Path

import requests

from .config import env


def fetch_pexels_video(query: str, dest: Path, min_duration: float) -> Path | None:
    key = env("PEXELS_API_KEY", required=False)
    if not key:
        print("[media] PEXELS_API_KEY not set -> using gradient background")
        return None
    try:
        r = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": key},
            params={"query": query, "orientation": "portrait", "size": "medium", "per_page": 20},
            timeout=30,
        )
        r.raise_for_status()
        videos = [v for v in r.json().get("videos", []) if v.get("duration", 0) >= min(min_duration, 8)]
        if not videos:
            fallback = requests.get(
                "https://api.pexels.com/videos/search",
                headers={"Authorization": key},
                params={"query": "abstract technology dark", "orientation": "portrait", "per_page": 20},
                timeout=30,
            )
            videos = fallback.json().get("videos", [])
        if not videos:
            return None
        video = random.choice(videos[:10])
        files = [f for f in video["video_files"] if f.get("height") and f["height"] >= f.get("width", 0)]
        files = files or video["video_files"]
        # choose the smallest file that is still >= 1280px tall (fast download, good quality)
        files.sort(key=lambda f: (f.get("height", 0) < 1280, f.get("height", 0)))
        link = files[0]["link"]
        with requests.get(link, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(1 << 16):
                    f.write(chunk)
        print(f"[media] background: Pexels video {video['id']} by {video.get('user', {}).get('name')}")
        return dest
    except Exception as e:
        print(f"[media] Pexels failed ({e}) -> using gradient background")
        return None
