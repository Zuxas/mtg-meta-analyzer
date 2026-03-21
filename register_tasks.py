"""
register_tasks.py — Register all Windows Task Scheduler tasks.

Must be run as Administrator. Called automatically by the first-run setup
wizard via UAC elevation. Can also be run manually:

    python register_tasks.py

In frozen .exe context, the main exe is re-launched with --register-tasks:
    MTGMetaAnalyzer.exe --register-tasks

Writes setup_complete flag to config.ini on success so the wizard never
asks again.
"""

import sys
import os
import subprocess
import configparser
from datetime import datetime

_ROOT = os.path.dirname(os.path.abspath(__file__))

TASKS = [
    {
        "name":     "MTG-Meta-Analyzer-Background-6AM",
        "bat":      "background_fill.bat",
        "schedule": "DAILY",
        "time":     "06:00",
        "desc":     "6 AM daily — Standard, Pioneer, Modern (MTGTop8 + MTGDecks)",
    },
    {
        "name":     "MTG-Meta-Analyzer-Daily",
        "bat":      "run_daily.bat",
        "schedule": "DAILY",
        "time":     "17:00",
        "desc":     "5 PM daily — Standard latest events + archive maintenance",
    },
    {
        "name":     "MTG-Meta-Analyzer-Scryfall-Weekly",
        "bat":      "run_scryfall_weekly.bat",
        "schedule": "WEEKLY",
        "day":      "SUN",
        "time":     "00:00",
        "desc":     "Sunday midnight — Scryfall card database refresh",
    },
]


def _register_one(task: dict) -> tuple[bool, str]:
    """Register a single task. Returns (success, error_message)."""
    bat = os.path.join(_ROOT, task["bat"])
    if not os.path.exists(bat):
        return False, f"Script not found: {bat}"

    # Remove old version first (ignore errors)
    subprocess.run(
        ["schtasks", "/delete", "/tn", task["name"], "/f"],
        capture_output=True,
    )

    cmd = [
        "schtasks", "/create",
        "/tn", task["name"],
        "/tr", f'cmd /c "{bat}"',
        "/sc", task["schedule"],
        "/st", task["time"],
        "/rl", "HIGHEST",
        "/f",
    ]
    if task.get("day"):
        cmd += ["/d", task["day"]]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        return True, ""
    return False, (result.stderr or result.stdout).strip()


def mark_setup_complete():
    """Write tasks_registered = true to config.ini."""
    cfg_path = os.path.join(_ROOT, "config.ini")
    cfg = configparser.ConfigParser()
    cfg.read(cfg_path)
    if "setup" not in cfg:
        cfg["setup"] = {}
    cfg["setup"]["tasks_registered"] = "true"
    cfg["setup"]["tasks_registered_at"] = datetime.now().isoformat(timespec="seconds")
    with open(cfg_path, "w") as f:
        cfg.write(f)


def main():
    print()
    print("=" * 54)
    print("  MTG Meta Analyzer — Task Registration")
    print("=" * 54)

    ok_count = 0
    for task in TASKS:
        ok, err = _register_one(task)
        tag = "OK  " if ok else "FAIL"
        print(f"  [{tag}] {task['desc']}")
        if not ok and err:
            print(f"         Error: {err}")
        if ok:
            ok_count += 1

    print()
    if ok_count == len(TASKS):
        mark_setup_complete()
        print("  All tasks registered. Setup complete.")
        print("=" * 54)
        sys.exit(0)
    else:
        print(f"  Warning: {ok_count}/{len(TASKS)} tasks registered.")
        if ok_count > 0:
            mark_setup_complete()
        print("=" * 54)
        sys.exit(1 if ok_count == 0 else 0)


if __name__ == "__main__":
    main()
