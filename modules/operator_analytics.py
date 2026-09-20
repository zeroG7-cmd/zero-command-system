"""Zero Command System - Operator Analytics Hub.

Cross-hub summary: pulls together the same numbers Fitness, Learning,
Journal, Tasks and Execution already produce and reconciles them into one
view - main stat overalls, category/capability leaderboards, an XP-over-time
graph per stat, and a combined recent-activity feed.

Read-only by design (no route here writes anything), so it stays
dependency-light like modules/operator.py/operator_fitness.py: everything is
read straight from the same JSON files those hubs already read/write, no
cross-repo Python imports needed.

Two different data sources feed this page, deliberately:
- Main stats / categories / capabilities (the "what level is X at" numbers)
  come from learning_stats.json, which already holds the recursive
  average_level rollup and per-capability xp/level - the same file
  modules/operator.py and modules/tasks.py already treat as the source of
  truth for those numbers. learning_stats.json's node_type for a leaf is
  "skill" (not "competency_reference" - that's skill_tree.json's schema,
  a different file with a different convention).
- The XP-over-time graph, the five hub-summary cards, and the recent-activity
  feed instead come from operator_core/distribution/receipts/*.json - the
  append-only, auditable record of every XP award and its per-stat/per-
  capability split, cross-referenced back to operator_events.jsonl for a
  human-readable label (habit name, track/unit title, journal title, ...).
  learning_stats.json only holds current totals, not a history of when XP
  landed or which hub it came from - the receipts are the only place that
  actually lives.

That second source has a known, real gap as of when this was built: Task
Hub (modules/tasks.py) and Execution Hub (modules/operator_execution.py)
both award XP by calling learning.engine.stats.update_operator_competencies()
directly and never create a distribution receipt for it, unlike Fitness,
Learning and Journal. So their hub-summary cards, the graph, and the
activity feed will all under-report those two hubs until that gets wired up
the same way the others already are. receipt_coverage below always reports
the real, current gap between receipt-covered xp and learning_stats.json's
total_xp rather than assuming full coverage, so this page says so instead
of silently misreporting.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, render_template, url_for

operator_analytics_bp = Blueprint("operator_analytics", __name__, url_prefix="/operator/analytics")

MAIN_STATS = ["CON", "INT", "STR", "DEX", "DISC", "WILL", "SPIRIT"]

# Local copy of the fitness habit labels from operator_fitness.py's
# HABIT_FIELDS - same "keep a local copy rather than import across modules"
# choice that file documents for its own copy of fitness/engine/config.py's
# HABITS. Only needed here to turn a habit key (fitness_habit_logged events
# only store the bare key, e.g. "pushups") back into a display label for
# the Recent Activity feed.
HABIT_LABELS = {
    "pushups": "Push-ups", "pullups": "Pull-ups", "situps": "Sit-ups",
    "squats": "Squats", "run_minutes": "Jog", "stretch_minutes": "Stretch / mobility",
}


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


def _iter_leaves(node: Any, name: str = ""):
    """Yield (name, node) for every 'skill' leaf beneath this learning_stats.json node,
    walking through any depth of intermediate category/subcategory grouping."""
    if not isinstance(node, dict):
        return
    if node.get("node_type") == "skill":
        yield name, node
        return
    children = node.get("children", {})
    if not isinstance(children, dict):
        return
    for child_name, child in children.items():
        yield from _iter_leaves(child, child_name)


def _category_rollups(stats: dict[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Per-stat full category list, and a flattened all-stats list. Each
    category carries its own average_level (read directly - learning_stats.json
    caches it at every node) plus a freshly-summed xp total (learning_stats.json
    only caches xp at leaf nodes, not at categories/subcategories)."""
    full: dict[str, list[dict[str, Any]]] = {}
    flat: list[dict[str, Any]] = []
    for stat in MAIN_STATS:
        stat_node = stats.get(stat, {})
        children = stat_node.get("children", {}) if isinstance(stat_node, dict) else {}
        rows = []
        for cat_name, cat_node in children.items():
            if not isinstance(cat_node, dict):
                continue
            leaves = list(_iter_leaves(cat_node))
            xp = sum(int(leaf.get("xp", 0)) for _, leaf in leaves)
            with_xp = sum(1 for _, leaf in leaves if int(leaf.get("xp", 0)) > 0)
            row = {
                "category": cat_name,
                "xp": xp,
                "average_level": float(cat_node.get("average_level", 0.0)),
                "leaf_count": len(leaves),
                "leaf_count_with_xp": with_xp,
            }
            rows.append(row)
            flat.append({**row, "stat": stat})
        full[stat] = rows
    return full, flat


