"""Zero Command System - Operator Flight Log Hub.

Real and simulated flight practice logging, tagged against the Aviation
branch of the real skill tree (INT > Aviation - Flight Theory, Navigation,
Meteorology, Mission Planning, Piloting, FPV Operations, BVLOS, Autonomy).

This is its own hub, not a third activity_type on Execution Hub. Execution
Hub's own docstring (operator_core/execution/service.py) already explains
why: it used to support a broader set of activity types including
"practice", and that was deliberately narrowed back down because practice
is frequent and varies in length - it doesn't fit a flat, scope-sized,
one-off completion record. A flight is exactly that kind of practice, so
it gets duration-based XP (learning.engine.xp.calculate_hourly_xp(), the
same rate Task Hub uses for logged hours) instead of Execution Hub's flat
small/medium/large.

It also isn't just Task Hub with an extra field, though: Task Hub scopes
each weekday to a fixed slice of the tree (Aviation only opens up on
Tuesdays), but a flight happens whenever it happens. And kind
("real"/"simulated") is a first-class field on the record, not something
inferred from a title.

Evidence links to raw footage in the zeroGravity media folder
(ZERO_GRAVITY_MEDIA_ROOT, same override convention as ZERO_GRAVITY_RND_ROOT
elsewhere in this file). A flight's evidence path is resolved as
Flights/<Real|Simulated>/<aircraft>/raw/<filename> under that root and
streamed back through the /media/<path> route below with Range support,
so the dashboard can embed it as a real, scrubbable <video> instead of a
bare link.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

from flask import Blueprint, abort, current_app, jsonify, render_template, request, send_from_directory

bp = Blueprint("operator_flights", __name__, url_prefix="/operator/flights")

AVIATION_CATEGORY = "Aviation"
AVIATION_STAT = "INT"

# Video-ish extensions the dashboard will embed inline as <video> rather
# than just link to. Anything else in evidence still resolves and streams
# fine through /media/<path>, it just isn't auto-embedded.
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


def _rnd_root() -> Path:
    env = os.getenv("ZERO_GRAVITY_RND_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    configured = current_app.config.get("ZERO_GRAVITY_RND_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(current_app.root_path).resolve().parent / "zeroGravity-rnd"


def _media_root() -> Path:
    env = os.getenv("ZERO_GRAVITY_MEDIA_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    configured = current_app.config.get("ZERO_GRAVITY_MEDIA_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(current_app.root_path).resolve().parent / "zeroGravity-media"


def _engine_modules():
    root = _rnd_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from learning.engine import xp as xp_engine, stats as stats_engine
    from operator_core.profile.progression import get_level_progress
    from operator_core.flights import service as flight_service

    return xp_engine, stats_engine, get_level_progress, flight_service


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


def _competency_registry() -> dict[str, Any]:
    path = _rnd_root() / "operator_core" / "capabilities" / "competencies.json"
    data = _load_json(path, {"competencies": {}})
    entries = data.get("competencies", data) if isinstance(data, dict) else data
    if isinstance(entries, list):
        return {str(item.get("id")): item for item in entries}
    return entries


# Same "walk through any grouping depth" helper every other hub module
# keeps its own local copy of (tasks.py, operator_execution.py) - most
# subcategories are flat, a few have an extra layer in between.
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


def _aviation_catalog(tree: dict[str, Any], registry: dict[str, Any], get_level_progress) -> dict[str, list[dict[str, Any]]]:
    """Subcategory -> capability list, scoped to INT > Aviation only - a
    flight only ever trains Aviation skills, so unlike Execution Hub's
    full-tree catalog this never needs a Stat/Category picker at all.
    """
    aviation = (
        tree.get("stats", {})
        .get(AVIATION_STAT, {})
        .get("children", {})
        .get(AVIATION_CATEGORY, {})
    )
    subcats: dict[str, list[dict[str, Any]]] = {}
    if not isinstance(aviation, dict):
        return subcats
    for sub_name, sub_node in aviation.get("children", {}).items():
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
    return subcats


def _resolve_capability(subcategory: str, capability: str, tree: dict[str, Any]) -> str | None:
    """Re-derive the competency_id server-side from the picked subcategory
    and capability name, scoped to Aviation - never trust a posted id."""
    sub_node = (
        tree.get("stats", {})
        .get(AVIATION_STAT, {})
        .get("children", {})
        .get(AVIATION_CATEGORY, {})
        .get("children", {})
        .get(subcategory, {})
    )
    if not isinstance(sub_node, dict):
        return None
    leaf = _leaf_capabilities(sub_node).get(capability)
    if not leaf:
        return None
    return str(leaf.get("competency_id", "")) or None


# ---------------------------------------------------------------------------
# Aircraft folders, scanned live from the media root - Flights/Real/<name>
# and Flights/Simulated/<name> - so a new drone or sim platform just needs
# a folder made for it and it shows up here on its own, same "walk the real
# thing, never hand-type a duplicate list" principle _catalog_for_day() in
# tasks.py already follows for the skill tree.
# ---------------------------------------------------------------------------
def _aircraft_options() -> dict[str, list[str]]:
    root = _media_root() / "Flights"
    options: dict[str, list[str]] = {"real": [], "simulated": []}
    if not root.exists():
        return options
    kind_dirs = {"real": root / "Real", "simulated": root / "Simulated"}
    for kind, kind_dir in kind_dirs.items():
        if not kind_dir.is_dir():
            continue
        options[kind] = sorted(p.name for p in kind_dir.iterdir() if p.is_dir())
    return options


def _existing_evidence_files(kind: str, aircraft: str) -> list[str]:
    """Filenames already sitting in <aircraft>/raw for the picked kind -
    fed to the form as a datalist so logging a flight you already recorded
    is picking a filename, not retyping one."""
    if kind not in {"real", "simulated"} or not aircraft:
        return []
    kind_folder = "Real" if kind == "real" else "Simulated"
    raw_dir = _media_root() / "Flights" / kind_folder / aircraft / "raw"
    if not raw_dir.is_dir():
        return []
    return sorted(p.name for p in raw_dir.iterdir() if p.is_file())


def _evidence_relpath(kind: str, aircraft: str, filename: str) -> str:
    kind_folder = "Real" if kind == "real" else "Simulated"
    return f"Flights/{kind_folder}/{aircraft}/raw/{filename}"


@bp.get("/")
def dashboard():
    xp_engine, stats_engine, get_level_progress, flight_service = _engine_modules()
    tree = _skill_tree()
    registry = _competency_registry()
    competency_names = {cid: str(rec.get("name", cid)) for cid, rec in registry.items()}
    aircraft = _aircraft_options()

    records = flight_service.list_flights(30)
    # Attach the /media URL + whether it's embeddable video for each
    # evidence entry so the template doesn't need to know the routing.
    for record in records:
        record["evidence_links"] = [
            {
                "path": path,
                "url": f"/operator/flights/media/{path}",
                "is_video": Path(path).suffix.lower() in VIDEO_EXTENSIONS,
            }
            for path in record.get("evidence", [])
        ]

    return render_template(
        "workspaces/operator/flights.html",
        catalog=_aviation_catalog(tree, registry, get_level_progress),
        aircraft=aircraft,
        hourly_xp_rate=xp_engine.HOURLY_XP_RATE,
        summary=flight_service.flight_summary(),
        records=records,
        competency_names=competency_names,
        today=date.today().isoformat(),
        error=None,
    )


@bp.get("/evidence-files")
def evidence_files():
    """Existing filenames under <aircraft>/raw for the given kind - used to
    populate the evidence datalist client-side after the aircraft picker
    changes, without a full page reload."""
    kind = request.args.get("kind", "")
    aircraft = request.args.get("aircraft", "")
    return jsonify({"files": _existing_evidence_files(kind, aircraft)})


@bp.post("/api")
def create():
    xp_engine, stats_engine, get_level_progress, flight_service = _engine_modules()
    payload = request.get_json(silent=True) or {}

    kind = str(payload.get("kind", "")).strip().lower()
    aircraft = str(payload.get("aircraft", "")).strip()
    picks = payload.get("capabilities", [])
    if not isinstance(picks, list):
        picks = []

    if kind not in flight_service.VALID_KINDS:
        return jsonify({"error": f"kind must be one of: {', '.join(sorted(flight_service.VALID_KINDS))}"}), 400
    if not aircraft:
        return jsonify({"error": "aircraft is required"}), 400

    tree = _skill_tree()
    resolved: list[str] = []
    for pick in picks:
        if not isinstance(pick, dict):
            continue
        competency_id = _resolve_capability(str(pick.get("subcategory", "")), str(pick.get("capability", "")), tree)
        if competency_id and competency_id not in resolved:
            resolved.append(competency_id)

    if not resolved:
        return jsonify({"error": "no valid capabilities were resolved - refresh and try again"}), 400

    try:
        duration_minutes = float(payload.get("duration_minutes", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "duration_minutes must be a number"}), 400

    # Evidence: a bare filename from the client, resolved here against the
    # real media root and checked to actually exist - never trust a client
    # path straight through, and don't silently accept a typo'd filename.
    evidence_filename = str(payload.get("evidence_filename", "")).strip()
    evidence: list[str] = []
    if evidence_filename:
        kind_folder = "Real" if kind == "real" else "Simulated"
        expected = _media_root() / "Flights" / kind_folder / aircraft / "raw" / evidence_filename
        if not expected.is_file():
            return jsonify({
                "error": f"Couldn't find \"{evidence_filename}\" under Flights/{kind_folder}/{aircraft}/raw - "
                         f"check the filename (or leave evidence blank and add it later)."
            }), 400
        evidence = [_evidence_relpath(kind, aircraft, evidence_filename)]

    total_xp = xp_engine.calculate_hourly_xp(duration_minutes / 60.0)
    xp_awards = xp_engine.distribute_xp(total_xp, [{"competency_id": cid, "weight": 1.0} for cid in resolved])

    try:
        record = flight_service.build_record({
            "kind": kind,
            "aircraft": aircraft,
            "date": str(payload.get("date", "")).strip(),
            "duration_minutes": duration_minutes,
            "capabilities": resolved,
            "xp_total": total_xp,
            "xp_awards": xp_awards,
            "evidence": evidence,
            "notes": payload.get("notes", ""),
            "source": "zero_command",
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    existing = flight_service.find_by_fingerprint(record["fingerprint"])
    if existing:
        return jsonify({**existing, "duplicate": True}), 200

    # Same event-ledger + distribution-receipt pattern every other hub
    # routes XP through, so a flight shows up in Analytics like anything
    # else and the applied XP can never drift from the receipt.
    OperatorEvent, EventLedger, DistributionService = _event_modules()
    ledger = EventLedger()
    event = ledger.append(OperatorEvent(
        event_type="flight_logged",
        source="operator_core.flights",
        payload={
            "kind": kind,
            "aircraft": aircraft,
            "date": record["date"],
            "duration_minutes": duration_minutes,
            "capabilities": resolved,
            "evidence": evidence,
            "notes": record.get("notes", ""),
            "base_xp": total_xp,
            "xp_targets": [{"competency_id": cid, "weight": 1.0} for cid in resolved],
        },
        idempotency_key=f"flight:{record['fingerprint']}",
    ))
    receipt = DistributionService(ledger=ledger).distribute_event(event)

    allocations = [
        {"competency_id": allocation.target_id, "xp": allocation.xp}
        for allocation in receipt.allocations
        if allocation.target_type == "competency"
    ]
    if allocations:
        stats_engine.update_operator_competencies(allocations)

    record["event_id"] = event.event_id
    record["receipt_id"] = receipt.receipt_id
    record = flight_service.persist_flight(record)

    return jsonify(record), 201


@bp.get("/media/<path:relpath>")
def media(relpath: str):
    """Stream a file out of the zeroGravity media folder for inline
    playback. send_from_directory + conditional=True gives real Range
    support (so a <video> can scrub), and resolving + containment-checking
    the path before serving anything keeps this from ever walking outside
    the configured media root, however the path arrives.
    """
    root = _media_root()
    try:
        target = (root / relpath).resolve()
        target.relative_to(root.resolve())
    except (ValueError, RuntimeError):
        abort(404)
    if not target.is_file():
        abort(404)
    return send_from_directory(root, relpath, conditional=True)
