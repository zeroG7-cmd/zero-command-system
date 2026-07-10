"""Zero Command System - Operator workspace."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, render_template

operator_bp = Blueprint("operator", __name__, url_prefix="/operator")


def _rnd_root() -> Path:
    env_path = os.getenv("ZERO_GRAVITY_RND_ROOT")
    if env_path:
        return Path(env_path).expanduser().resolve()

    configured = current_app.config.get("ZERO_GRAVITY_RND_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()

    return Path(current_app.root_path).resolve().parent / "zeroGravity-rnd"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Operator data file not found: {path}")

    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid JSON in {path}: line {error.lineno}, column {error.colno}"
        ) from error

    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {path}")

    return data


def _main_stats(stats: dict[str, Any]) -> list[dict[str, Any]]:
    preferred = ["CON", "INT", "STR", "DEX", "DIS"]
    names = [name for name in preferred if name in stats]
    names.extend(name for name in stats if name not in names)

    result = []
    for name in names:
        node = stats.get(name, {})
        if not isinstance(node, dict):
            continue
        children = node.get("children", {})
        result.append({
            "name": name,
            "average_level": float(node.get("average_level", 0.0)),
            "child_count": len(children) if isinstance(children, dict) else 0,
        })
    return result


def _int_domains(stats: dict[str, Any]) -> list[dict[str, Any]]:
    int_node = stats.get("INT", {})
    children = int_node.get("children", {}) if isinstance(int_node, dict) else {}
    if not isinstance(children, dict):
        return []

    result = []
    for name, node in children.items():
        if not isinstance(node, dict):
            continue
        child_nodes = node.get("children", {})
        result.append({
            "name": name,
            "average_level": float(node.get("average_level", 0.0)),
            "child_count": len(child_nodes) if isinstance(child_nodes, dict) else 0,
        })
    return result


def get_operator_dashboard_data() -> dict[str, Any]:
    rnd_root = _rnd_root()
    stats_path = rnd_root / "learning" / "operator" / "stats.json"
    competencies_path = rnd_root / "learning" / "config" / "competencies.json"

    stats_data = _load_json(stats_path)
    competencies_data = _load_json(competencies_path)

    stats = stats_data.get("stats", {})
    competencies = competencies_data.get("competencies", {})

    if not isinstance(stats, dict):
        raise ValueError("stats.json must contain a 'stats' object")
    if not isinstance(competencies, dict):
        raise ValueError("competencies.json must contain a 'competencies' object")

    total_xp = int(stats_data.get("total_xp", 0))
    level = int(stats_data.get("level", 0))
    next_level_xp = max(100, level * 100)
    level_start = 0 if level == 0 else (level - 1) * 100
    level_span = max(1, next_level_xp - level_start)
    progress = min(100.0, round(((total_xp - level_start) / level_span) * 100, 1))

    shared_count = sum(
        1 for item in competencies.values()
        if isinstance(item, dict) and bool(item.get("shared", False))
    )

    return {
        "operator_level": level,
        "total_xp": total_xp,
        "next_level_xp": next_level_xp,
        "level_progress": max(0.0, progress),
        "competency_count": int(stats_data.get("competency_count", len(competencies))),
        "shared_competency_count": shared_count,
        "main_stats": _main_stats(stats),
        "int_domains": _int_domains(stats),
        "tree": stats,
        "data_source": str(stats_path),
        "schema_version": stats_data.get("schema_version", "unknown"),
    }


@operator_bp.route("/")
def dashboard():
    try:
        return render_template(
            "workspaces/operator/dashboard.html",
            dashboard=get_operator_dashboard_data(),
            operator_error=None,
        )
    except (FileNotFoundError, ValueError, OSError) as error:
        return render_template(
            "workspaces/operator/dashboard.html",
            dashboard=None,
            operator_error=str(error),
        ), 500
