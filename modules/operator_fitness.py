"""Zero Command System — Operator Fitness Hub.

Daily bodyweight/cardio habit logging. Mirrors the read-JSON-then-render
pattern in modules/operator.py, and the subprocess-into-the-engine pattern
in modules/operator_learning.py's ``_run`` helper — this blueprint has no
Python import dependency on the zeroGravity-rnd repo, it only reads its
JSON output and shells out to its CLI, exactly like Learning does.
"""
from __future__ import annotations

import json
import os
import subprocess
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


def _run_tracker(args: list[str]) -> str:
    root = _rnd_root()
    result = subprocess.run(
        [sys.executable, "-m", "fitness.engine.tracker", *args],
        input="",
        text=True,
        capture_output=True,
        cwd=str(root),
        timeout=60,
        check=False,
    )
    return (result.stdout + "\n" + result.stderr).strip()


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
    habit_args: list[str] = []
    for field in HABIT_FIELDS:
        value = request.form.get(field["key"], "").strip()
        if value:
            flag = "--" + field["key"].replace("_", "-")
            habit_args += [flag, value]

    if not habit_args:
        output = "Enter at least one habit quantity before logging."
    else:
        log_date = request.form.get("date", "").strip()
        args = habit_args + (["--date", log_date] if log_date else [])
        try:
            output = _run_tracker(args)
        except Exception as error:
            output = f"FITNESS ENGINE ERROR\n{error}"

    return redirect(url_for("operator_fitness.dashboard", output=output[-4000:]))
