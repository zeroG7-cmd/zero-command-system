"""Operator Execution Hub routes.

Project/Experiment completion log. Follows the same direct-import pattern
as modules/tasks.py and modules/operator_journal.py: resolves each picked
capability against the real skill tree server-side (never trusts a
client-posted competency_id), then awards a flat completion XP pool split
across whatever capabilities the project/experiment actually touched.
Unlike Task Hub, there's no day scope here: a project can touch anything
in the tree, so the picker walks the whole thing rather than a day-scoped
slice.

XP is driven by scope (small/medium/large -> EXECUTION_XP_BY_SCOPE below),
not by activity_type and not by hours logged. activity_type (project vs
experiment) stays a pure category label - it decides which stat
card/log tag a completion counts toward, nothing else. This is
deliberately its own scale, separate from learning.engine.xp's
DEFAULT_XP_RULES: that dict answers "what course-unit source_type is
this" for the Learning Engine, a different question from "how big was
this project", and reusing it here was a coincidence of the numbers
matching, not a real coupling worth keeping. Hours was tried first as the
XP driver and dropped - self-reported hours are trivially inflated, and
they'd double-count against Task Hub, which already awards XP for hours
logged against a capability during the week a project was being built.
Scope is a one-time, honest choice made at completion time instead.

Evidence-log persistence (dedup, records.json) still goes through
operator_core.execution.service, which stays skill-tree-unaware on
purpose - this module resolves everything real before handing it a
plain, already-validated payload.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, jsonify, render_template, request

bp = Blueprint("operator_execution", __name__, url_prefix="/operator/execution")

EXECUTION_XP_BY_SCOPE = {"small": 60, "medium": 100, "large": 160}


def _rnd_root() -> Path:
    env = os.getenv("ZERO_GRAVITY_RND_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    configured = current_app.config.get("ZERO_GRAVITY_RND_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(current_app.root_path).resolve().parent / "zeroGravity-rnd"


def _engine_modules():
    root = _rnd_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from learning.engine import xp as xp_engine, stats as stats_engine
    from operator_core.profile.progression import get_level_progress
    from operator_core.execution import service as execution_service
    return xp_engine, stats_engine, get_level_progress, execution_service


# ---------------------------------------------------------------------------
# Kept separate from _engine_modules() above so dashboard()'s call site
# doesn't need to change shape - only create() needs the event-ledger +
# distribution-receipt machinery. Same pattern journal/engine/service.py
# uses: emit an OperatorEvent, run it through DistributionService for an
# auditable receipt, then apply the receipt's own allocations - never the
# separately computed xp_awards preview - so the receipt and the actually
# applied XP can never drift apart. This is what makes a completed project
# or experiment show up in the Analytics Hub.
# ---------------------------------------------------------------------------
def _event_modules():
    root = _rnd_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from operator_core.events.models import OperatorEvent
    from operator_core.events.service import EventLedger
    from operator_core.distribution.service import DistributionService
    return OperatorEvent, EventLedger, DistributionService


def _skill_tree() -> dict[str, Any]:
    path = _rnd_root() / "operator_core" / "capabilities" / "skill_tree.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _competency_registry() -> dict[str, Any]:
    path = _rnd_root() / "operator_core" / "capabilities" / "competencies.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("competencies", data) if isinstance(data, dict) else data
    if isinstance(entries, list):
        return {str(item.get("id")): item for item in entries}
    return entries


# Most subcategories are flat (Subcategory -> Capability directly), but a
# few (e.g. Robotics/Robot Software) have an extra grouping layer in
# between - walk through any depth of that so nothing is hidden from the
# picker. Same helper as modules/tasks.py, kept as its own local copy
# since these Flask modules don't share a util module by convention here.
def _leaf_capabilities(node: dict[str, Any]) -> dict[str, dict[str, Any]]:
    leaves: dict[str, dict[str, Any]] = {}
    for name, child in node.get("children", {}).items():
        if not isinstance(child, dict):
            continue
        if child.get("node_type") == "competency_reference":
            leaves[name] = child
        else:
            leaves.update(_leaf_capabilities(child))
    return leaves


def _catalog(tree: dict[str, Any], registry: dict[str, Any], get_level_progress) -> list[dict[str, Any]]:
    """Full unscoped Stat -> Category -> Subcategory -> Capability catalog -
    a project/experiment can touch anything, unlike Task Hub's day scope.
    """
    catalog: list[dict[str, Any]] = []
    for stat_name, stat_node in tree.get("stats", {}).items():
        for cat_name, cat_node in stat_node.get("children", {}).items():
            subcats: dict[str, list[dict[str, Any]]] = {}
            for sub_name, sub_node in cat_node.get("children", {}).items():
                if not isinstance(sub_node, dict):
                    continue
                caps = []
                for cap_name, cap_node in _leaf_capabilities(sub_node).items():
                    competency_id = str(cap_node.get("competency_id", ""))
                    record = registry.get(competency_id, {})
                    xp = int(record.get("xp", 0))
                    progress = get_level_progress(xp)
                    caps.append({
                        "name": cap_name,
                        "competency_id": competency_id,
                        "xp": xp,
                        "level": progress["level"],
                        "progress_percentage": progress["progress_percentage"],
                    })
                if caps:
                    subcats[sub_name] = caps
            if subcats:
                catalog.append({"stat": stat_name, "category": cat_name, "subcategories": subcats})
    return catalog


def _resolve_capability(stat: str, category: str, subcategory: str, capability: str, tree: dict[str, Any]) -> str | None:
    """Re-derive the competency_id server-side from the picked path - never
    trust a competency_id posted from the client directly."""
    sub_node = (
        tree.get("stats", {})
        .get(stat, {})
        .get("children", {})
        .get(category, {})
        .get("children", {})
        .get(subcategory, {})
    )
    if not isinstance(sub_node, dict):
        return None
    leaf = _leaf_capabilities(sub_node).get(capability)
    if not leaf:
        return None
    return str(leaf.get("competency_id", "")) or None


def get_execution_dashboard_data() -> dict[str, Any]:
    """Same context dashboard() renders with - pulled out so the HUD shell's
    live-data aggregator (modules/operator_hud.py) can reuse it exactly,
    rather than re-deriving execution data a second way."""
    xp_engine, stats_engine, get_level_progress, execution_service = _engine_modules()
    tree = _skill_tree()
    registry = _competency_registry()
    competency_names = {cid: str(rec.get("name", cid)) for cid, rec in registry.items()}
    return {
        "catalog": _catalog(tree, registry, get_level_progress),
        "xp_by_scope": EXECUTION_XP_BY_SCOPE,
        "summary": execution_service.execution_summary(),
        "records": execution_service.list_executions(30),
        "competency_names": competency_names,
        "error": None,
    }


@bp.get("/")
def dashboard():
    return render_template("workspaces/operator/execution.html", **get_execution_dashboard_data())


@bp.post("/api")
def create():
    xp_engine, stats_engine, get_level_progress, execution_service = _engine_modules()
    payload = request.get_json(silent=True) or {}

    title = str(payload.get("title", "")).strip()
    activity_type = str(payload.get("activity_type", "")).strip().lower()
    scope = str(payload.get("scope", "")).strip().lower()
    picks = payload.get("capabilities", [])
    if not isinstance(picks, list):
        picks = []

    if activity_type not in execution_service.VALID_TYPES:
        return jsonify({"error": f"activity_type must be one of: {', '.join(sorted(execution_service.VALID_TYPES))}"}), 400
    if scope not in EXECUTION_XP_BY_SCOPE:
        return jsonify({"error": f"scope must be one of: {', '.join(sorted(EXECUTION_XP_BY_SCOPE))}"}), 400

    tree = _skill_tree()
    resolved: list[str] = []
    for pick in picks:
        if not isinstance(pick, dict):
            continue
        competency_id = _resolve_capability(
            str(pick.get("stat", "")), str(pick.get("category", "")),
            str(pick.get("subcategory", "")), str(pick.get("capability", "")), tree,
        )
        if competency_id and competency_id not in resolved:
            resolved.append(competency_id)

    if not resolved:
        return jsonify({"error": "no valid capabilities were resolved - refresh and try again"}), 400

    total_xp = EXECUTION_XP_BY_SCOPE[scope]
    xp_awards = xp_engine.distribute_xp(
        total_xp, [{"competency_id": cid, "weight": 1.0} for cid in resolved]
    )

    # Validate + fingerprint BEFORE any XP is awarded. If this exact record
    # already exists (e.g. a resubmitted/duplicate request), we must not
    # award XP a second time - the evidence log alone getting deduplicated
    # isn't enough, since XP is the irreversible side effect here.
    try:
        record = execution_service.build_record({
            "title": title,
            "activity_type": activity_type,
            "scope": scope,
            "capabilities": resolved,
            "xp_total": total_xp,
            "xp_awards": xp_awards,
            "evidence": payload.get("evidence", []),
            "reflection": payload.get("reflection", ""),
            "status": "completed",
            "source": "zero_command",
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    existing = execution_service.find_by_fingerprint(record["fingerprint"])
    if existing:
        return jsonify({**existing, "duplicate": True}), 200

    # Only now, after validation and the duplicate check both passed, do we
    # trigger the irreversible side effect and persist the evidence record.
    # Routed through the same event-ledger + distribution-receipt system
    # every other hub uses, reusing the record's own stable fingerprint as
    # the idempotency key so a genuine duplicate resubmission can never
    # award XP twice even if it somehow slipped past find_by_fingerprint().
    OperatorEvent, EventLedger, DistributionService = _event_modules()
    ledger = EventLedger()
    event = ledger.append(OperatorEvent(
        event_type="execution_completed",
        source="operator_core.execution",
        payload={
            "title": title,
            "activity_type": activity_type,
            "scope": scope,
            "capabilities": resolved,
            "evidence": record.get("evidence", []),
            "reflection": record.get("reflection", ""),
            "base_xp": total_xp,
            "xp_targets": [{"competency_id": cid, "weight": 1.0} for cid in resolved],
        },
        idempotency_key=f"execution:{record['fingerprint']}",
    ))
    receipt = DistributionService(ledger=ledger).distribute_event(event)

    # Apply XP from the receipt's own allocations, never the xp_awards
    # preview computed above - guarantees the receipt and the actually
    # applied XP can never drift apart. allocate_xp() (used by the receipt)
    # and distribute_xp() (used for the preview) are algorithmically
    # identical, so this doesn't change awarded amounts, only how they get
    # recorded.
    allocations = [
        {"competency_id": allocation.target_id, "xp": allocation.xp}
        for allocation in receipt.allocations
        if allocation.target_type == "competency"
    ]
    if allocations:
        stats_engine.update_operator_competencies(allocations)

    record["event_id"] = event.event_id
    record["receipt_id"] = receipt.receipt_id
    record = execution_service.persist_execution(record)

    return jsonify(record), 201
