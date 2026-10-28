"""Zero Command System - Operator workspace."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from flask import Blueprint, abort, current_app, jsonify, render_template, url_for

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

    main_stats = _main_stats(stats)
    overall = (
        sum(item["average_level"] for item in main_stats) / len(main_stats)
        if main_stats else 0.0
    )
    strongest_stat = max(main_stats, key=lambda item: item["average_level"], default=None)
    int_domains = _int_domains(stats)
    strongest_domain = max(int_domains, key=lambda item: item["average_level"], default=None)
    active_capabilities = _featured_capabilities(competencies)
    current_focus = max(active_capabilities, key=lambda item: (item["xp"], item["coverage"]), default=None)

    if level >= 20:
        operator_title = "Systems Architect"
    elif level >= 10:
        operator_title = "R&D Operator"
    elif level >= 5:
        operator_title = "Developing Operator"
    else:
        operator_title = "Initiate"

    return {
        "operator_name": "Zero",
        "operator_title": operator_title,
        "operator_level": level,
        "overall": overall,
        "total_xp": total_xp,
        "next_level_xp": next_level_xp,
        "xp_to_next_level": max(next_level_xp - total_xp, 0),
        "level_progress": max(0.0, progress),
        "strongest_stat": strongest_stat,
        "strongest_domain": strongest_domain,
        "current_focus": current_focus,
        "competency_count": int(stats_data.get("competency_count", len(competencies))),
        "shared_competency_count": shared_count,
        "main_stats": main_stats,
        "int_domains": int_domains,
        "tree": stats,
        "concepts_by_capability": _all_capability_concepts(),
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
    # Serves the sci-fi HUD shell (approved mockup, see project docs:
    # "Operator Workspace HUD Mockup: Handoff"). The shell itself is static -
    # all real data comes from GET /operator/hud/data (modules/operator_hud.py),
    # fetched client-side on load, so one hub's data failing can't blank the
    # whole page the way the old dashboard=None/operator_error path could.
    # The old dashboard.html stays on disk, untouched, as a fallback if this
    # ever needs to be reverted.
    return render_template("workspaces/operator/hud.html")


@operator_bp.route("/room")
def room():
    """The 3D Operator Development room (gym / study / reflection zones).

    Click-into-full-page-dashboard stays available via the "View Skill
    Tree" link the stat panel renders - this route is just the room shell,
    the actual stat data comes from /operator/api/summary below.
    """
    return render_template("rooms/operator_development.html")


@operator_bp.route("/api/summary")
def api_summary():
    """Slim JSON version of get_operator_dashboard_data(), for the
    in-scene stat panel - same underlying data as the full dashboard page,
    just shaped for a popup instead of a full render_template() page."""
    try:
        data = get_operator_dashboard_data()
    except (FileNotFoundError, ValueError, OSError) as error:
        return jsonify({"error": str(error)}), 200

    return jsonify({
        "operator_name": data["operator_name"],
        "operator_title": data["operator_title"],
        "operator_level": data["operator_level"],
        "overall": data["overall"],
        "total_xp": data["total_xp"],
        "next_level_xp": data["next_level_xp"],
        "xp_to_next_level": data["xp_to_next_level"],
        "level_progress": data["level_progress"],
        "main_stats": data["main_stats"],
        "skill_tree_url": url_for("operator.dashboard"),
    })


def _all_capability_concepts() -> dict[str, list[dict[str, Any]]]:
    """Concepts for every capability, keyed by competency_id - reuses the
    same fields get_capability_data() builds for a single capability, so
    the drill-down modal and the dedicated capability page never disagree."""
    graph = _capability_graph()
    concept_progress = graph.get("concept_progress", {})
    result: dict[str, list[dict[str, Any]]] = {}
    for capability in graph.get("capabilities", {}).values():
        if not isinstance(capability, dict):
            continue
        capability_id = capability.get("id", "")
        concepts = []
        for concept_id, concept in capability.get("concepts", {}).items():
            progress = concept_progress.get(concept_id, {})
            concepts.append({
                "id": concept_id,
                "name": concept.get("name", concept_id),
                "xp": int(progress.get("xp", 0)),
                "level": int(progress.get("level", 0)),
                "status": progress.get("status", "Not Started"),
            })
        result[capability_id] = concepts
    return result


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


def _tier_concepts(concepts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Assigns each concept a 0-indexed tier by topological depth through
    its prerequisites (tier 0 = no prerequisites = foundations), and
    resolves each prerequisite id to its display name for the "suggested
    after" hint. Prerequisites are informational only - nothing in this
    system gates XP on them - so a dangling id is simply dropped, and a
    prerequisite edge that would complete a cycle is ignored for that one
    edge (standard longest-path-with-cycle-removal) rather than recursing
    forever; real cycles aren't expected in the data, this just guarantees
    termination if one ever sneaks in.

    Mutates each concept dict in place (adds "tier"/"prerequisite_names")
    and also returns a "tiers" list of {index, label, concepts} groups,
    sorted and ready for the template to iterate directly."""
    by_id = {concept["id"]: concept for concept in concepts}
    tier_cache: dict[str, int] = {}

    def tier_of(concept_id: str, on_path: frozenset[str]) -> int:
        if concept_id in tier_cache:
            return tier_cache[concept_id]
        concept = by_id.get(concept_id)
        prereq_ids = [pid for pid in (concept.get("prerequisites") or []) if pid in by_id] if concept else []
        on_path = on_path | {concept_id}
        usable_ids = [pid for pid in prereq_ids if pid not in on_path]
        result = 1 + max((tier_of(pid, on_path) for pid in usable_ids), default=-1)
        tier_cache[concept_id] = result
        return result

    for concept in concepts:
        concept["tier"] = tier_of(concept["id"], frozenset())
        concept["prerequisite_names"] = [
            by_id[pid]["name"] for pid in (concept.get("prerequisites") or []) if pid in by_id
        ]

    max_tier = max((concept["tier"] for concept in concepts), default=-1)
    tiers = [
        {
            "index": index,
            "label": "FOUNDATIONS" if index == 0 else f"TIER {index + 1}",
            "concepts": sorted(
                (concept for concept in concepts if concept["tier"] == index),
                key=lambda concept: concept["name"].lower(),
            ),
        }
        for index in range(max_tier + 1)
    ]
    return concepts, tiers


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
    concepts, tiers = _tier_concepts(concepts)
    return {
        "id": capability_id,
        "name": capability.get("name", slug.title()),
        "slug": slug,
        "description": capability.get("description", ""),
        "xp": int(record.get("xp", 0)),
        "level": int(record.get("level", 0)),
        "coverage": round((started / len(concepts)) * 100, 1) if concepts else 0.0,
        "started_count": started,
        "concepts": concepts,
        "tiers": tiers,
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


@operator_bp.route("/capabilities/<slug>/data")
def capability_data(slug: str):
    """Thin JSON sibling of capability() above - same get_capability_data(),
    just jsonify()'d instead of rendered. Added so the HUD's in-shell skill
    page (operator_hud.js's renderSkillPage(), reached via #skill/<slug>)
    can fetch the already-correct tiered concept data on demand, without a
    second, hand-maintained copy of the tiering logic in JavaScript."""
    try:
        return jsonify(get_capability_data(slug))
    except KeyError:
        return jsonify({"error": "Capability not found."}), 404
    except (FileNotFoundError, ValueError, OSError) as error:
        return jsonify({"error": str(error)}), 200
