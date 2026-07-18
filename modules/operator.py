"""Zero Command System - Operator workspace."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from flask import Blueprint, abort, current_app, render_template

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
    preferred = ["CON", "INT", "STR", "DEX", "DISC", "WILL", "SPIRIT"]
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



def _featured_capabilities(competencies: dict[str, Any]) -> list[dict[str, Any]]:
    graph = _capability_graph()
    featured = []
    for capability in graph.get("capabilities", {}).values():
        if not isinstance(capability, dict) or not capability.get("slug"):
            continue
        record = competencies.get(capability.get("id"), {})
        progress = graph.get("concept_progress", {})
        concepts = capability.get("concepts", {})
        started = sum(1 for cid in concepts if int(progress.get(cid, {}).get("xp", 0)) > 0)
        featured.append({
            "name": capability.get("name"), "slug": capability.get("slug"),
            "description": capability.get("description", ""),
            "xp": int(record.get("xp", 0)), "level": int(record.get("level", 0)),
            "coverage": round((started / len(concepts)) * 100, 1) if concepts else 0.0,
        })
    return sorted(featured, key=lambda item: item["name"].lower())

def get_operator_dashboard_data() -> dict[str, Any]:
    rnd_root = _rnd_root()
    stats_path = rnd_root / "operator_core" / "hubs" / "learning" / "stats" / "learning_stats.json"
    competencies_path = rnd_root / "operator_core" / "capabilities" / "competencies.json"

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
    next_level_xp = int(stats_data.get("next_level_xp", 100))
    progress = float(stats_data.get("level_progress", 0.0))

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
        "capability_names": {item.get("name"): item.get("slug") for item in _capability_graph().get("capabilities", {}).values() if isinstance(item, dict) and item.get("name") and item.get("slug")},
        "featured_capabilities": _featured_capabilities(competencies),
        "capability_slugs": {
            item.get("id"): item.get("slug")
            for item in _capability_graph().get("capabilities", {}).values()
            if isinstance(item, dict) and item.get("id") and item.get("slug")
        },
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
        ), 200


def _capability_graph() -> dict[str, Any]:
    path = _rnd_root() / "operator_core" / "capabilities" / "capability_graph.json"
    return _load_json(path)


def _track_cards_for_capability(capability_id: str) -> list[dict[str, Any]]:
    tracks_root = _rnd_root() / "learning" / "tracks"
    cards: list[dict[str, Any]] = []
    if not tracks_root.exists():
        return cards
    for metadata_path in tracks_root.rglob("metadata.json"):
        try:
            metadata = _load_json(metadata_path)
            progress = _load_json(metadata_path.parent / "progress.json")
        except (FileNotFoundError, ValueError, OSError):
            continue
        awards = metadata.get("default_competency_awards", [])
        ids = {str(item.get("competency_id", "")) for item in awards if isinstance(item, dict)}
        if str(metadata.get("competency_id", "")) != capability_id and capability_id not in ids:
            continue
        units = metadata.get("units", [])
        completed = int(progress.get("external_completed_units") or len(progress.get("completed_units", [])))
        total = int(progress.get("external_total_units") or metadata.get("external_total_units") or len(units))
        cards.append({
            "id": metadata.get("id", metadata_path.parent.name),
            "title": metadata.get("title", metadata_path.parent.name),
            "provider": metadata.get("provider", "Unknown"),
            "status": progress.get("status", "In Progress"),
            "completed": completed,
            "total": total,
            "percentage": round((completed / total) * 100, 1) if total else 0.0,
            "xp": int(progress.get("total_xp", 0)),
            "source_url": metadata.get("source_url", ""),
        })
    return sorted(cards, key=lambda item: item["title"].lower())


def get_capability_data(slug: str) -> dict[str, Any]:
    graph = _capability_graph()
    capability = next(
        (item for item in graph.get("capabilities", {}).values() if item.get("slug") == slug),
        None,
    )
    if not capability:
        raise KeyError(slug)
    capability_id = capability["id"]
    competencies = _load_json(_rnd_root() / "operator_core" / "capabilities" / "competencies.json").get("competencies", {})
    record = competencies.get(capability_id, {})
    concept_progress = graph.get("concept_progress", {})
    concepts = []
    for concept_id, concept in capability.get("concepts", {}).items():
        progress = concept_progress.get(concept_id, {})
        concepts.append({
            "id": concept_id,
            "name": concept.get("name", concept_id),
            "description": concept.get("description", ""),
            "prerequisites": concept.get("prerequisites", []),
            "xp": int(progress.get("xp", 0)),
            "level": int(progress.get("level", 0)),
            "status": progress.get("status", "Not Started"),
            "mapping_confidence": progress.get("last_mapping_confidence", "unmapped"),
        })
    started = sum(1 for concept in concepts if concept["xp"] > 0 or concept["status"] != "Not Started")
    return {
        "id": capability_id,
        "name": capability.get("name", slug.title()),
        "slug": slug,
        "description": capability.get("description", ""),
        "xp": int(record.get("xp", 0)),
        "level": int(record.get("level", 0)),
        "coverage": round((started / len(concepts)) * 100, 1) if concepts else 0.0,
        "concepts": concepts,
        "relationships": capability.get("relationships", []),
        "tracks": _track_cards_for_capability(capability_id),
    }


@operator_bp.route("/capabilities/<slug>")
def capability(slug: str):
    try:
        return render_template("workspaces/operator/capability.html", capability=get_capability_data(slug), operator_error=None)
    except KeyError:
        abort(404)
    except (FileNotFoundError, ValueError, OSError) as error:
        return render_template("workspaces/operator/capability.html", capability=None, operator_error=str(error)), 200
