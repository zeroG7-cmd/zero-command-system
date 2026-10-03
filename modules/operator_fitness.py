"""Zero Command System — Operator Fitness Hub.

Daily bodyweight/cardio habit logging. Mirrors the read-JSON-then-render
pattern in modules/operator.py.

Logging used to shell out to `fitness.engine.tracker`/`gym_log` via
``subprocess.run([sys.executable, "-m", ...])`` - the same pattern
modules/operator_learning.py's ``_run`` helper still uses. That breaks once
the app is bundled with PyInstaller: `sys.executable` then points at the
frozen `zero-command-backend.exe` itself, not a real Python interpreter, so
`-m fitness.engine.tracker` is meaningless to it - the subprocess hangs
until the timeout instead of running anything (this is exactly what the
desktop app's "FITNESS ENGINE ERROR ... timed out after 60 seconds" was).
`fitness.engine.tracker.log_day`/`gym_log.log_gym_day` were already clean,
importable functions returning a plain summary dict (not just CLI wrappers
around print statements), so this now imports and calls them directly in
the same request - the same direct-import pattern modules/tasks.py,
modules/operator_execution.py and modules/operator_journal.py already use,
and immune to the frozen-exe problem since there's no subprocess at all.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, redirect, render_template, request, url_for

operator_fitness_bp = Blueprint("operator_fitness", __name__, url_prefix="/operator/fitness")

# Kept as a local copy of fitness/engine/config.py's HABITS (in zeroGravity-rnd)
# rather than imported across repos — same choice operator_learning.py makes
# for DEFAULT_XP_RULES. Keep the two in sync by hand if targets change.
HABIT_FIELDS: list[dict[str, Any]] = [
    {
        "key": "pushups", "label": "Push-ups", "unit": "reps", "target": 60,
        "tree_path": ["STR", "Muscular Strength", "Pushing Strength", "Push-ups"],
    },
    {
        "key": "pullups", "label": "Pull-ups", "unit": "reps", "target": 60,
        "tree_path": ["STR", "Muscular Strength", "Pulling Strength", "Pull-ups"],
    },
    {
        "key": "situps", "label": "Sit-ups", "unit": "reps", "target": 60,
        "tree_path": ["STR", "Muscular Strength", "Core Strength", "Sit-ups"],
    },
    {
        "key": "squats", "label": "Squats", "unit": "reps", "target": 60,
        "tree_path": ["STR", "Muscular Strength", "Leg Strength", "Squats"],
    },
    {
        "key": "run_minutes", "label": "Jog", "unit": "minutes", "target": 30,
        "tree_path": ["CON", "Endurance", "Aerobic Capacity", "Running"],
    },
    {
        "key": "stretch_minutes", "label": "Stretch / mobility", "unit": "minutes", "target": 10,
        "tree_path": ["CON", "Health Management", "Mobility", "Stretching"],
        # Stretching splits its XP with a DEX leaf too - see fitness/README.md
        # in zeroGravity-rnd for why. Shown as a second line on this card.
        "secondary_label": "Dynamic Flexibility (DEX)",
        "secondary_tree_path": ["DEX", "Agility", "Mobility", "Dynamic Flexibility"],
    },
]

DAILY_PRACTICE_TREE_PATH = ["DISC", "Consistency", "Routine Adherence", "Daily Practice"]

# The five Muscular Strength categories, for the digital-twin hotspot labels
# pinned onto static/models/zero.glb in fitness.html. "position"/"normal" are
# <model-viewer> hotspot coordinates in the model's own local space - derived
# from zero.glb's actual vertex bounding box (x: -0.40..0.40, y: -0.95..0.95,
# z: -0.32..0.32) and standard body proportions, NOT verified against a
# render, since nothing here can preview the live 3D scene. Treat these as a
# first pass - nudge the numbers once you see it in the browser if a pin
# lands in the wrong spot.
MUSCULAR_STRENGTH_CATEGORIES: list[dict[str, str]] = [
    {"name": "Pushing Strength", "hotspot": "pushing-strength", "position": "0 0.42 0.28", "normal": "0 0 1"},
    {"name": "Pulling Strength", "hotspot": "pulling-strength", "position": "0 0.42 -0.28", "normal": "0 0 -1"},
    {"name": "Grip Strength", "hotspot": "grip-strength", "position": "0.35 -0.2 0.05", "normal": "1 0 0"},
    {"name": "Leg Strength", "hotspot": "leg-strength", "position": "0.15 -0.42 0.25", "normal": "0 0 1"},
    {"name": "Core Strength", "hotspot": "core-strength", "position": "0 0.2 0.28", "normal": "0 0 1"},
]


def _rnd_root() -> Path:
    env = os.getenv("ZERO_GRAVITY_RND_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    configured = current_app.config.get("ZERO_GRAVITY_RND_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(current_app.root_path).resolve().parent / "zeroGravity-rnd"


def _load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _navigate(stats: dict[str, Any], tree_path: list[str]) -> dict[str, Any]:
    node: dict[str, Any] = stats.get(tree_path[0], {}) if isinstance(stats, dict) else {}
    for name in tree_path[1:]:
        node = node.get("children", {}).get(name, {}) if isinstance(node, dict) else {}
    return node if isinstance(node, dict) else {}


def get_fitness_dashboard_data() -> dict[str, Any]:
    root = _rnd_root()
    stats_path = root / "operator_core" / "hubs" / "learning" / "stats" / "learning_stats.json"
    stats_doc = _load_json(stats_path)
    if stats_doc is None:
        raise FileNotFoundError(f"Required stats file not found: {stats_path}")
    stats = stats_doc.get("stats", {})

    habits = []
    for field in HABIT_FIELDS:
        leaf = _navigate(stats, field["tree_path"])
        entry = {
            **field,
            "xp": leaf.get("xp", 0),
            "level": leaf.get("level", 0),
            "level_progress": leaf.get("level_progress", 0.0),
        }
        secondary_path = field.get("secondary_tree_path")
        if secondary_path:
            secondary_leaf = _navigate(stats, secondary_path)
            entry["secondary"] = {
                "label": field.get("secondary_label", ""),
                "xp": secondary_leaf.get("xp", 0),
                "level": secondary_leaf.get("level", 0),
                "level_progress": secondary_leaf.get("level_progress", 0.0),
            }
        habits.append(entry)

    daily_practice = _navigate(stats, DAILY_PRACTICE_TREE_PATH)

    # Per-category breakdown for the digital-twin hotspots - each category's
    # average_level, computed from its own children by fitness/engine/stats.py.
    muscular_strength_categories = []
    for cat in MUSCULAR_STRENGTH_CATEGORIES:
        node = _navigate(stats, ["STR", "Muscular Strength", cat["name"]])
        muscular_strength_categories.append(
            {
                "name": cat["name"],
                "hotspot": cat["hotspot"],
                "position": cat["position"],
                "normal": cat["normal"],
                "average_level": float(node.get("average_level", 0.0)),
            }
        )

    history = _load_json(root / "operator_core" / "hubs" / "fitness" / "history" / "fitness_history.json", [])
    if not isinstance(history, list):
        history = []
    progress = _load_json(root / "operator_core" / "hubs" / "fitness" / "progress" / "fitness_progress.json", {})
    routine = _load_json(root / "fitness" / "routines" / "weekly_routine.json", {})
    today_name = date.today().strftime("%A")
    todays_routine_day = next(
        (d for d in routine.get("days", []) if d.get("day") == today_name), None
    )

    return {
        "habits": habits,
        "str_average_level": float(stats.get("STR", {}).get("average_level", 0.0)),
        "con_average_level": float(stats.get("CON", {}).get("average_level", 0.0)),
        "dex_average_level": float(stats.get("DEX", {}).get("average_level", 0.0)),
        "disc_average_level": float(stats.get("DISC", {}).get("average_level", 0.0)),
        "muscular_strength_categories": muscular_strength_categories,
        "daily_practice": daily_practice,
        "history": list(reversed(history[-7:])),
        "current_streak": progress.get("current_streak_days", 0),
        "longest_streak": progress.get("longest_streak_days", 0),
        "routine": routine,
        "todays_routine_day": todays_routine_day,
        "today_name": today_name,
        "rnd_root": str(root),
    }


def _fitness_engine():
    """Lazily import fitness.engine.tracker/gym_log from zeroGravity-rnd.

    Lazy + idempotent path insertion (like operator_execution.py's
    _engine_modules helper) rather than a module-level import, so this file
    still loads cleanly even if ZERO_GRAVITY_RND_ROOT/the sibling repo isn't
    set up yet - the error then surfaces from inside the route's own
    try/except as a normal "FITNESS ENGINE ERROR" instead of crashing the
    whole app at import time.
    """
    root = _rnd_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from fitness.engine.tracker import log_day as run_log_day
    from fitness.engine.gym_log import log_gym_day as run_log_gym_day
    return run_log_day, run_log_gym_day


def _format_log_summary(summary: dict[str, Any]) -> str:
    """Mirror fitness.engine.tracker._print_summary's exact text, since that
    function prints to stdout instead of returning a string - now that we
    call log_day() in-process there's no subprocess stdout left to capture.
    """
    lines = [f"Fitness log for {summary['date']}"]
    if not summary["entries"] and not summary["skipped_already_logged"]:
        lines.append("  Nothing logged.")
    for entry in summary["entries"]:
        flag = "OK" if entry["met_target"] else "under target"
        lines.append(
            f"  {entry['label']:<18} {entry['quantity']:g} {entry['unit']:<7} "
            f"(target {entry['target']}, {flag}) -> +{entry['xp_awarded']} XP"
        )
    for label in summary["skipped_already_logged"]:
        lines.append(f"  {label}: already logged today, skipped (v1 logs are final per day).")
    if summary["full_day_bonus_xp"]:
        lines.append(f"  Full-day consistency bonus: +{summary['full_day_bonus_xp']} XP to Discipline")
    if summary["operator_total_xp"] is not None:
        lines.append(f"  Operator total XP: {summary['operator_total_xp']} (level {summary['operator_level']})")
    return "\n".join(lines)


def _format_gym_summary(summary: dict[str, Any]) -> str:
    """Mirror fitness.engine.gym_log._print_summary's exact text - same
    reasoning as _format_log_summary above.
    """
    lines = [f"Gym day log for {summary['date']} ({summary['day']})"]
    if not summary["logged"]:
        if summary["reason"] == "rest_day":
            lines.append(f"  {summary['day']} is a rest day - nothing to log.")
        elif summary["reason"] == "already_logged":
            lines.append(f"  Already logged for {summary['date']} (one log per calendar date).")
        return "\n".join(lines)
    if summary["capabilities_trained"]:
        lines.append(f"  {summary['focus']} -> +{summary['xp_awarded']} XP split across:")
        for competency_id in summary["capabilities_trained"]:
            lines.append(f"    - {competency_id}")
    else:
        lines.append(f"  {summary['focus']} -> +{summary['xp_awarded']} XP to Discipline (showed up)")
    if summary.get("operator_total_xp") is not None:
        lines.append(f"  Operator total XP: {summary['operator_total_xp']} (level {summary['operator_level']})")
    return "\n".join(lines)


@operator_fitness_bp.route("/")
def dashboard():
    try:
        return render_template(
            "workspaces/operator/fitness.html",
            fitness=get_fitness_dashboard_data(),
            fitness_error=None,
            action_output=request.args.get("output"),
        )
    except Exception as error:
        return render_template(
            "workspaces/operator/fitness.html",
            fitness=None,
            fitness_error=str(error),
            action_output=None,
        ), 500


@operator_fitness_bp.post("/log")
def log_day():
    quantities: dict[str, float] = {}
    for field in HABIT_FIELDS:
        value = request.form.get(field["key"], "").strip()
        if value:
            quantities[field["key"]] = float(value)

    if not quantities:
        output = "Enter at least one habit quantity before logging."
    else:
        log_date = request.form.get("date", "").strip() or None
        try:
            run_log_day, _run_log_gym_day = _fitness_engine()
            summary = run_log_day(quantities, log_date=log_date)
            output = _format_log_summary(summary)
        except Exception as error:
            output = f"FITNESS ENGINE ERROR\n{error}"

    return redirect(url_for("operator_fitness.dashboard", output=output[-4000:]))


@operator_fitness_bp.post("/log-gym-day")
def log_gym_day():
    """Mark today's (or a chosen) gym-routine day done - distributes XP into
    that day's specific gym-lift capabilities via fitness.engine.gym_log.
    """
    day = request.form.get("day", "").strip() or None
    try:
        _run_log_day, run_log_gym_day = _fitness_engine()
        summary = run_log_gym_day(day_name=day)
        output = _format_gym_summary(summary)
    except Exception as error:
        output = f"FITNESS ENGINE ERROR\n{error}"

    return redirect(url_for("operator_fitness.dashboard", output=output[-4000:]))
