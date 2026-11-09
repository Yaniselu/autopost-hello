import json
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
DATA = ROOT / "data"
OUTPUT = ROOT / "output"
SETTINGS_FILE = ROOT / "settings.json"


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader (KEY=VALUE lines) for local runs."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_settings() -> dict:
    """settings.json is written by the web panel and overrides config.yaml."""
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except ValueError:
            print("[config] settings.json is invalid, ignoring it")
    return {}


def load_config() -> dict:
    load_dotenv()
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    s = load_settings()
    if s.get("times") is not None:
        cfg["schedule"]["times"] = s["times"]
    for key in ("language", "hashtags_count", "content_pillars"):
        if s.get(key):
            cfg[key] = s[key]
    cfg["brand"].update({k: v for k, v in (s.get("brand") or {}).items() if v})
    cfg["video"].update({k: v for k, v in (s.get("video") or {}).items() if v})
    cfg["timezone"] = s.get("timezone", "Europe/Bucharest")
    cfg["paused"] = bool(s.get("paused", False))
    cfg["post_to_facebook"] = bool(s.get("post_to_facebook", True))
    cfg["stories_per_slot"] = int(s.get("stories_per_slot", 1) or 1)
    cfg["comments"] = s.get("comments") or {"enabled": True}
    cfg["instagram_username"] = s.get("instagram_username", "")
    return cfg


def env(name: str, required: bool = True) -> str | None:
    value = os.environ.get(name, "").strip()
    if required and not value:
        raise SystemExit(f"Lipsește variabila {name}. Pune-o în .env sau în GitHub Secrets.")
    return value or None
