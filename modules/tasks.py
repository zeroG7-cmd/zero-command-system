"""Operator Weekly Ops - real Task Hub.

Replaces the earlier stub (a flat to-do list: a title plus a raw main-stat
dropdown - CON/STR/INT/DEX/DISC/WILL/SPIRIT). Tasks are still part of
Operator Development and still primarily evidence for Discipline (see
operator_core/hubs/tasks/README.md), but XP now routes into the real skill
tree instead of a bare stat: each weekday has a Category -> Subcategory ->
Capability picker scoped to that day's real recurring routine (the Notion
"zeroGravity Planner"), hours logged convert to XP via
learning.engine.xp.calculate_hourly_xp(), and the award lands on the one
specific capability picked - never split, never flat to the main stat.

Follows the same import-the-engine-directly pattern operator_journal.py
uses (not the CLI-subprocess pattern operator_fitness.py/operator_learning.py
use) since learning.engine is a proper importable package.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, redirect, render_template, request, url_for

bp = Blueprint("operator_tasks", __name__, url_prefix="/operator/tasks")


# ---------------------------------------------------------------------------
# Day -> real skill-tree scope. Matches his real recurring weekly routine
# (the Notion "zeroGravity Planner"), confirmed with him across several demo
# iterations. Robotics is the one deliberate subcategory split - Tuesday is
# CAD/frame work (Mechanical Design), Wednesday is electronics/ROS
# (Mechatronics + Robot Software) - everything else shows every real
# subcategory of the scoped category, walked live from skill_tree.json
# rather than a hand-typed subset, so a new subcategory he adds later shows
# up on its own instead of silently being left out.
# ---------------------------------------------------------------------------
DAYS: list[dict[str, Any]] = [
    {
        "key": "mon", "label": "Mon", "icon": "\U0001F916",
        "focus": "Software Engineering & Data Science",
        "desc": "Core software engineering, computer science and data fundamentals — the technical base your Python and data-science work sits on.",
        "scope": [("INT", "Software Engineering", None), ("INT", "Computer Science", None), ("INT", "Data & Databases", None)],
    },
    {
        "key": "tue", "label": "Tue", "icon": "\U0001F6E0️",
        "focus": "Drone Engineering & Flight Ops",
        "desc": "Drone hardware design, networking/RF links and aviation theory — the engineering and airspace knowledge behind the FPV build.",
        "scope": [("INT", "Robotics", ["Mechanical Design"]), ("INT", "Networking", None), ("INT", "Aviation", None)],
    },
    {
        "key": "wed", "label": "Wed", "icon": "\U0001F527",
        "focus": "Prototyping & Robotics",
        "desc": "Hands-on prototyping and robotics — wiring, 3D printing, assembly and physical testing.",
        "scope": [("INT", "Robotics", ["Mechatronics", "Robot Software"]), ("INT", "Systems Engineering", None), ("DEX", "Fine Motor Control", None)],
    },
    {
        "key": "thu", "label": "Thu", "icon": "\U0001F4DC",
        "focus": "Chartered Engineer Progress",
        "desc": "CPD documentation, technical reporting and applied AI-in-engineering study.",
        "scope": [("WILL", "Persistence", None), ("INT", "Software Engineering", None), ("INT", "Computer Science", None)],
    },
    {
        "key": "fri", "label": "Fri", "icon": "\U0001F3E2",
        "focus": "Business & Industry Strategy",
        "desc": "Industry webinars, manufacturing research and business-model work.",
        "scope": [("INT", "Business", None)],
    },
    {
        "key": "sat", "label": "Sat", "icon": "✍️",
        "focus": "Story Development",
        "desc": "Backstories, plot, setting and lore — the creative-practice work behind the fiction.",
        "scope": [("SPIRIT", "Culture", None), ("SPIRIT", "Creativity", None), ("INT", "Creative Production", None)],
    },
    {
        "key": "sun", "label": "Sun", "icon": "\U0001F504",
        "focus": "Review & Planning",
        "desc": "Reflecting on the week and adjusting strategy for the one ahead.",
        "scope": [("DISC", "Time Management", None), ("SPIRIT", "Reflection", None)],
    },
]
DAY_BY_KEY: dict[str, dict[str, Any]] = {day["key"]: day for day in DAYS}

HOURS_MAX = 24  # sanity cap on a single logged session, not a design constraint


def _rnd_root() -> Path:
    configured = os.getenv("ZERO_GRAVITY_RND_ROOT") or current_app.config.get("ZERO_GRAVITY_RND_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(current_app.root_path).resolve().parent / "zeroGravity-rnd"


def _engine_modules():
    root = _rnd_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from learning.engine import xp as xp_engine, stats as stats_engine
    from operator_core.profile.progression import get_level_progress

    return xp_engine, stats_engine, get_level_progress


# ---------------------------------------------------------------------------
# Kept separate from _engine_modules() above (rather than folding into it)
# so the existing dashboard() call site doesn't need to change shape - only
# log_session() needs the event-ledger + distribution-receipt machinery.
# Same pattern journal/engine/service.py uses: emit an OperatorEvent, run it
# through DistributionService for an auditable receipt, then apply the
# receipt's own allocations - never a separately computed award - so the
# receipt and the actually-applied XP can never drift apart. This is what
# makes a logged Weekly Ops session show up in the Analytics Hub.
# ---------------------------------------------------------------------------
def _event_modules():
    root = _rnd_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from operator_core.events.models import OperatorEvent
    from operator_core.events.service import EventLedger
    from operator_core.distribution.service import DistributionService

    return OperatorEvent, EventLedger, DistributionService


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _skill_tree() -> dict[str, Any]:
    path = _rnd_root() / "operator_core" / "capabilities" / "skill_tree.json"
    return _load_json(path, {"stats": {}})


def _competencies() -> dict[str, Any]:
    path = _rnd_root() / "operator_core" / "capabilities" / "competencies.json"
    return _load_json(path, {"competencies": {}}).get("competencies", {})


def _learning_stats() -> dict[str, Any]:
    path = _rnd_root() / "operator_core" / "hubs" / "learning" / "stats" / "learning_stats.json"
    return _load_json(path, {"stats": {}})


def _log_file() -> Path:
    path = _rnd_root() / "operator_core" / "hubs" / "tasks" / "data" / "tasks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_log() -> list[dict[str, Any]]:
    data = _load_json(_log_file(), [])
    return data if isinstance(data, list) else []


def _save_log(entries: list[dict[str, Any]]) -> None:
    _log_file().write_text(json.dumps(entries, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Most subcategories are flat (Subcategory -> Capability directly), but a
# few in his tree (Robotics/Robot Software, e.g. "Robot Middleware" ->
# "ROS2") have an extra grouping layer in between. This walks through any
# depth of that grouping so nothing he's built out under it is silently
# hidden from the picker - the grouping name itself is dropped, the leaf
# capability names are what the picker shows.
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


# ---------------------------------------------------------------------------
# Catalog: for one day, walk the real skill tree under that day's scope and
# attach each capability's real current xp/level so the page can show a live
# preview without a round trip. Rebuilt on every request - the tree and
# competencies files are small and this stays correct even right after an
# XP award changes them.
# ---------------------------------------------------------------------------
def _catalog_for_day(day: dict[str, Any], tree: dict[str, Any], registry: dict[str, Any], get_level_progress) -> list[dict[str, Any]]:
    stats = tree.get("stats", {})
    catalog: list[dict[str, Any]] = []
    for stat, category, subcat_filter in day["scope"]:
        cat_node = stats.get(stat, {}).get("children", {}).get(category)
        if not isinstance(cat_node, dict):
            continue
        subcats: dict[str, list[dict[str, Any]]] = {}
        for sub_name, sub_node in cat_node.get("children", {}).items():
            if subcat_filter is not None and sub_name not in subcat_filter:
                continue
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
                    "xp_to_next_level": progress["xp_to_next_level"],
                    "next_level_xp": progress["next_level_xp"],
                })
            if caps:
                subcats[sub_name] = caps
        if subcats:
            catalog.append({"stat": stat, "category": category, "subcategories": subcats})
    return catalog


# ---------------------------------------------------------------------------
# Operator Stats panel: only the stats/categories this week's scope actually
# touches, derived from DAYS itself (never hand-typed) so it can't drift out
# of sync with the day scopes the way a duplicated list eventually would.
# "Level" -> "Overall", "Lv" -> "Ov" per his naming.
# ---------------------------------------------------------------------------
def _used_scope() -> dict[str, list[str]]:
    used: dict[str, list[str]] = {}
    for day in DAYS:
        for stat, category, _ in day["scope"]:
            bucket = used.setdefault(stat, [])
            if category not in bucket:
                bucket.append(category)
    return used


def _stats_panel(learning_stats: dict[str, Any]) -> list[dict[str, Any]]:
    stats = learning_stats.get("stats", {})
    used = _used_scope()
    panel = []
    for stat, categories in used.items():
        stat_node = stats.get(stat, {})
        stat_avg = float(stat_node.get("average_level", 0.0))
        rows = []
        for category in categories:
            cat_node = stat_node.get("children", {}).get(category, {})
            avg = float(cat_node.get("average_level", 0.0)) if isinstance(cat_node, dict) else 0.0
            whole = int(avg)
            pct = round((avg - whole) * 100, 1)
            rows.append({"category": category, "whole": whole, "pct": pct})
        stat_whole = int(stat_avg)
        stat_pct = round((stat_avg - stat_whole) * 100, 1)
        panel.append({"stat": stat, "overall_whole": stat_whole, "overall_pct": stat_pct, "categories": rows})
    return panel


def _resolve_competency_id(day: dict[str, Any], stat: str, category: str, subcategory: str, capability: str, tree: dict[str, Any]) -> str | None:
    """Re-derive the competency_id server-side from the submitted picks,
    validated against the day's own scope - never trust a posted id."""
    allowed = {(s, c) for s, c, _ in day["scope"]}
    if (stat, category) not in allowed:
        return None
    subcat_filter = next((f for s, c, f in day["scope"] if s == stat and c == category), None)
    if subcat_filter is not None and subcategory not in subcat_filter:
        return None
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


