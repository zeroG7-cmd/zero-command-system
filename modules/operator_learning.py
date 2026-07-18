"""Zero Command System — Operator Learning Hub v2.0."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, redirect, render_template, request, url_for

operator_learning_bp = Blueprint(
    "operator_learning",
    __name__,
    url_prefix="/operator/learning",
)

DEFAULT_XP_RULES = {
    "manual": 40,
    "video": 30,
    "article": 25,
    "quiz": 35,
    "notebook": 40,
    "script": 30,
    "script_topic": 35,
    "exercise": 45,
    "challenge": 50,
    "lab": 55,
    "assignment": 60,
    "project": 100,
}


def _rnd_root() -> Path:
    env = os.getenv("ZERO_GRAVITY_RND_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    configured = current_app.config.get("ZERO_GRAVITY_RND_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(current_app.root_path).resolve().parent / "zeroGravity-rnd"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Required learning file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def _meaningful_text(path: Path) -> bool:
    if not path.exists() or not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.stat().st_size > 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line in {"...", "TODO", "TBD", "[ ]", "- [ ]"}:
            continue
        if line.startswith("- [ ]"):
            continue
        return True
    return False


def _knowledge(metadata: dict[str, Any]) -> str:
    return " > ".join(
        str(value)
        for value in [metadata.get("stat", "Unknown"), *metadata.get("hierarchy", [])]
        if value
    )


def _track_paths() -> list[Path]:
    root = _rnd_root() / "learning" / "tracks"
    if not root.exists():
        return []
    return sorted(
        metadata.parent
        for metadata in root.rglob("metadata.json")
        if (metadata.parent / "progress.json").exists()
    )


def _evidence(track: Path, metadata: dict[str, Any], progress: dict[str, Any]) -> dict[str, Any]:
    units = metadata.get("units", [])
    requirements = metadata.get("evidence_requirements", [])
    if not units:
        return {
            "current_unit": None,
            "items": [],
            "passed_count": 0,
            "required_count": 0,
            "complete": False,
        }

    index = max(0, min(int(progress.get("current_unit_index", 0)), len(units) - 1))
    unit = units[index]
    unit_relative_path = str(unit.get("path", "")).strip()
    if not unit_relative_path or not requirements:
        return {
            "current_unit": unit,
            "items": [],
            "passed_count": 0,
            "required_count": 0,
            "complete": False,
        }

    unit_path = track / unit_relative_path
    items = []
    for requirement in requirements:
        requirement_path = str(requirement.get("path", "")).strip()
        if not requirement_path:
            continue
        path = unit_path / requirement_path
        items.append(
            {
                "name": requirement.get("name", requirement_path),
                "relative_path": requirement_path,
                "passed": _meaningful_text(path),
            }
        )
    passed = sum(1 for item in items if item["passed"])
    return {
        "current_unit": unit,
        "items": items,
        "passed_count": passed,
        "required_count": len(items),
        "complete": bool(items) and passed == len(items),
    }


def _normalise_awards(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    merged: dict[str, float] = {}
    order: list[str] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        competency_id = str(item.get("competency_id", "")).strip()
        try:
            weight = float(item.get("weight", 0))
        except (TypeError, ValueError):
            continue
        if not competency_id or weight <= 0:
            continue
        if competency_id not in merged:
            order.append(competency_id)
            merged[competency_id] = 0.0
        merged[competency_id] += weight
    total = sum(merged.values())
    if total <= 0:
        return []
    return [
        {"competency_id": competency_id, "weight": merged[competency_id] / total}
        for competency_id in order
    ]


def _resolve_awards(metadata: dict[str, Any], unit: dict[str, Any]) -> list[dict[str, Any]]:
    awards = _normalise_awards(unit.get("competency_awards"))
    if awards:
        return awards
    sections = metadata.get("section_competency_awards", {})
    if isinstance(sections, dict):
        for key in (
            str(unit.get("section_number", "")),
            str(unit.get("section_title", "")),
        ):
            awards = _normalise_awards(sections.get(key))
            if awards:
                return awards
    awards = _normalise_awards(metadata.get("default_competency_awards"))
    if awards:
        return awards
    competency_id = str(metadata.get("competency_id", "")).strip()
    return [{"competency_id": competency_id, "weight": 1.0}] if competency_id else []


def _unit_xp(metadata: dict[str, Any], unit: dict[str, Any]) -> int:
    try:
        explicit = int(unit.get("xp_value"))
        if explicit >= 0:
            return explicit
    except (TypeError, ValueError):
        pass
    rules = DEFAULT_XP_RULES.copy()
    if isinstance(metadata.get("xp_rules"), dict):
        for key, value in metadata["xp_rules"].items():
            try:
                rules[str(key)] = max(0, int(value))
            except (TypeError, ValueError):
                pass
    return rules.get(str(unit.get("source_type", "manual")), rules["manual"])


def _reward_preview(metadata: dict[str, Any], unit: dict[str, Any]) -> dict[str, Any]:
    total_xp = _unit_xp(metadata, unit)
    awards = _resolve_awards(metadata, unit)
    registry = _load_json(_rnd_root() / "operator_core" / "capabilities" / "competencies.json").get(
        "competencies", {}
    )
    exact = [total_xp * award["weight"] for award in awards]
    values = [math.floor(value) for value in exact]
    remainder = total_xp - sum(values)
    indexes = sorted(
        range(len(awards)),
        key=lambda index: (exact[index] - values[index], -index),
        reverse=True,
    )
    for index in indexes[:remainder]:
        values[index] += 1

    items = []
    for index, award in enumerate(awards):
        competency = registry.get(award["competency_id"], {})
        items.append(
            {
                "competency_id": award["competency_id"],
                "name": competency.get("name", award["competency_id"]),
                "weight_percentage": round(award["weight"] * 100),
                "xp": values[index],
            }
        )
    return {"total_xp": total_xp, "items": items}


def _card(track: Path) -> dict[str, Any]:
    metadata = _load_json(track / "metadata.json")
    progress = _load_json(track / "progress.json")
    units = metadata.get("units", [])

    completed = max(
        len(progress.get("completed_units", [])),
        int(progress.get("external_completed_units", 0) or 0),
    )

    provider_total = (
        int(progress.get("external_total_units", 0) or 0)
        or int(metadata.get("external_total_units", 0) or 0)
        or int(metadata.get("unit_count", 0) or 0)
    )

    total = provider_total if provider_total > 0 else len(units)

    completed = min(completed, total) if total > 0 else completed

    evidence = _evidence(track, metadata, progress)
    current_unit = evidence["current_unit"]

    return {
        "id": metadata.get("id", track.name),
        "title": metadata.get("title", track.name),
        "provider": metadata.get("provider", "Unknown"),
        "difficulty": metadata.get("difficulty", "Unknown"),
        "knowledge_path": _knowledge(metadata),
        "skill": metadata.get("skill", ""),
        "source_url": metadata.get("source_url", ""),
        "completed_count": completed,
        "unit_count": total,
        "percentage": round((completed / total) * 100, 1) if total else 0.0,
        "total_xp": int(progress.get("total_xp", 0)),
        "status": progress.get("status", "In Progress"),
        "current_unit": current_unit,
        "evidence": evidence,
        "reward_preview": (
            _reward_preview(metadata, current_unit)
            if current_unit
            else None
        ),
    }


def get_learning_hub_data() -> dict[str, Any]:
    cards: list[dict[str, Any]] = []
    track_errors: list[str] = []
    for path in _track_paths():
        try:
            cards.append(_card(path))
        except Exception as error:
            track_errors.append(f"{path.name}: {error}")

    total = sum(card["unit_count"] for card in cards)
    done = sum(card["completed_count"] for card in cards)
    stats_path = _rnd_root() / "operator_core" / "hubs" / "learning" / "stats" / "learning_stats.json"
    operator_stats = _load_json(stats_path) if stats_path.exists() else {}
    return {
        "tracks": cards,
        "track_count": len(cards),
        "total_units": total,
        "completed_units": done,
        "total_track_xp": sum(card["total_xp"] for card in cards),
        "overall_percentage": round((done / total) * 100, 1) if total else 0.0,
        "operator_level": operator_stats.get("level", 0),
        "operator_total_xp": operator_stats.get("total_xp", 0),
        "operator_level_progress": operator_stats.get("level_progress", 0.0),
        "operator_xp_to_next": operator_stats.get("xp_to_next_level", 100),
        "rnd_root": str(_rnd_root()),
        "providers": (
            _load_json(_rnd_root() / "learning" / "config" / "provider_registry.json")
            .get("providers", {})
            if (_rnd_root() / "learning" / "config" / "provider_registry.json").exists()
            else {}
        ),
        "track_errors": track_errors,
    }


def _selection(track_id: str) -> int:
    for index, path in enumerate(_track_paths(), start=1):
        if _load_json(path / "metadata.json").get("id", path.name) == track_id:
            return index
    raise ValueError(f"Learning track not found: {track_id}")


def _run(script_name: str, stdin: str = "", args: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    root = _rnd_root()
    script = root / "learning" / "engine" / script_name
    if not script.exists():
        raise FileNotFoundError(f"Learning engine script not found: {script}")
    return subprocess.run(
        [sys.executable, str(script), *(args or [])],
        input=stdin,
        text=True,
        capture_output=True,
        cwd=str(root),
        timeout=120,
        check=False,
    )


@operator_learning_bp.route("/")
def dashboard():
    try:
        return render_template(
            "workspaces/operator/learning.html",
            hub=get_learning_hub_data(),
            learning_error=None,
            action_output=request.args.get("output"),
        )
    except Exception as error:
        return render_template(
            "workspaces/operator/learning.html",
            hub=None,
            learning_error=str(error),
            action_output=None,
        ), 500


@operator_learning_bp.post("/tracks/<track_id>/complete")
def complete_current_unit(track_id: str):
    try:
        result = _run("tracker.py", f"{_selection(track_id)}\n")
        output = (result.stdout + "\n" + result.stderr).strip()
    except Exception as error:
        output = f"LEARNING ENGINE ERROR\n{error}"
    return redirect(url_for("operator_learning.dashboard", output=output[-5000:]))


@operator_learning_bp.post("/import")
def import_manifest():
    manifest = request.form.get("manifest_path", "").strip()
    if not manifest:
        return redirect(
            url_for(
                "operator_learning.dashboard",
                output="IMPORT ERROR\nEnter a manifest file or resource directory.",
            )
        )
    try:
        result = _run("import_manifest.py", f"{manifest}\ny\ny\n")
        output = (result.stdout + "\n" + result.stderr).strip()
    except Exception as error:
        output = f"IMPORT ERROR\n{error}"
    return redirect(url_for("operator_learning.dashboard", output=output[-5000:]))


@operator_learning_bp.post("/providers/bootdev/reconcile")
def reconcile_bootdev():
    """Repair/mirror Boot.dev track counts without duplicate XP."""
    try:
        result = _run(
            "setup_bootdev.py",
            args=["--apply-history"],
        )
        output = (result.stdout + "\n" + result.stderr).strip()
    except Exception as error:
        output = f"BOOT.DEV RECONCILIATION ERROR\n{error}"
    return redirect(
        url_for("operator_learning.dashboard", output=output[-5000:])
    )


@operator_learning_bp.post("/provider-progress")
def import_provider_progress():
    snapshot = request.form.get("snapshot_path", "").strip()
    dry_run = request.form.get("dry_run") == "on"
    if not snapshot:
        return redirect(url_for("operator_learning.dashboard", output="PROVIDER IMPORT ERROR\nEnter a progress snapshot path."))
    args = [snapshot]
    if dry_run:
        args.append("--dry-run")
    try:
        result = _run("import_provider_progress.py", args=args)
        output = (result.stdout + "\n" + result.stderr).strip()
    except Exception as error:
        output = f"PROVIDER IMPORT ERROR\n{error}"
    return redirect(url_for("operator_learning.dashboard", output=output[-5000:]))
