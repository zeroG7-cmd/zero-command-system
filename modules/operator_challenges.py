"""Operator Challenges Hub routes.

Time-boxed XP goals, auto-tracked from the same event-ledger +
distribution-receipt system every other hub feeds - never a manual check-in.
A challenge is either self-set (pick a scope + target XP + duration) or
accepted from a system suggestion (a stat with zero XP logged so far).
Progress is fully derived every time this page loads by summing receipt XP
whose allocations fall inside the challenge's scope and date window - the
same receipt-scanning approach Analytics Hub already uses, just scoped to a
competency/category/stat and a date range instead of a whole hub. Only the
challenge's own definition (scope/target/dates) needs real storage; nothing
about progress is ever separately persisted, so it can never drift from the
real receipts the way a second hand-kept counter could.

Completing a challenge awards a small, flat, discipline-only bonus - never
XP into whatever the challenge targeted, since that XP was already earned
for real by whatever hub logged the underlying work; paying it again would
be double counting the same effort. The bonus goes to one specific real
leaf capability (disc.consistency.task_completion.follow_through - "you set
a goal and saw it through"), same "always a real leaf, never a flat stat"
rule every hub in this system follows. It goes through the same event +
receipt path as every other award, idempotency-keyed to the challenge's own
id, so re-evaluating an already-completed challenge on every page load can
never pay the bonus twice.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, jsonify, render_template, request

bp = Blueprint("operator_challenges", __name__, url_prefix="/operator/challenges")

MAIN_STATS = ["CON", "INT", "STR", "DEX", "DISC", "WILL", "SPIRIT"]

# "Small" and flat, deliberately: it doesn't scale with the challenge's own
# target, so a bigger target can't be used to farm a bigger bonus, and it
# stays clearly secondary to whatever real XP the challenge's underlying
# work already earned. One flat unit, same rate as one honest Task Hub hour.
BONUS_XP = 20
BONUS_COMPETENCY_ID = "disc.consistency.task_completion.follow_through"

SUGGESTION_TARGET_XP = 50
SUGGESTION_DURATION_DAYS = 7
DEFAULT_DURATIONS = [7, 14, 30]


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
    from learning.engine import stats as stats_engine
    from operator_core.events.models import OperatorEvent
    from operator_core.events.service import EventLedger
    from operator_core.distribution.service import DistributionService

    return stats_engine, OperatorEvent, EventLedger, DistributionService


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _skill_tree() -> dict[str, Any]:
    return _load_json(_rnd_root() / "operator_core/capabilities/skill_tree.json", {"stats": {}})


def _learning_stats() -> dict[str, Any]:
    return _load_json(
        _rnd_root() / "operator_core/hubs/learning/stats/learning_stats.json", {"stats": {}}
    )


def _goals_path() -> Path:
    path = _rnd_root() / "operator_core/profile/data/active_goals.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_goals() -> list[dict[str, Any]]:
    data = _load_json(_goals_path(), {"schema_version": 1, "goals": []})
    goals = data.get("goals", []) if isinstance(data, dict) else []
    return goals if isinstance(goals, list) else []


def _strip_transient(goal: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in goal.items() if k != "progress"}


def _save_goals(goals: list[dict[str, Any]]) -> None:
    clean = [_strip_transient(g) for g in goals]
    _goals_path().write_text(
        json.dumps({"schema_version": 1, "goals": clean}, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Same recursive nested-grouping walk modules/tasks.py and
# modules/operator_execution.py already use (needed for e.g.
# INT/Robotics/Robot Software's extra grouping layer) - kept as its own
# local copy, same convention those two modules already follow.
# ---------------------------------------------------------------------------
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


def _catalog(tree: dict[str, Any]) -> list[dict[str, Any]]:
    """Full unscoped Stat -> Category -> Subcategory -> Capability catalog,
    same flat shape Execution Hub's own _catalog() already uses (one entry
    per stat+category pair) - a challenge can target anything, and reusing
    the identical shape means the picker JS can reuse the same cascading
    pattern already proven there."""
    catalog: list[dict[str, Any]] = []
    for stat_name, stat_node in tree.get("stats", {}).items():
        for cat_name, cat_node in stat_node.get("children", {}).items():
            subcats: dict[str, list[str]] = {}
            for sub_name, sub_node in cat_node.get("children", {}).items():
                if not isinstance(sub_node, dict):
                    continue
                caps = list(_leaf_capabilities(sub_node).keys())
                if caps:
                    subcats[sub_name] = caps
            if subcats:
                catalog.append({"stat": stat_name, "category": cat_name, "subcategories": subcats})
    return catalog


def _category_competency_ids(tree: dict[str, Any], stat: str, category: str) -> set[str]:
    cat_node = tree.get("stats", {}).get(stat, {}).get("children", {}).get(category)
    if not isinstance(cat_node, dict):
        return set()
    return {
        str(c.get("competency_id"))
        for c in _leaf_capabilities(cat_node).values()
        if c.get("competency_id")
    }


def _stat_competency_ids(tree: dict[str, Any], stat: str) -> set[str]:
    stat_node = tree.get("stats", {}).get(stat, {})
    if not isinstance(stat_node, dict):
        return set()
    return {
        str(c.get("competency_id"))
        for c in _leaf_capabilities(stat_node).values()
        if c.get("competency_id")
    }


def _resolve_capability_id(
    tree: dict[str, Any], stat: str, category: str, subcategory: str, capability: str
) -> str | None:
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


def _resolve_scope(
    tree: dict[str, Any], scope_type: str, scope: dict[str, Any]
) -> tuple[set[str], str] | None:
    """Re-derives the real competency_id set server-side from the posted
    scope - never trusts anything posted directly, same rule every other
    picker in this system follows. Returns (competency_id set, human label)
    or None if the scope doesn't resolve to anything real."""
    if scope_type == "stat":
        stat = str(scope.get("stat", "")).upper()
        if stat not in MAIN_STATS:
            return None
        ids = _stat_competency_ids(tree, stat)
        return (ids, stat) if ids else None
    if scope_type == "category":
        stat = str(scope.get("stat", "")).upper()
        category = str(scope.get("category", ""))
        if stat not in MAIN_STATS or not category:
            return None
        ids = _category_competency_ids(tree, stat, category)
        return (ids, f"{stat} / {category}") if ids else None
    if scope_type == "competency":
        stat = str(scope.get("stat", "")).upper()
        category = str(scope.get("category", ""))
        subcategory = str(scope.get("subcategory", ""))
        capability = str(scope.get("capability", ""))
        cid = _resolve_capability_id(tree, stat, category, subcategory, capability)
        if not cid:
            return None
        return ({cid}, capability)
    return None