def get_tasks_dashboard_data(day_key: str = "mon", error: str | None = None, logged: str | None = None) -> dict[str, Any]:
    """Same context dashboard() renders with - pulled out so the HUD shell's
    live-data aggregator (modules/operator_hud.py) can reuse it exactly."""
    day = DAY_BY_KEY.get(day_key, DAYS[0])

    tree = _skill_tree()
    registry = _competencies()
    _, _, get_level_progress = _engine_modules()

    catalog = _catalog_for_day(day, tree, registry, get_level_progress)
    stats_panel = _stats_panel(_learning_stats())

    log = _load_log()
    day_log = [entry for entry in log if entry.get("day_key") == day["key"]]
    day_log.sort(key=lambda entry: entry.get("created_at", ""), reverse=True)

    return {
        "days": DAYS,
        "active_day": day,
        "catalog": catalog,
        "stats_panel": stats_panel,
        "day_log": day_log[:15],
        "error": error,
        "logged": logged,
    }


@bp.get("/")
def dashboard():
    day_key = request.args.get("day", "mon")
    return render_template(
        "workspaces/operator/tasks.html",
        **get_tasks_dashboard_data(day_key, error=request.args.get("error"), logged=request.args.get("logged")),
    )


@bp.post("/log")
def log_session():
    form = request.form
    day_key = form.get("day", "").strip()
    day = DAY_BY_KEY.get(day_key)
    stat = form.get("stat", "").strip()
    category = form.get("category", "").strip()
    subcategory = form.get("subcategory", "").strip()
    capability = form.get("capability", "").strip()
    hours_raw = form.get("hours", "").strip()

    def back(error: str | None = None, logged: str | None = None):
        # Redirects into the HUD shell (modules/operator_hud.py) rather than
        # this hub's own standalone page, so a real <form> POST from the HUD's
        # Tasks view lands back inside the SPA instead of kicking the user
        # out to a separately-styled page. operator_tasks.dashboard still
        # works fine on its own for direct/legacy links.
        return redirect(url_for("operator.dashboard", hud_view="tasks", day=day_key or "mon", error=error, logged=logged))

    if not day:
        return back(error="Unknown day.")
    if not (stat and category and subcategory and capability):
        return back(error="Pick a category, subcategory and capability before logging a session.")

    try:
        hours = float(hours_raw)
    except ValueError:
        return back(error="Hours needs to be a number.")
    if hours <= 0 or hours > HOURS_MAX:
        return back(error=f"Hours must be between 0 and {HOURS_MAX}.")

    tree = _skill_tree()
    competency_id = _resolve_competency_id(day, stat, category, subcategory, capability, tree)
    if not competency_id:
        return back(error="That pick doesn't match today's scope - refresh and try again.")

    xp_engine, stats_engine, get_level_progress = _engine_modules()
    OperatorEvent, EventLedger, DistributionService = _event_modules()

    registry_before = _competencies()
    xp_before = int(registry_before.get(competency_id, {}).get("xp", 0))
    level_before = get_level_progress(xp_before)["level"]

    xp_award = xp_engine.calculate_hourly_xp(hours)

    log_id = f"wo-{int(datetime.now(timezone.utc).timestamp() * 1000)}"
    occurred_at = datetime.now(timezone.utc).isoformat()

    ledger = EventLedger()
    event = ledger.append(OperatorEvent(
        event_type="task_session_logged",
        source="operator_core.tasks",
        payload={
            "log_id": log_id,
            "day_key": day_key,
            "stat": stat,
            "category": category,
            "subcategory": subcategory,
            "capability": capability,
            "competency_id": competency_id,
            "hours": hours,
            "base_xp": xp_award,
            "xp_targets": [{"competency_id": competency_id, "weight": 1.0}],
        },
        occurred_at=occurred_at,
        idempotency_key=f"task_session:{log_id}",
    ))
    receipt = DistributionService(ledger=ledger).distribute_event(event)

    # Apply XP from the receipt's own allocations, never the flat xp_award
    # computed above - guarantees the receipt and the actually-applied XP
    # can never drift apart (same pattern journal/engine/service.py uses).
    allocations = [
        {"competency_id": allocation.target_id, "xp": allocation.xp}
        for allocation in receipt.allocations
        if allocation.target_type == "competency"
    ]
    if allocations:
        stats_engine.update_operator_competencies(allocations)

    registry_after = _competencies()
    xp_after = int(registry_after.get(competency_id, {}).get("xp", 0))
    level_after = get_level_progress(xp_after)["level"]

    log = _load_log()
    log.append({
        "id": log_id,
        "created_at": occurred_at,
        "day_key": day_key,
        "stat": stat,
        "category": category,
        "subcategory": subcategory,
        "capability": capability,
        "competency_id": competency_id,
        "hours": hours,
        "xp": xp_award,
        "level_before": level_before,
        "level_after": level_after,
        "leveled_up": level_after > level_before,
        "event_id": event.event_id,
        "receipt_id": receipt.receipt_id,
    })
    _save_log(log)

    return back(logged="1")
