"""Zero Command adapter for the zeroGravity R&D engine."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, render_template

from config import ZERO_GRAVITY_RND_ROOT

rnd_bp = Blueprint("research_development", __name__, url_prefix="/research-development")


def _offline_workspace(error: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": None,
        "integration_error": error,
        "research": {
            "database_online": False,
            "database_path": str(ZERO_GRAVITY_RND_ROOT / "lab" / "database" / "zerogravity_rnd.db"),
            "tests": {"total": 0, "passed": 0, "failed": 0, "pending": 0, "success_rate": 0, "recent": []},
            "experiments": [],
            "experiment_summary": {"total": 0, "active": 0},
            "simulation": {"runs": 0, "completed_runs": 0, "telemetry_samples": 0},
        },
        "repository": {
            "repo_online": ZERO_GRAVITY_RND_ROOT.exists(),
            "healthy": False,
            "health_score": 0,
            "repo_path": str(ZERO_GRAVITY_RND_ROOT),
            "hardware_files": 0,
            "simulation_files": 0,
            "archived_experiments": 0,
            "cad_assets": 0,
            "urdf_assets": 0,
            "latest_artifact": None,
        },
        "operator": {"online": False, "level": 0, "xp": 0, "competencies": 0},
        "journal": {"entries": 0, "latest": None},
        "projects": [],
        "shadow": {
            "database_online": False,
            "vehicle": {"name": "Shadow MK1", "type": "Companion Aerial Robot", "model": "MK1", "status": "Unavailable", "last_seen": None},
            "telemetry": {"samples": 0, "latest": None},
            "missions": {"total": 0, "completed": 0},
            "faults": {"open": 0},
            "maintenance": {"records": 0},
            "camera_files": 0,
            "sensor_records": 0,
        },
    }


def get_workspace_data() -> dict[str, Any]:
    """Load the public R&D service without duplicating repository logic."""
    root = Path(ZERO_GRAVITY_RND_ROOT)
    if not root.exists():
        return _offline_workspace(f"R&D repository not found: {root}")

    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)

    try:
        from shared.services.rnd_workspace import get_workspace_data as engine_workspace
        return engine_workspace()
    except Exception as exc:  # dashboard must remain available during repairs
        return _offline_workspace(f"R&D integration failed: {exc}")


def get_total_tests() -> int:
    return int(get_workspace_data()["research"]["tests"]["total"])


def get_passed_tests() -> int:
    return int(get_workspace_data()["research"]["tests"]["passed"])


def get_failed_tests() -> int:
    return int(get_workspace_data()["research"]["tests"]["failed"])


def get_recent_tests(limit: int = 6) -> list[dict[str, Any]]:
    return get_workspace_data()["research"]["tests"]["recent"][:limit]


@rnd_bp.route("/")
def dashboard():
    return render_template("workspaces/research_development/dashboard.html", rnd=get_workspace_data())


@rnd_bp.route("/api/status")
def api_status():
    """Machine-readable status for future live dashboard refreshes."""
    return jsonify(get_workspace_data())
