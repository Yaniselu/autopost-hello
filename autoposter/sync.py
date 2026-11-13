"""Saves data/*.json back to the repo without ever losing anything.

Several writers touch data/ at the same time (posting runs, comment runs, the panel's scheduler),
so a plain `git pull --rebase` can stop on a conflict and the history of a run would be lost
(and a slot could be posted twice). Instead: keep our versions in memory, move to the latest
remote commit, merge each file with a JSON-aware merge, commit, push; retry on races.

usage: python -m autoposter.sync
"""
import json
import subprocess
import sys
import time
from pathlib import Path

from .config import DATA


def _git(*args, check=True):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=check)


def _key(e):
    return json.dumps(e, sort_keys=True, ensure_ascii=False)


def _union_list(theirs, ours):
    seen, out = set(), []
    for x in list(theirs) + list(ours):
        k = _key(x)
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def merge(name: str, theirs, ours):
    if theirs is None:
        return ours
    if ours is None:
        return theirs
    if name == "history.json" and isinstance(theirs, list) and isinstance(ours, list):
        ident = lambda e: (e.get("time"), e.get("type"), e.get("mode"), e.get("slot"), e.get("run_url"))  # noqa: E731
        by = {ident(e): e for e in theirs}
        for e in ours:  # ours wins for the same run (it is newer)
            by[ident(e)] = e
        return sorted(by.values(), key=lambda e: str(e.get("time", "")))
    if name == "state.json" and isinstance(theirs, dict) and isinstance(ours, dict):
        done = list(dict.fromkeys(list(theirs.get("done", [])) + list(ours.get("done", []))))[-400:]
        att = dict(theirs.get("attempts", {}))
        for k, v in (ours.get("attempts") or {}).items():
            att[k] = max(int(v or 0), int(att.get(k, 0) or 0))
        att = {k: v for k, v in att.items() if k not in done}
        return {**theirs, **ours, "done": done, "attempts": att}
    if isinstance(theirs, dict) and isinstance(ours, dict):
        out = dict(theirs)
        for k, v in ours.items():
            out[k] = merge("", theirs.get(k), v) if k in theirs else v
        return out
    if isinstance(theirs, list) and isinstance(ours, list):
        return _union_list(theirs, ours)
    return ours


def save(message="Update history", tries=5):
    ours = {}
    rel = DATA.resolve().relative_to(Path(_git("rev-parse", "--show-toplevel").stdout.strip()).resolve())
    for p in DATA.glob("*.json"):
        try:
            mine = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        base = _git("show", f"HEAD:{rel.as_posix()}/{p.name}", check=False)
        try:
            before = json.loads(base.stdout) if base.returncode == 0 else None
        except ValueError:
            before = None
        if mine != before:  # only what this run changed
            ours[p.name] = mine
    for attempt in range(tries):
        _git("fetch", "-q", "origin", "main")
        _git("reset", "-q", "--hard", "origin/main")
        changed = False
        for name, mine in ours.items():
            p = DATA / name
            try:
                theirs = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
            except ValueError:
                theirs = None
            merged = merge(name, theirs, mine)
            if merged != theirs:
                p.write_text(json.dumps(merged, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
                changed = True
        if not changed:
            print("[sync] nothing to save")
            return True
        _git("add", "data/")
        _git("commit", "-q", "-m", message)
        r = _git("push", "-q", "origin", "HEAD:main", check=False)
        if r.returncode == 0:
            print(f"[sync] saved (attempt {attempt + 1})")
            return True
        print(f"[sync] push raced, retrying: {r.stderr.strip()[:200]}")
        time.sleep(3 + attempt * 3)
    print("[sync] could not save data after retries")
    return False


if __name__ == "__main__":
    sys.exit(0 if save(*(sys.argv[1:2] or [])) else 1)
