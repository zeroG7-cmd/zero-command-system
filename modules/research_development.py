from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Blueprint, render_template

from config import ZERO_GRAVITY_RND_DB, ZERO_GRAVITY_RND_ROOT

try:
    from modules.shadow import get_shadow_summary
except ImportError:
    get_shadow_summary = None


rnd_bp = Blueprint(
    "research_development",
    __name__,
    url_prefix="/research-development",
)


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(ZERO_GRAVITY_RND_DB)
    connection.row_factory = sqlite3.Row
    return connection


def _safe_scalar(query: str, parameters: tuple[Any, ...] = ()) -> int:
    try:
        with _connect() as connection:
            row = connection.execute(query, parameters).fetchone()
            return int(row[0]) if row else 0
    except (sqlite3.Error, OSError, TypeError, ValueError):
        return 0


def get_total_tests() -> int:
    return _safe_scalar("SELECT COUNT(*) FROM test_runs")


def get_passed_tests() -> int:
    return _safe_scalar(
        """
        SELECT COUNT(*)
        FROM test_runs
        WHERE LOWER(TRIM(result)) = 'pass'
        """
    )


def get_failed_tests() -> int:
    return _safe_scalar(
        """
        SELECT COUNT(*)
        FROM test_runs
        WHERE LOWER(TRIM(result)) = 'fail'
        """
    )


def get_recent_tests(limit: int = 6) -> list[dict[str, Any]]:
    try:
        with _connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    test_name,
                    component,
                    source,
                    result,
                    notes,
                    timestamp
                FROM test_runs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        tests = []
        for row in rows:
            item = dict(row)
            item["result_class"] = _normalise_result(item.get("result"))
            tests.append(item)

        return tests
    except (sqlite3.Error, OSError):
        return []


def get_recent_experiments(limit: int = 8) -> list[dict[str, Any]]:
    try:
        with _connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    experiment_name,
                    category,
                    status,
                    hypothesis,
                    conclusion,
                    created_at,
                    updated_at
                FROM experiments
                ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [dict(row) for row in rows]
    except (sqlite3.Error, OSError):
        return []


def get_simulation_summary() -> dict[str, Any]:
    return {
        "runs": _safe_scalar("SELECT COUNT(*) FROM simulation_runs"),
        "telemetry_samples": _safe_scalar(
            "SELECT COUNT(*) FROM simulated_telemetry"
        ),
        "completed_runs": _safe_scalar(
            """
            SELECT COUNT(*)
            FROM simulation_runs
            WHERE LOWER(TRIM(status)) = 'completed'
            """
        ),
    }


def _normalise_result(result: Any) -> str:
    value = str(result or "").strip().lower()
    if value == "pass":
        return "pass"
    if value == "fail":
        return "fail"
    return "pending"


def _count_files(directory: Path, extensions: set[str] | None = None) -> int:
    if not directory.exists():
        return 0

    count = 0
    for path in directory.rglob("*"):
        if not path.is_file() or path.name == ".gitkeep":
            continue
        if extensions is None or path.suffix.lower() in extensions:
            count += 1
    return count


def _latest_file(directory: Path) -> dict[str, Any] | None:
    if not directory.exists():
        return None

    files = [
        path
        for path in directory.rglob("*")
        if path.is_file() and path.name != ".gitkeep"
    ]
    if not files:
        return None

    latest = max(files, key=lambda path: path.stat().st_mtime)
    modified = datetime.fromtimestamp(latest.stat().st_mtime)

    return {
        "name": latest.name,
        "relative_path": str(latest.relative_to(ZERO_GRAVITY_RND_ROOT)),
        "modified": modified.strftime("%d %b %Y · %H:%M"),
    }


def get_repository_summary() -> dict[str, Any]:
    root = Path(ZERO_GRAVITY_RND_ROOT)

    hardware_root = root / "data" / "hardware"
    simulation_root = root / "data" / "simulation"
    archive_root = root / "experiments_archive"
    cad_root = root / "cad"
    urdf_root = root / "urdf"

    return {
        "repo_online": root.exists(),
        "repo_path": str(root),
        "hardware_files": _count_files(hardware_root),
        "simulation_files": _count_files(simulation_root),
        "archived_experiments": _count_files(archive_root),
        "cad_assets": _count_files(
            cad_root,
            {
                ".step",
                ".stp",
                ".stl",
                ".iges",
                ".igs",
                ".f3d",
                ".f3z",
                ".sldprt",
            },
        ),
        "urdf_assets": _count_files(
            urdf_root,
            {".urdf", ".xacro", ".xml"},
        ),
        "latest_artifact": _latest_file(root),
    }


def get_workspace_data() -> dict[str, Any]:
    total = get_total_tests()
    passed = get_passed_tests()
    failed = get_failed_tests()
    pending = max(total - passed - failed, 0)

    shadow = (
        get_shadow_summary()
        if callable(get_shadow_summary)
        else {
            "database_online": False,
            "vehicle": {
                "name": "Shadow MK1",
                "status": "Unavailable",
            },
            "telemetry": {
                "samples": 0,
                "latest": None,
            },
            "missions": {
                "total": 0,
                "completed": 0,
            },
            "faults": {
                "open": 0,
            },
        }
    )

    return {
        "research": {
            "database_online": Path(ZERO_GRAVITY_RND_DB).exists(),
            "database_path": str(ZERO_GRAVITY_RND_DB),
            "tests": {
                "total": total,
                "passed": passed,
                "failed": failed,
                "pending": pending,
                "success_rate": round((passed / total) * 100) if total else 0,
                "recent": get_recent_tests(),
            },
            "experiments": get_recent_experiments(),
            "simulation": get_simulation_summary(),
        },
        "shadow": shadow,
        "repository": get_repository_summary(),
    }


@rnd_bp.route("/")
def dashboard():
    return render_template(
        "workspaces/research_development/dashboard.html",
        rnd=get_workspace_data(),
    )
