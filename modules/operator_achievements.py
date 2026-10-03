"""Zero Command System - Operator Achievements Hub.

Read-only display of the curated achievement catalog defined in
zeroGravity-rnd/operator_core/achievements/data/definitions.json - the
actual checking/awarding logic lives entirely over there
(operator_core/achievements/service.py, hooked into the tail of
learning.engine.stats.update_operator_competencies()). This page only ever
reads; nothing here awards or writes anything.

Dependency-light like operator_analytics.py/operator.py: no cross-repo
Python imports, just JSON reads (definitions.json, competencies.json, the
event ledger's index for "already unlocked", and a course's own
progress.json for a rough in-progress/not-started read). The level-curve
math (BASE_XP=100, CURVE_EXPONENT=1.5) is a tiny pure function duplicated
here on purpose - same tradeoff operator_tasks.py/operator.py already made
for the same reason: a few lines of arithmetic beats a cross-repo import
for a read-only display.

"Unlocked" is read straight from operator_events.jsonl's own index
(idempotency_keys "achievement:<id>") rather than re-deriving it from
current xp/level - that index IS the ledger's source of truth for whether
an achievement has actually fired, and re-deriving it here would drift the
moment the achievement catalog's thresholds change after something already
unlocked under an older threshold.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, render_template

operator_achievements_bp = Blueprint(
    "operator_achievements", __name__, url_prefix="/operator/achievements"
)

BASE_XP = 100
CURVE_EXPONENT = 1.5

TRACK_LABELS = {"python": "Python", "premiere_pro": "Premiere Pro", "cad": "CAD"}
TRACK_ORDER = ["python", "premiere_pro", "cad"]


def _rnd_root() -> Path:
    env = os.getenv("ZERO_GRAVITY_RND_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    configured = current_app.config.get("ZERO_GRAVITY_RND_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(current_app.root_path).resolve().parent / "zeroGravity-rnd"


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _xp_cost_for_level(level: int) -> int:
    return round(BASE_XP * ((level + 1) ** CURVE_EXPONENT))


def _cumulative_xp_for_level(level: int) -> int:
    return sum(_xp_cost_for_level(current) for current in range(level))


def _calculate_level(xp: int) -> int:
    level = 0
    while xp >= _cumulative_xp_for_level(level + 1):
        level += 1
    return level


def _unlocked_ids(root: Path) -> set[str]:
    index = _load_json(root / "operator_core" / "events" / "event_index.json", {})
    keys = index.get("idempotency_keys", {}) if isinstance(index, dict) else {}
    return {
        key.split(":", 1)[1]
        for key in keys
        if isinstance(key, str) and key.startswith("achievement:")
    }


def _competency_name(competency_id: str, registry: dict[str, Any]) -> str:
    record = registry.get(competency_id, {})
    return str(record.get("name", competency_id)) if isinstance(record, dict) else competency_id


def _course_state(root: Path, track_path: str) -> dict[str, Any]:
    if not track_path:
        return {"exists": False, "status": "Not started"}
    progress = _load_json(root / "learning" / "tracks" / track_path / "progress.json", None)
    if not isinstance(progress, dict):
        return {"exists": False, "status": "Not started"}
    return {"exists": True, "status": str(progress.get("status", "In Progress"))}


def get_achievements_dashboard_data() -> dict[str, Any]:
    root = _rnd_root()
    definitions = _load_json(
        root / "operator_core" / "achievements" / "data" / "definitions.json",
        {"achievements": [], "bonus_split": {"targets": []}},
    )
    competencies = _load_json(
        root / "operator_core" / "capabilities" / "competencies.json", {"competencies": {}}
    ).get("competencies", {})
    unlocked = _unlocked_ids(root)

    bonus_split = [
        {
            "competency_id": str(target.get("competency_id", "")),
            "name": _competency_name(str(target.get("competency_id", "")), competencies),
            "percentage": round(float(target.get("weight", 0)) * 100),
        }
        for target in definitions.get("bonus_split", {}).get("targets", [])
    ]

    by_track: dict[str, dict[str, Any]] = {}
    for achievement in definitions.get("achievements", []):
        track_key = str(achievement.get("track", ""))
        track = by_track.setdefault(track_key, {"milestones": [], "courses": [], "competency_id": None})

        achievement_id = str(achievement.get("id", ""))
        is_unlocked = achievement_id in unlocked
        confirmed = bool(achievement.get("confirmed", True))
        kind = achievement.get("kind")

        if kind == "milestone":
            competency_id = str(achievement.get("competency_id", ""))
            track["competency_id"] = track["competency_id"] or competency_id
            xp = int(competencies.get(competency_id, {}).get("xp", 0))
            threshold = int(achievement.get("level_threshold", 0))
            need = _cumulative_xp_for_level(threshold)
            track["milestones"].append({
                "id": achievement_id,
                "level_threshold": threshold,
                "title": achievement.get("title", ""),
                "description": achievement.get("description", ""),
                "base_xp": int(achievement.get("base_xp", 0)),
                "confirmed": confirmed,
                "unlocked": is_unlocked,
                "xp_needed": need,
                "xp_needed_display": f"{need:,}",
                "current_xp": xp,
                "current_xp_display": f"{xp:,}",
                "progress_percentage": min(100.0, round(xp / need * 100, 1)) if need else 100.0,
            })
        elif kind == "course_completion":
            course = _course_state(root, str(achievement.get("track_path", "")))
            track["courses"].append({
                "id": achievement_id,
                "title": achievement.get("title", ""),
                "description": achievement.get("description", ""),
                "base_xp": int(achievement.get("base_xp", 0)),
                "confirmed": confirmed,
                "unlocked": is_unlocked,
                "course_exists": course["exists"],
                "course_status": course["status"],
            })

    tracks_out = []
    for track_key in TRACK_ORDER:
        track = by_track.get(track_key)
        if not track:
            continue

        milestones = sorted(track["milestones"], key=lambda m: m["level_threshold"])
        seen_current = False
        for milestone in milestones:
            if milestone["unlocked"]:
                milestone["state"] = "cleared"
            elif not seen_current:
                milestone["state"] = "current"
                seen_current = True
            else:
                milestone["state"] = "locked"

        competency_id = track["competency_id"] or ""
        current_xp = int(competencies.get(competency_id, {}).get("xp", 0))
        current_level = _calculate_level(current_xp)

        tracks_out.append({
            "key": track_key,
            "label": TRACK_LABELS.get(track_key, track_key.replace("_", " ").title()),
            "competency_id": competency_id,
            "current_level": current_level,
            "current_xp": current_xp,
            "current_xp_display": f"{current_xp:,}",
            "milestones": milestones,
            "courses": track["courses"],
            "has_proposed": (
                any(not m["confirmed"] for m in milestones)
                or any(not c["confirmed"] for c in track["courses"])
            ),
        })

    return {"tracks": tracks_out, "bonus_split": bonus_split}


@operator_achievements_bp.get("/")
def dashboard():
    try:
        data = get_achievements_dashboard_data()
        error = None
    except Exception as exc:  # a display hiccup here should never take the hub down
        data = None
        error = str(exc)

    return render_template(
        "workspaces/operator/achievements.html",
        data=data,
        achievements_error=error,
    )
