"""English AI voice-over (free Microsoft Edge neural voices via edge-tts) with word timings
for synced subtitles. If the voice service is unreachable the reel is made without voice.

Flow: synthesize each section -> stretch the video sections to fit the voice -> place the clips
on the final timeline -> one voice track + absolute word timings.
"""
import asyncio
import random
import subprocess
from pathlib import Path

import numpy as np

from .audio import SR
from .ff import FFMPEG

VOICES = ["en-US-AndrewMultilingualNeural", "en-US-AvaMultilingualNeural",
          "en-US-BrianMultilingualNeural", "en-US-EmmaMultilingualNeural"]
LEAD = {"hook": 0.15, "problem": 0.35, "step": 0.15, "result": 0.3, "cta": 0.25}  # pause before speaking
TAIL = 0.45  # breathing room after a line


def _clean(text: str) -> str:
    return " ".join(str(text or "").replace("*", "").split())


def lines_for(post: dict, cfg: dict) -> dict:
    vo = post.get("voiceover") or {}
    steps = post["solution"]["steps"]
    vsteps = vo.get("steps") if isinstance(vo.get("steps"), list) and len(vo.get("steps")) >= len(steps) else None
    return {
        "hook": _clean(vo.get("hook") or post["hook"]),
        "problem": _clean(vo.get("problem") or post["problem"]["text"]),
        "steps": [_clean((vsteps or [None] * len(steps))[i] or f"{s['title']}. {s['text']}") for i, s in enumerate(steps)],
        "result": _clean(vo.get("result") or post["result"]),
        "cta": _clean(vo.get("cta") or f"Follow {cfg['brand']['name']} for more."),
    }


def speakable(text: str) -> str:
    """Only what a TTS voice can read: no emojis/symbols, plain quotes, no markdown."""
    import re
    import unicodedata
    t = str(text or "").replace("*", "").replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    t = t.replace("\u2014", ", ").replace("\u2013", ", ").replace("&", " and ").replace("%", " percent").replace("/", " or ")
    t = "".join(ch for ch in t if unicodedata.category(ch)[0] in "LNPZ" or ch in "$'")
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s+([,.!?])", r"\1", t).strip(" ,")
    return t if re.search(r"[A-Za-z0-9]", t) else ""


async def _synth_once(text: str, voice: str, mp3: Path, rate: str) -> list:
    import edge_tts
    words = []
    try:
        com = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    except TypeError:  # older edge-tts versions emit word boundaries by default
        com = edge_tts.Communicate(text, voice, rate=rate)
    with open(mp3, "wb") as f:
        async for ch in com.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                words.append((ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7, ch["text"]))
    return words


async def _synth(text: str, voice: str, mp3: Path, rate: str) -> list:
    """Retries (the free service sometimes drops a request) and falls back to the other voices."""
    import time as _t
    text = speakable(text) or "Here's how."
    tries = [voice, voice] + [v for v in VOICES if v != voice][:2]
    last = None
    for k, v in enumerate(tries):
        try:
            words = await _synth_once(text, v, mp3, rate if k < 2 else "+0%")
            if mp3.exists() and mp3.stat().st_size > 2000:
                return words
            last = RuntimeError("empty audio")
        except Exception as e:  # noqa: BLE001
            last = e
        _t.sleep(1.5 * (k + 1))
    raise last


def _decode(mp3: Path) -> np.ndarray:
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", str(mp3), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).astype(np.float64)


def make_voiceover(post: dict, cfg: dict, seed: int, work: Path, history: list | None = None) -> dict | None:
    if not (cfg.get("voice") or {}).get("enabled", True):
        return None
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        print("[voice] edge-tts not installed -> no voice-over")
        return None
    vc = cfg.get("voice") or {}
    voices = [vc["voice"]] if vc.get("voice") in VOICES else (vc.get("voices") or VOICES)
    last = next((h.get("voice") for h in reversed(history or []) if h.get("voice")), None)
    choices = [v for v in voices if v != last] or voices
    voice = random.Random(seed).choice(choices)
    rate = (cfg.get("voice") or {}).get("rate", "+6%")
    lines = lines_for(post, cfg)
    clips = {}
    try:
        items = [("hook", lines["hook"]), ("problem", lines["problem"])]
        items += [(f"step{i}", s) for i, s in enumerate(lines["steps"])]
        items += [("result", lines["result"]), ("cta", lines["cta"])]
        for key, text in items:
            mp3 = work / f"vo-{key}.mp3"
            words = asyncio.run(_synth(text, voice, mp3, rate))
            audio = _decode(mp3)
            if len(audio) < SR * 0.3:
                raise RuntimeError(f"empty audio for {key}")
            clips[key] = {"audio": audio, "dur": len(audio) / SR, "words": words, "text": text}
    except Exception as e:  # noqa: BLE001 - voice is a bonus, never block the post
        print(f"[voice] voice-over unavailable ({type(e).__name__}: {e}) -> continuing without voice")
        return None
    print(f"[voice] {voice}: {sum(c['dur'] for c in clips.values()):.1f}s of speech")
    return {"voice": voice, "clips": clips, "n_steps": len(lines["steps"])}


def section_durations(vo: dict | None) -> dict | None:
    """Minimum section lengths so every line is spoken completely."""
    if not vo:
        return None
    c = vo["clips"]
    return {
        "hook": LEAD["hook"] + c["hook"]["dur"] + TAIL,
        "problem": LEAD["problem"] + c["problem"]["dur"] + TAIL,
        "steps": [LEAD["step"] + c[f"step{i}"]["dur"] + 0.35 for i in range(vo["n_steps"])],
        "result": LEAD["result"] + c["result"]["dur"] + TAIL,
        "cta": LEAD["cta"] + c["cta"]["dur"] + 1.4,  # leave time for the follow tap
    }


def assemble(vo: dict | None, tl: dict, total: float) -> tuple[np.ndarray | None, list]:
    """Places the clips on the final timeline -> (mono voice track, [(t0, t1, word, section)])."""
    if not vo:
        return None, []
    n = int(total * SR) + 1
    track = np.zeros(n)
    words = []
    S = tl["sections"]
    starts = {"hook": S["hook"]["start"] + LEAD["hook"], "problem": S["problem"]["start"] + LEAD["problem"],
              "result": S["result"]["start"] + LEAD["result"], "cta": S["cta"]["start"] + LEAD["cta"]}
    for i, st in enumerate(tl["steps"]):
        starts[f"step{i}"] = st["start"] + LEAD["step"]
    for key, clip in vo["clips"].items():
        t0 = starts.get(key)
        if t0 is None:
            continue
        i0 = int(t0 * SR)
        a = clip["audio"][: max(0, n - i0)]
        track[i0:i0 + len(a)] += a
        sec = "solution" if key.startswith("step") else key
        words += [(t0 + w0, t0 + w1, w, sec) for w0, w1, w in clip["words"]]
    peak = np.max(np.abs(track)) or 1.0
    return track / peak * 0.92, words
