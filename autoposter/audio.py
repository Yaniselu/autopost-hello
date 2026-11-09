"""Music + sound effects.

Uses your own royalty-free tracks from assets/music/ if present; otherwise it
composes a short electronic track procedurally (so it's 100% copyright-free).
All sound effects are synthesized, no external files needed.
"""
import random
import subprocess
import wave
from pathlib import Path

import numpy as np

from .config import ASSETS
from .ff import FFMPEG

SR = 44100


# ------------------------------------------------------------------ helpers
def _t(seconds: float) -> np.ndarray:
    return np.arange(int(seconds * SR)) / SR


def _one_pole_lowpass(x: np.ndarray, cutoff_hz) -> np.ndarray:
    """One-pole lowpass. cutoff_hz may be a scalar or a per-sample array."""
    cutoff = np.broadcast_to(np.asarray(cutoff_hz, dtype=float), x.shape)
    a = 1.0 - np.exp(-2.0 * np.pi * cutoff / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc += a[i] * (x[i] - acc)
        y[i] = acc
    return y


def _midi_hz(note: float) -> float:
    return 440.0 * 2 ** ((note - 69) / 12)


# ------------------------------------------------------------------ SFX
def sfx_whoosh(duration=0.55, rising=True) -> np.ndarray:
    t = _t(duration)
    noise = np.random.uniform(-1, 1, len(t))
    p = t / duration
    sweep = 300 + 5000 * (p if rising else 1 - p) ** 2
    y = _one_pole_lowpass(noise, sweep)
    y -= _one_pole_lowpass(y, 150)  # remove rumble
    env = np.sin(np.pi * p) ** 2
    return y * env * 1.6


def sfx_pop() -> np.ndarray:
    t = _t(0.12)
    freq = 900 * np.exp(-t * 30) + 220
    phase = 2 * np.pi * np.cumsum(freq) / SR
    return np.sin(phase) * np.exp(-t * 38) * 0.8


def sfx_tick() -> np.ndarray:
    t = _t(0.05)
    return np.sin(2 * np.pi * 2400 * t) * np.exp(-t * 120) * 0.35


def sfx_impact() -> np.ndarray:
    t = _t(1.2)
    freq = 110 * np.exp(-t * 6) + 38
    phase = 2 * np.pi * np.cumsum(freq) / SR
    boom = np.sin(phase) * np.exp(-t * 3.5)
    noise = _one_pole_lowpass(np.random.uniform(-1, 1, len(t)), 2500) * np.exp(-t * 18)
    return np.tanh((boom + noise * 0.7) * 1.8) * 0.9


def sfx_riser(duration=1.0) -> np.ndarray:
    t = _t(duration)
    p = t / duration
    freq = 200 + 1400 * p ** 2
    tone = np.sin(2 * np.pi * np.cumsum(freq) / SR) * 0.25
    noise = _one_pole_lowpass(np.random.uniform(-1, 1, len(t)), 500 + 7000 * p) * 0.6
    return (tone + noise) * p ** 2


def sfx_alert() -> np.ndarray:
    out = []
    for f, d in ((988, 0.09), (0, 0.03), (740, 0.12)):
        t = _t(d)
        out.append(np.sign(np.sin(2 * np.pi * f * t)) * 0.18 * np.exp(-t * 18) if f else np.zeros(len(t)))
    return _one_pole_lowpass(np.concatenate(out), 4000) * 1.6


def sfx_glitch() -> np.ndarray:
    rng = np.random.default_rng(5)
    parts = []
    for _ in range(7):
        d = rng.uniform(0.02, 0.06)
        t = _t(d)
        if rng.random() < 0.5:
            sig = np.sign(np.sin(2 * np.pi * rng.uniform(200, 1800) * t))
        else:
            sig = np.round(rng.uniform(-1, 1, len(t)) * 3) / 3
        parts.append(sig * rng.uniform(0.15, 0.4))
        parts.append(np.zeros(int(rng.uniform(0.005, 0.02) * SR)))
    return np.concatenate(parts) * 0.8


def sfx_chime() -> np.ndarray:
    t = _t(1.4)
    y = np.zeros(len(t))
    for base in (1318.5, 1975.5):
        for k, (ratio, amp, dec) in enumerate(((1, 1, 3), (2.76, 0.35, 5), (5.4, 0.15, 8))):
            y += np.sin(2 * np.pi * base * ratio * t) * amp * np.exp(-t * dec)
    return y * 0.16


# ------------------------------------------------------------------ music
PROGRESSIONS = [
    [0, -4, 3, -2],    # i - VI - III - VII  (Am F C G)
    [0, 3, -2, -4],    # i - III - VII - VI
    [0, -4, -2, 0],    # i - VI - VII - i
    [0, 5, -4, -2],    # i - iv - VI - VII
]


def _chord(root: int, minor: bool) -> list[int]:
    return [root, root + (3 if minor else 4), root + 7]


def _note(freq: float, dur: float, harmonics=6, decay=None, detune=0.0) -> np.ndarray:
    t = _t(dur)
    y = np.zeros(len(t))
    for k in range(1, harmonics + 1):
        y += np.sin(2 * np.pi * freq * k * (1 + detune) * t) / k ** 1.6
    if decay:
        y *= np.exp(-t * decay)
    return y


def compose_music(duration: float, seed: int | None = None) -> np.ndarray:
    rng = random.Random(seed)
    bpm = rng.choice([100, 105, 110, 115, 120, 124])
    beat = 60 / bpm
    bar = beat * 4
    key = rng.choice([57, 58, 59, 60, 61, 62])  # A3..D4 roots (minor keys)
    prog = rng.choice(PROGRESSIONS)
    n = int(duration * SR) + SR
    left, right = np.zeros(n), np.zeros(n)

    def add(sig, start, gain=1.0, pan=0.0):
        i = int(start * SR)
        if i >= n:
            return
        sig = sig[: n - i] * gain
        left[i:i + len(sig)] += sig * (1 - pan) * 0.5 * 2 ** 0.5
        right[i:i + len(sig)] += sig * (1 + pan) * 0.5 * 2 ** 0.5

    minor_degrees = {0: True, 3: False, -4: False, -2: False, 5: True, 7: True}
    bars = int(duration / bar) + 2
    for b in range(bars):
        deg = prog[b % len(prog)]
        root = key + deg
        notes = _chord(root, minor_degrees.get(deg, False))
        start = b * bar
        # pad (slow attack), slightly detuned L/R
        for m in notes:
            pad = _note(_midi_hz(m - 12), bar + 0.3, harmonics=5)
            attack = np.minimum(1, _t(bar + 0.3) / 0.35)
            release = np.minimum(1, (bar + 0.3 - _t(bar + 0.3)) / 0.3)
            pad *= attack * release
            add(pad, start, 0.06, -0.4)
            add(_note(_midi_hz(m - 12), bar + 0.3, 5, detune=0.004) * attack * release, start, 0.06, 0.4)
        # bass
        for q in range(4):
            add(_note(_midi_hz(root - 24), beat * 0.9, 3, decay=3), start + q * beat, 0.22)
        # arpeggio pluck on 8th notes
        arp = notes + [notes[0] + 12, notes[1] + 12]
        pattern = rng.choice([[0, 1, 2, 3, 2, 1, 3, 4], [0, 2, 1, 3, 0, 2, 4, 3], [4, 3, 2, 1, 2, 3, 0, 2]])
        for e in range(8):
            m = arp[pattern[e] % len(arp)] + 12
            add(_note(_midi_hz(m), beat * 0.6, 4, decay=9), start + e * beat / 2, 0.07,
                -0.5 if e % 2 else 0.5)

    # drums (start after the first bar for a small intro)
    t_kick = _t(0.35)
    kick = np.sin(2 * np.pi * np.cumsum(140 * np.exp(-t_kick * 25) + 45) / SR) * np.exp(-t_kick * 9)
    hat = np.random.uniform(-1, 1, int(0.05 * SR))
    hat = (hat - _one_pole_lowpass(hat, 7000)) * np.exp(-_t(0.05) * 70)
    clap = np.random.uniform(-1, 1, int(0.18 * SR))
    clap = (clap - _one_pole_lowpass(clap, 1200)) * np.exp(-_t(0.18) * 22)
    total_beats = int(duration / beat) + 4
    duck = np.ones(n)
    for q in range(4, total_beats):
        s = q * beat
        add(kick, s, 0.55)
        i = int(s * SR)
        d = 1 - 0.55 * np.exp(-_t(beat) * 9)
        duck[i:i + len(d)] = np.minimum(duck[i:i + len(d)], d[: max(0, n - i)])
        add(hat, s + beat / 2, 0.12, 0.3)
        if q % 2 == 1:
            add(clap, s, 0.18, -0.1)
    left *= duck
    right *= duck
    return np.stack([left, right], axis=1)[: int(duration * SR)]


def compose_cinematic(duration: float, seed: int | None = None, hits: list[float] | None = None) -> np.ndarray:
    """Trailer-style bed: sub drone, slow pads, pulsing ostinato that builds, braams on the cuts."""
    rng = random.Random(seed)
    bpm = rng.choice([84, 90, 96, 100])
    beat = 60 / bpm
    key = rng.choice([45, 46, 47, 48, 50])  # A2..D3
    prog = rng.choice([[0, -4, 3, -2], [0, -4, -2, 0], [0, 3, -4, -2]])
    n = int(duration * SR) + SR
    L, R = np.zeros(n), np.zeros(n)
    intensity = np.clip(np.linspace(0.35, 1.0, n), 0, 1)

    def add(sig, start, gain=1.0, pan=0.0):
        i = int(start * SR)
        if i >= n or i < 0:
            return
        sig = sig[: n - i] * gain
        L[i:i + len(sig)] += sig * (1 - pan)
        R[i:i + len(sig)] += sig * (1 + pan)

    bar = beat * 4
    minor = {0: True, 3: False, -4: False, -2: False}
    for b in range(int(duration / bar) + 2):
        deg = prog[b % len(prog)]
        root = key + deg
        chord = _chord(root + 12, minor.get(deg, False))
        st = b * bar
        env_len = bar + 0.6
        tt = _t(env_len)
        env = np.minimum(1, tt / 0.8) * np.minimum(1, (env_len - tt) / 0.6)
        for m in chord:  # wide, dark pad
            add(_note(_midi_hz(m), env_len, 4) * env, st, 0.05, -0.5)
            add(_note(_midi_hz(m), env_len, 4, detune=0.005) * env, st, 0.05, 0.5)
        add(np.sin(2 * np.pi * _midi_hz(root - 12) * tt) * env, st, 0.22)  # sub
        for e in range(16):  # 16th ostinato, pluck
            m = chord[[0, 2, 1, 2][e % 4]] + (12 if e % 8 >= 6 else 0)
            add(_note(_midi_hz(m), beat * 0.3, 3, decay=22), st + e * beat / 4, 0.05, -0.3 if e % 2 else 0.3)

    t_k = _t(0.9)  # low "taiko" hits on downbeats in the second half
    taiko = np.sin(2 * np.pi * np.cumsum(90 * np.exp(-t_k * 9) + 42) / SR) * np.exp(-t_k * 5)
    for q in range(int(duration / beat)):
        if q * beat > duration * 0.35 and q % 2 == 0:
            add(taiko, q * beat, 0.35)
    for h in hits or []:  # braam on every cut
        tb = _t(2.2)
        braam = sum(_note(_midi_hz(key + o), 2.2, 9, detune=d) for o, d in ((-12, 0), (-12, 0.006), (-5, 0.003), (0, 0.004)))
        braam = _one_pole_lowpass(braam * np.exp(-tb * 1.6) * np.minimum(1, tb / 0.03), 1400)
        add(braam, h, 0.16)
    L *= intensity
    R *= intensity
    return np.stack([L, R], axis=1)[: int(duration * SR)]


def load_music_file(duration: float) -> np.ndarray | None:
    folder = ASSETS / "music"
    files = [p for p in folder.glob("*") if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg", ".flac"}]
    if not files:
        return None
    path = random.choice(files)
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
        capture_output=True, check=True,
    ).stdout
    audio = np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).astype(np.float64)
    need = int(duration * SR)
    if len(audio) < need:
        audio = np.tile(audio, (need // len(audio) + 1, 1))
    max_start = max(0, len(audio) - need)
    # start somewhere in the first third of the song (usually past the intro)
    start = random.randint(0, max_start // 3) if max_start else 0
    print(f"[audio] music: {path.name}")
    return audio[start:start + need]


# ------------------------------------------------------------------ mixing
def build_soundtrack(duration: float, cues: list[tuple[float, str]], cfg: dict, out: Path, seed=None,
                     style: str = "classic") -> Path:
    """cues: list of (time_seconds, sfx_name)."""
    a = cfg["audio"]
    n = int(duration * SR)
    music = load_music_file(duration)
    if music is None:
        print("[audio] no files in assets/music -> composing original track")
        if style == "cinematic":
            hits = sorted({round(t, 2) for t, name in cues if name == "impact" or name == "whoosh"})
            music = compose_cinematic(duration, seed, hits)
        else:
            music = compose_music(duration, seed)
    music = music[:n]
    if len(music) < n:
        music = np.pad(music, ((0, n - len(music)), (0, 0)))
    music = music / (np.max(np.abs(music)) + 1e-9) * 0.8 * a.get("music_volume", 0.55)

    sfx_track = np.zeros(n)
    if a.get("sfx", True):
        makers = {"whoosh": sfx_whoosh, "pop": sfx_pop, "tick": sfx_tick,
                  "impact": sfx_impact, "riser": sfx_riser, "alert": sfx_alert, "glitch": sfx_glitch,
                  "chime": sfx_chime,
                  "whoosh_out": lambda: sfx_whoosh(0.45, rising=False)}
        for when, name in cues:
            sig = makers[name]()
            i = max(0, int(when * SR))
            if i >= n:
                continue
            sig = sig[: n - i]
            sfx_track[i:i + len(sig)] += sig
        sfx_track *= a.get("sfx_volume", 0.9) * 0.6

    mix = music + sfx_track[:, None]
    fade_in = np.minimum(1, np.arange(n) / (0.15 * SR))
    fade_out = np.minimum(1, (n - np.arange(n)) / (1.2 * SR))
    mix *= (fade_in * fade_out)[:, None]
    mix = np.tanh(mix * 1.1)
    mix = mix / (np.max(np.abs(mix)) + 1e-9) * 0.89  # ~ -1 dBFS

    pcm = (mix * 32767).astype("<i2")
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return out