def _top_capabilities(stats: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
    caps = []
    for stat in MAIN_STATS:
        for name, leaf in _iter_leaves(stats.get(stat, {})):
            xp = int(leaf.get("xp", 0))
            if xp <= 0:
                continue
            caps.append({
                "id": leaf.get("competency_id", ""),
                "name": name,
                "xp": xp,
                "level": int(leaf.get("level", 0)),
            })
    caps.sort(key=lambda c: c["xp"], reverse=True)
    return caps[:limit]


def _competency_names(stats: dict[str, Any]) -> dict[str, str]:
    names: dict[str, str] = {}
    for stat in MAIN_STATS:
        for name, leaf in _iter_leaves(stats.get(stat, {})):
            cid = leaf.get("competency_id")
            if cid:
                names[str(cid)] = name
    return names


def _events(root: Path) -> dict[str, dict[str, Any]]:
    path = root / "operator_core" / "events" / "operator_events.jsonl"
    if not path.exists():
        return {}
    events: dict[str, dict[str, Any]] = {}
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
    receipts_dir = root / "operator_core" / "distribution" / "receipts"
    if not receipts_dir.exists():
        return []
    out = []
    for path in receipts_dir.glob("*.json"):
        data = _load_json(path, None)
        if isinstance(data, dict) and data.get("created_at"):
            out.append(data)
    return out


def _stat_of_competency(competency_id: str) -> str | None:
    if not competency_id or "." not in competency_id:
        return None
    prefix = competency_id.split(".", 1)[0].upper()
    return prefix if prefix in MAIN_STATS else None


def _hub_of_event_type(event_type: str | None) -> str | None:
    if not event_type:
        return None
    if event_type.startswith("fitness_"):
        return "fitness"
    if event_type.startswith("learning_"):
        return "learning"
    if event_type.startswith("journal_"):
        return "journal"
    if event_type.startswith("task"):
        return "tasks"
    if event_type.startswith("execution_") or event_type.startswith("project_"):
        return "execution"
    return None


def _event_label(event: dict[str, Any] | None, source_event_type: str, competency_names: dict[str, str]) -> str:
    if event is None:
        return source_event_type.replace("_", " ").title() if source_event_type else "Activity"

    event_type = event.get("event_type", "")
    payload = event.get("payload", {}) or {}

    if event_type == "fitness_habit_logged":
        habit = str(payload.get("habit", ""))
        label = HABIT_LABELS.get(habit, habit.replace("_", " ").title() or "Habit")
        quantity = payload.get("quantity", "?")
        unit = payload.get("unit", "")
        return f"{label} — {quantity} {unit}".strip()

    if event_type == "fitness_gym_day_logged":
        return f"Gym day: {payload.get('focus') or payload.get('day') or 'Session'}"

    if event_type == "learning_completed":
        provider_record = payload.get("provider_record", {}) or {}
        track = payload.get("track_title") or provider_record.get("track", "")
        unit_title = payload.get("unit_title") or provider_record.get("unit_title", "")
        if track and unit_title:
            return f"{track} — {unit_title}"
        return track or unit_title or "Learning completion"

    if event_type == "journal_created":
        return str(payload.get("title", "Journal entry"))

    # generic fallback for anything else (e.g. a future Task Hub/Execution
    # Hub event) - name the capability/ies it touched
    targets = payload.get("xp_targets", [])
    names = []
    for target in targets:
        cid = str(target.get("competency_id") or target.get("target_id", ""))
        name = competency_names.get(cid)
        if name:
            names.append(name)
    if names:
        extra = f" +{len(names) - 2} more" if len(names) > 2 else ""
        return ", ".join(names[:2]) + extra
    return event_type.replace("_", " ").title() or "Activity"


def _effective_time(receipt: dict[str, Any], event: dict[str, Any] | None) -> str:
    """The real "when did this XP get earned" timestamp.

    A receipt's own created_at is when the RECEIPT was written, not when the
    underlying activity happened - for an imported/backfilled completion
    those can be far apart (e.g. a legacy_provider_import receipt rewritten
    today for a course finished in July still needs to plot in July). The
    source event's occurred_at is the ground truth when it's available;
    receipt.created_at is only a fallback for the rare receipt with no
    matching event on record.
    """
    if event and event.get("occurred_at"):
        return str(event["occurred_at"])
    return str(receipt.get("created_at", ""))


def _stat_timeseries_hub_summary_and_activity(
    receipts: list[dict[str, Any]],
    events: dict[str, dict[str, Any]],
    competency_names: dict[str, str],
    total_xp: int,
) -> tuple[dict[str, Any], dict[str, dict[str, int]], list[dict[str, Any]]]:
    # Pair each receipt with its event (if any) and its effective time, then
    # sort by THAT - not receipt.created_at - so the graph and activity feed
    # read chronologically by when the work actually happened.
    enriched = []
    for receipt in receipts:
        event = events.get(receipt.get("source_event_id", ""))
        enriched.append((_effective_time(receipt, event), receipt, event))
    enriched.sort(key=lambda item: item[0])

    running = {stat: 0 for stat in MAIN_STATS}
    points: list[dict[str, Any]] = []
    xp_covered = 0
    hub_summary = {hub: {"count": 0, "xp": 0} for hub in ("fitness", "learning", "journal", "tasks", "execution")}
    activity: list[dict[str, Any]] = []

    for effective_time, receipt, event in enriched:
        receipt_xp = int(receipt.get("total_xp", 0))
        xp_covered += receipt_xp
        event_type = event.get("event_type") if event else receipt.get("source_event_type")
        hub = _hub_of_event_type(event_type)

        if hub in hub_summary:
            hub_summary[hub]["count"] += 1
            hub_summary[hub]["xp"] += receipt_xp

        deltas: dict[str, int] = {}
        for alloc in receipt.get("allocations", []):
            stat = _stat_of_competency(str(alloc.get("target_id", "")))
            if stat is None:
                continue
            deltas[stat] = deltas.get(stat, 0) + int(alloc.get("xp", 0))
        for stat, delta in deltas.items():
            if delta == 0:
                continue
            running[stat] += delta
            points.append({"t": effective_time, "stat": stat, "cum": running[stat]})

        activity.append({
            "hub": hub or "learning",
            "label": _event_label(event, receipt.get("source_event_type", ""), competency_names),
            "xp": receipt_xp,
            "occurred_at": effective_time,
            "event_type": event_type or "",
        })

    activity.sort(key=lambda item: item["occurred_at"], reverse=True)

    coverage = {
        "receipts_count": len(receipts),
        "allocations_count": sum(len(r.get("allocations", [])) for r in receipts),
        "xp_covered": xp_covered,
        "xp_total_reconciled": int(total_xp),
        "earliest": enriched[0][0] if enriched else None,
        "latest": enriched[-1][0] if enriched else None,
        "full_coverage": xp_covered == int(total_xp),
    }
    timeseries = {"receipt_coverage": coverage, "final_cumulative": running, "points": points}
    return timeseries, hub_summary, activity[:25]


def get_analytics_dashboard_data() -> dict[str, Any]:
    root = _rnd_root()
    stats_doc = _load_json(root / "operator_core" / "hubs" / "learning" / "stats" / "learning_stats.json", None)
    if stats_doc is None:
        raise FileNotFoundError("learning_stats.json not found - run the stats sync first.")
    stats = stats_doc.get("stats", {})

    progression = {
        "level": int(stats_doc.get("level", 0)),
        "total_xp": int(stats_doc.get("total_xp", 0)),
        "next_level_xp": int(stats_doc.get("next_level_xp", 100)),
        "xp_to_next_level": int(stats_doc.get("xp_to_next_level", 0)),
        "progress_percentage": float(stats_doc.get("level_progress", 0.0)),
    }

    main_stats: dict[str, dict[str, Any]] = {}
    for stat in MAIN_STATS:
        node = stats.get(stat, {})
        leaves = list(_iter_leaves(node))
        main_stats[stat] = {
            "xp": sum(int(leaf.get("xp", 0)) for _, leaf in leaves),
            "average_level": float(node.get("average_level", 0.0)) if isinstance(node, dict) else 0.0,
        }

    full_category_rollup, flat_categories = _category_rollups(stats)
    category_rollup = sorted(flat_categories, key=lambda c: c["xp"], reverse=True)[:10]
    top_caps = _top_capabilities(stats)
    competency_names = _competency_names(stats)

    events = _events(root)
    receipts = _receipts(root)
    stat_timeseries, hub_summary, timeline = _stat_timeseries_hub_summary_and_activity(
        receipts, events, competency_names, progression["total_xp"],
    )

    return {
        "progression": progression,
        "stats": main_stats,
        "hub_summary": hub_summary,
        "timeline": timeline,
        "top_caps": top_caps,
        "category_rollup": category_rollup,
        "full_category_rollup": full_category_rollup,
        "stat_timeseries": stat_timeseries,
    }


@operator_analytics_bp.get("/")
def dashboard():
    try:
        data = get_analytics_dashboard_data()
        error = None
    except (FileNotFoundError, ValueError, OSError) as exc:
        data = None
        error = str(exc)

    return render_template(
        "workspaces/operator/analytics.html",
        data=data,
        analytics_error=error,
        hub_urls={
            "fitness": url_for("operator_fitness.dashboard"),
            "learning": url_for("operator_learning.dashboard"),
            "journal": url_for("operator_journal.dashboard"),
            "tasks": url_for("operator_tasks.dashboard"),
            "execution": url_for("operator_execution.dashboard"),
        },
    )