# ---------------------------------------------------------------------------
# Events/receipts - same loaders operator_analytics.py already uses.
# ---------------------------------------------------------------------------
def _events(root: Path) -> dict[str, dict[str, Any]]:
    path = root / "operator_core/events/operator_events.jsonl"
    events: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return events
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        event_id = event.get("event_id")
        if event_id:
            events[event_id] = event
    return events


def _receipts(root: Path) -> list[dict[str, Any]]:
    d = root / "operator_core/distribution/receipts"
    if not d.exists():
        return []
    out = []
    for path in d.glob("*.json"):
        data = _load_json(path, None)
        if isinstance(data, dict):
            out.append(data)
    return out


def _effective_time(receipt: dict[str, Any], event: dict[str, Any] | None) -> str:
    if event and event.get("occurred_at"):
        return str(event["occurred_at"])
    return str(receipt.get("created_at", ""))


def _parse_iso(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _progress_for_scope(
    competency_ids: set[str],
    starts_at: str,
    ends_at: str,
    receipts: list[dict[str, Any]],
    events: dict[str, dict[str, Any]],
) -> int:
    if not competency_ids:
        return 0
    start_dt = _parse_iso(starts_at)
    end_dt = _parse_iso(ends_at)
    total = 0
    for receipt in receipts:
        # A challenge's own completion bonus must never count toward itself
        # or toward any other challenge whose scope happens to include the
        # bonus competency (e.g. a whole-DISC challenge) - otherwise the
        # bonus payout could cascade into completing more challenges.
        if receipt.get("source_event_type") == "challenge_completed":
            continue
        event = events.get(receipt.get("source_event_id", ""))
        when = _parse_iso(_effective_time(receipt, event))
        if when is None:
            continue
        if start_dt and when < start_dt:
            continue
        if end_dt and when > end_dt:
            continue
        for alloc in receipt.get("allocations", []):
            if str(alloc.get("target_id", "")) in competency_ids:
                total += int(alloc.get("xp", 0))
    return total


def _evaluate_goals(
    goals: list[dict[str, Any]],
    tree: dict[str, Any],
    receipts: list[dict[str, Any]],
    events: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    """Recomputes progress for every active goal and completes or expires
    it as appropriate. `changed` is only True when a goal's persisted
    status actually transitions - progress itself is never persisted, so
    routine display recomputation on every page load never triggers a
    write on its own."""
    stats_engine, OperatorEvent, EventLedger, DistributionService = _engine_modules()
    ledger = EventLedger()
    distributor = DistributionService(ledger=ledger)
    now = datetime.now(timezone.utc)
    changed = False

    for goal in goals:
        if goal.get("status") != "active":
            continue

        resolved = _resolve_scope(tree, goal.get("scope_type", ""), goal.get("scope", {}))
        competency_ids = resolved[0] if resolved else set()
        progress = _progress_for_scope(
            competency_ids, goal.get("starts_at", ""), goal.get("ends_at", ""), receipts, events
        )
        goal["progress"] = progress

        target = int(goal.get("target_xp", 0))
        if target > 0 and progress >= target:
            goal["status"] = "completed"
            goal["completed_at"] = now.isoformat()
            changed = True

            event = ledger.append(
                OperatorEvent(
                    event_type="challenge_completed",
                    source="operator_core.challenges",
                    payload={
                        "goal_id": goal["id"],
                        "title": goal.get("title", ""),
                        "base_xp": BONUS_XP,
                        "xp_targets": [{"competency_id": BONUS_COMPETENCY_ID, "weight": 1.0}],
                    },
                    idempotency_key=f"challenge_completed:{goal['id']}",
                ),
                allow_existing=True,
            )
            receipt = distributor.distribute_event(event)
            allocations = [
                {"competency_id": a.target_id, "xp": a.xp}
                for a in receipt.allocations
                if a.target_type == "competency"
            ]
            if allocations:
                stats_engine.update_operator_competencies(allocations)
            goal["bonus_xp"] = BONUS_XP
            goal["bonus_event_id"] = event.event_id
            goal["bonus_receipt_id"] = receipt.receipt_id
            continue

        end_dt = _parse_iso(goal.get("ends_at", ""))
        if end_dt and now > end_dt:
            goal["status"] = "expired"
            changed = True

    return goals, changed


def _suggested_challenges(
    learning_stats: dict[str, Any], goals: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Flags stats with literally zero XP logged - the plain heuristic
    discussed with him ("hasn't moved at all") rather than a fuzzier
    "lagging its siblings" comparison. Skips a stat that already has an
    active challenge scoped to it, so the same gap isn't suggested twice."""
    stats = learning_stats.get("stats", {})
    active_stats = {
        str(g.get("scope", {}).get("stat", "")).upper()
        for g in goals
        if g.get("status") == "active"
    }

    suggestions = []
    for stat in MAIN_STATS:
        node = stats.get(stat, {})
        avg = float(node.get("average_level", 0.0)) if isinstance(node, dict) else 0.0
        if avg > 0 or stat in active_stats:
            continue
        suggestions.append(
            {
                "scope_type": "stat",
                "scope": {"stat": stat},
                "label": stat,
                "title": f"{stat} is still untouched",
                "why": f"average_level: 0.00 across every {stat} category",
                "target_xp": SUGGESTION_TARGET_XP,
                "duration_days": SUGGESTION_DURATION_DAYS,
            }
        )
    return suggestions


def _create_goal(tree: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    scope_type = str(payload.get("scope_type", "")).strip()
    scope = payload.get("scope", {}) if isinstance(payload.get("scope"), dict) else {}
    resolved = _resolve_scope(tree, scope_type, scope)
    if not resolved:
        raise ValueError("That scope doesn't resolve to anything real - refresh and try again.")
    _competency_ids, label = resolved

    try:
        target_xp = int(payload.get("target_xp", 0))
    except (TypeError, ValueError):
        raise ValueError("Target XP must be a whole number.")
    if target_xp < 10 or target_xp > 5000:
        raise ValueError("Target XP must be between 10 and 5000.")

    try:
        duration_days = int(payload.get("duration_days", 7))
    except (TypeError, ValueError):
        raise ValueError("Duration must be a whole number of days.")
    if duration_days < 1 or duration_days > 90:
        raise ValueError("Duration must be between 1 and 90 days.")

    title = str(payload.get("title", "")).strip() or f"{label} push"
    now = datetime.now(timezone.utc)
    return {
        "id": f"chl_{uuid.uuid4().hex[:12]}",
        "title": title,
        "scope_type": scope_type,
        "scope": scope,
        "scope_label": label,
        "target_xp": target_xp,
        "starts_at": now.isoformat(),
        "ends_at": (now + timedelta(days=duration_days)).isoformat(),
        "status": "active",
        "source": str(payload.get("source", "self")),
        "created_at": now.isoformat(),
        "completed_at": None,
        "bonus_xp": None,
        "bonus_event_id": None,
        "bonus_receipt_id": None,
    }


def get_challenges_dashboard_data(error: str | None = None) -> dict[str, Any]:
    """Same context dashboard() renders with - pulled out so the HUD shell's
    live-data aggregator (modules/operator_hud.py) can reuse it exactly."""
    root = _rnd_root()
    tree = _skill_tree()
    goals = _load_goals()
    receipts = _receipts(root)
    events = _events(root)

    goals, changed = _evaluate_goals(goals, tree, receipts, events)
    if changed:
        _save_goals(goals)

    active = [g for g in goals if g.get("status") == "active"]
    active.sort(key=lambda g: g.get("ends_at") or "")
    completed = [g for g in goals if g.get("status") == "completed"]
    completed.sort(key=lambda g: g.get("completed_at") or "", reverse=True)
    expired = [g for g in goals if g.get("status") == "expired"]
    expired.sort(key=lambda g: g.get("ends_at") or "", reverse=True)

    suggestions = _suggested_challenges(_learning_stats(), goals)

    return {
        "active_goals": active,
        "completed_goals": completed[:10],
        "expired_goals": expired[:10],
        "suggestions": suggestions,
        "catalog": _catalog(tree),
        "main_stats": MAIN_STATS,
        "durations": DEFAULT_DURATIONS,
        "bonus_xp": BONUS_XP,
        "error": error,
    }


@bp.get("/")
def dashboard():
    return render_template(
        "workspaces/operator/challenges.html",
        **get_challenges_dashboard_data(error=request.args.get("error")),
    )


@bp.post("/api/create")
def create():
    payload = request.get_json(silent=True) or {}
    tree = _skill_tree()
    try:
        goal = _create_goal(tree, payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    goals = _load_goals()
    goals.append(goal)
    _save_goals(goals)
    return jsonify(goal), 201


@bp.post("/api/<goal_id>/cancel")
def cancel(goal_id: str):
    goals = _load_goals()
    found = False
    for g in goals:
        if g.get("id") == goal_id and g.get("status") == "active":
            g["status"] = "cancelled"
            found = True
            break
    if not found:
        return jsonify({"error": "challenge not found or not active"}), 404
    _save_goals(goals)
    return jsonify({"ok": True}), 200
