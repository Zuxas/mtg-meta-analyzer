"""Save MTGO's local match files before MTGO overwrites them.

mtgo.log only holds the CURRENT session (exact 75s + board frames) and is
replaced when MTGO next launches, so it is saved under its session id.
Game logs, match history and deck files are copied when new or changed.
Chat files (Match_GameChat_*, PrivateChatChannel_*) are never read.

  python -m scrapers.mtgo_snapshot          # copy into data/raw/mtgo/<today>/
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import date
from pathlib import Path

DEFAULT_DEST = Path(__file__).resolve().parents[1] / "data" / "raw" / "mtgo"
_SESSION_RE = re.compile(r"SessionStarted\) ID: ([0-9a-f]{8})")


def _install_id(path: Path) -> str:
    for part in path.parts:
        if part.startswith("mtgo..tion_"):
            return part.rsplit("_", 1)[-1][:8]
    return "unknown"


def _session_id(log: Path) -> str:
    with open(log, encoding="utf-8", errors="replace") as fh:
        for _ in range(50):
            line = fh.readline()
            if not line:
                break
            if m := _SESSION_RE.search(line):
                return m.group(1)
    return "nosession"


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sources(root: Path):
    """(source path, name to save it under, replace_in_place)."""
    out = []
    for app in root.glob("Data/*/*/mtgo..tion_*/Data/AppFiles/*"):
        inst = _install_id(app)
        for f in app.glob("Match_GameLog_*.dat"):
            out.append((f, f.name, False))
        hist = app / "mtgo_game_history"
        if hist.exists():
            out.append((hist, f"{inst}__mtgo_game_history", False))
        for f in app.glob("*.xml"):
            out.append((f, f"{inst}__{f.name}", False))
    for log in root.glob("*/*/mtgo..tion_*/Logs/mtgo.log"):
        name = f"mtgo_{_install_id(log)}_{_session_id(log)}.log"
        out.append((log, name, True))
    return out


def _known(dest_root: Path) -> tuple[dict[str, set], dict[str, Path]]:
    """sha256s already saved per name, and where each session log lives."""
    hashes: dict[str, set] = {}
    logs: dict[str, Path] = {}
    for man in dest_root.glob("*/MANIFEST.json"):
        try:
            for m in json.loads(man.read_text(encoding="utf-8")):
                hashes.setdefault(m["file"], set()).add(m["sha256"])
        except (ValueError, KeyError, OSError):
            continue
    for f in dest_root.glob("*/mtgo_*.log"):
        logs[f.name] = f
    return hashes, logs


def snapshot(root: str | os.PathLike | None = None,
             dest_root: str | os.PathLike = DEFAULT_DEST,
             today: date | None = None) -> dict:
    root = Path(root or os.path.expandvars(r"%LOCALAPPDATA%\Apps\2.0"))
    dest_root = Path(dest_root)
    if not root.exists():
        return {"copied": 0, "dest": None}
    day = dest_root / (today or date.today()).isoformat()
    hashes, saved_logs = _known(dest_root)
    manifest: dict[Path, list] = {}
    copied = 0
    for src, name, in_place in _sources(root):
        try:
            digest = _sha(src)
        except OSError:
            continue  # MTGO holds the file open mid-write; next run gets it
        if digest in hashes.get(name, set()):
            continue
        target_dir = saved_logs[name].parent if in_place and name in saved_logs else day
        target_dir.mkdir(parents=True, exist_ok=True)
        tmp = target_dir / (name + ".tmp")
        shutil.copy2(src, tmp)
        os.replace(tmp, target_dir / name)
        entries = manifest.setdefault(target_dir, _read_manifest(target_dir))
        entries[:] = [e for e in entries if e["file"] != name]
        entries.append({"file": name, "src": str(src), "bytes": src.stat().st_size,
                        "sha256": digest})
        hashes.setdefault(name, set()).add(digest)
        copied += 1
    for d, entries in manifest.items():
        tmp = d / "MANIFEST.json.tmp"
        tmp.write_text(json.dumps(entries, indent=1), encoding="utf-8")
        os.replace(tmp, d / "MANIFEST.json")
    return {"copied": copied, "dest": str(day) if copied else None}


def _read_manifest(d: Path) -> list:
    f = d / "MANIFEST.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            return []
    return []


if __name__ == "__main__":
    r = snapshot()
    print(f"MTGO snapshot: {r['copied']} file(s) saved" + (f" -> {r['dest']}" if r["dest"] else ""))
