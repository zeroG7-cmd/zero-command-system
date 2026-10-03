"""Zero Command System — Operator Learning Hub v2.0."""

from __future__ import annotations

import io
import json
import math
import os
import runpy
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from werkzeug.utils import secure_filename

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


def _group_tracks(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for card in cards:
        parts = [part.strip() for part in card.get("knowledge_path", "").split(">") if part.strip()]
        stat = parts[0] if parts else "Unassigned"
        domain = parts[1] if len(parts) > 1 else "General"
        category = parts[-1] if len(parts) > 2 else card.get("skill") or "General"
        key = (stat, domain)
        group = grouped.setdefault(key, {
            "stat": stat,
            "domain": domain,
            "track_count": 0,
            "completed_units": 0,
            "total_units": 0,
            "categories": {},
        })
        group["track_count"] += 1
        group["completed_units"] += card["completed_count"]
        group["total_units"] += card["unit_count"]
        group["categories"].setdefault(category, []).append(card)

    result = []
    for group in grouped.values():
        group["percentage"] = round(
            (group["completed_units"] / group["total_units"]) * 100, 1
        ) if group["total_units"] else 0.0
        group["categories"] = [
            {"name": name, "tracks": sorted(tracks, key=lambda item: item["title"].lower())}
            for name, tracks in sorted(group["categories"].items())
        ]
        result.append(group)
    return sorted(result, key=lambda item: (item["stat"], item["domain"]))


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
    status_counts: dict[str, int] = {}
    for card in cards:
        status = str(card.get("status", "In Progress"))
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "tracks": cards,
        "library_groups": _group_tracks(cards),
        "status_counts": status_counts,
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


def _track_by_id(track_id: str) -> Path:
    for path in _track_paths():
        if _load_json(path / "metadata.json").get("id", path.name) == track_id:
            return path
    raise ValueError(f"Learning track not found: {track_id}")


def _current_unit_context(track: Path) -> dict[str, Any]:
    """Resolve the track's current unit to real paths, for the notebook API.

    Mirrors _evidence()'s current_unit selection so the notebook always
    edits the same unit the hub page itself considers "current" - never a
    client-supplied index, which would let a stale page write to the wrong
    unit after someone else (or a Complete Current Unit click) advances it.
    """
    metadata = _load_json(track / "metadata.json")
    progress = _load_json(track / "progress.json")
    units = metadata.get("units", [])
    if not units:
        raise ValueError("This track has no units yet.")

    index = max(0, min(int(progress.get("current_unit_index", 0)), len(units) - 1))
    unit = units[index]
    unit_relative = str(unit.get("path", "")).strip()
    if not unit_relative:
        raise ValueError("This unit has no on-disk path.")

    unit_path = (track / unit_relative).resolve()
    track_resolved = track.resolve()
    if track_resolved not in unit_path.parents and unit_path != track_resolved:
        raise ValueError("Refusing to resolve a unit path outside its track.")

    return {
        "track": track,
        "metadata": metadata,
        "progress": progress,
        "unit": unit,
        "unit_index": index,
        "unit_path": unit_path,
    }


def _notebook_targets(metadata: dict[str, Any]) -> dict[str, Path | None]:
    """Map the track's real evidence_requirements onto the three notebook
    fields, instead of hardcoding filenames - different tracks use different
    real files here (manifest imports use notes.md/reflection.md/evidence/
    practical_evidence.md; the manually-added 30 Days of Python course uses
    evidence/terminal_output.txt instead), and this reads whichever the
    track's own metadata actually declares."""
    notes_rel = reflection_rel = evidence_rel = None
    for requirement in metadata.get("evidence_requirements", []):
        rel = str(requirement.get("path", "")).strip()
        if not rel:
            continue
        if rel == "notes.md":
            notes_rel = rel
        elif rel == "reflection.md":
            reflection_rel = rel
        elif rel.startswith("evidence/") and evidence_rel is None:
            evidence_rel = rel
    return {"notes": notes_rel, "reflection": reflection_rel, "evidence": evidence_rel}


def _read_text(path: Path | None) -> str:
    if not path or not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


@operator_learning_bp.get("/tracks/<track_id>/notebook")
def notebook(track_id: str):
    try:
        track = _track_by_id(track_id)
        context = _current_unit_context(track)
        metadata, unit, unit_path = context["metadata"], context["unit"], context["unit_path"]
        targets = _notebook_targets(metadata)

        evidence_dir = unit_path / "evidence"
        evidence_text_path = unit_path / targets["evidence"] if targets["evidence"] else None
        existing_files = []
        if evidence_dir.is_dir():
            for entry in sorted(evidence_dir.iterdir()):
                if entry.is_file() and entry != evidence_text_path:
                    existing_files.append(entry.name)

        return jsonify(
            {
                "track_id": track_id,
                "track_title": metadata.get("title", track.name),
                "unit_title": unit.get("title", ""),
                "unit_index": context["unit_index"],
                "unit_count": len(metadata.get("units", [])),
                "notes": _read_text(unit_path / targets["notes"]) if targets["notes"] else None,
                "reflection": _read_text(unit_path / targets["reflection"]) if targets["reflection"] else None,
                "evidence_text": _read_text(evidence_text_path) if evidence_text_path else None,
                "evidence_files": existing_files,
                "reward_preview": _reward_preview(metadata, unit),
            }
        )
    except Exception as error:
        return jsonify({"error": str(error)}), 400


@operator_learning_bp.post("/tracks/<track_id>/notebook")
def save_notebook(track_id: str):
    try:
        track = _track_by_id(track_id)
        context = _current_unit_context(track)
        metadata, unit_path = context["metadata"], context["unit_path"]
        targets = _notebook_targets(metadata)
        payload = request.get_json(force=True, silent=True) or {}

        saved = []
        if targets["notes"] and "notes" in payload:
            (unit_path / targets["notes"]).write_text(str(payload["notes"]), encoding="utf-8")
            saved.append(targets["notes"])
        if targets["reflection"] and "reflection" in payload:
            (unit_path / targets["reflection"]).write_text(str(payload["reflection"]), encoding="utf-8")
            saved.append(targets["reflection"])
        if targets["evidence"] and "evidence_text" in payload:
            path = unit_path / targets["evidence"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(payload["evidence_text"]), encoding="utf-8")
            saved.append(targets["evidence"])

        return jsonify({"saved": saved})
    except Exception as error:
        return jsonify({"error": str(error)}), 400


@operator_learning_bp.post("/tracks/<track_id>/evidence")
def upload_evidence(track_id: str):
    try:
        track = _track_by_id(track_id)
        context = _current_unit_context(track)
        unit_path = context["unit_path"]

        uploaded = request.files.get("file")
        if not uploaded or not uploaded.filename:
            return jsonify({"error": "No file supplied."}), 400
        safe_name = secure_filename(uploaded.filename)
        if not safe_name:
            return jsonify({"error": "Invalid filename."}), 400

        evidence_dir = unit_path / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        uploaded.save(evidence_dir / safe_name)
        return jsonify({"filename": safe_name})
    except Exception as error:
        return jsonify({"error": str(error)}), 400


@operator_learning_bp.get("/tracks/<track_id>/evidence/<path:filename>")
def serve_evidence(track_id: str, filename: str):
    track = _track_by_id(track_id)
    context = _current_unit_context(track)
    evidence_dir = (context["unit_path"] / "evidence").resolve()
    target = (evidence_dir / filename).resolve()
    if evidence_dir not in target.parents or not target.is_file():
        abort(404)
    return send_from_directory(evidence_dir, filename)


def _run_in_process(script: Path, stdin: str, args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Frozen-build fallback for _run().

    Once packaged with PyInstaller, sys.executable is this app's own
    zero-command-backend.exe, not a real Python interpreter - so
    subprocess.run([sys.executable, script, ...]) doesn't run the engine
    script at all, it tries to launch a second copy of the whole backend
    with the script's path as a stray argument. That second copy fights
    the running one for port 5000 and never exits cleanly, which is why
    this hung for the full 120s timeout instead of failing fast.

    These engine scripts are plain interactive CLI tools (argv + stdin
    prompts + stdout/stderr), so instead of shelling out to a second
    process, run them directly inside this already-running interpreter via
    runpy - same script, same stdin/argv contract, no second process
    needed. Safe to swap sys.stdin/stdout/stderr/argv/cwd/path globally like
    this because app.py's app.run() never sets threaded=True, so Flask's
    dev server only ever handles one request at a time - there is no
    concurrent request that could observe the swap.
    """
    old_argv = sys.argv
    old_cwd = os.getcwd()
    old_stdin, old_stdout, old_stderr = sys.stdin, sys.stdout, sys.stderr
    old_path = list(sys.path)
    stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
    returncode = 0
    try:
        os.chdir(cwd)
        sys.argv = [str(script), *args]
        sys.stdin = io.StringIO(stdin)
        sys.stdout = stdout_buf
        sys.stderr = stderr_buf
        # `python script.py` puts the script's own directory on sys.path[0]
        # automatically - runpy.run_path() does not, which is exactly why
        # these engine scripts' bare sibling imports (e.g. import_manifest.py's
        # `from concepts import ...`, learning/engine/stats.py's own `from
        # level import ...`) work when launched as a real subprocess but
        # fail with a ModuleNotFoundError run this way without doing it
        # ourselves first.
        sys.path.insert(0, str(script.parent))
        try:
            runpy.run_path(str(script), run_name="__main__")
        except SystemExit as exc:
            returncode = 0 if exc.code in (None, 0) else 1
        except Exception:
            traceback.print_exc(file=stderr_buf)
            returncode = 1
    finally:
        sys.argv = old_argv
        os.chdir(old_cwd)
        sys.stdin, sys.stdout, sys.stderr = old_stdin, old_stdout, old_stderr
        sys.path[:] = old_path

    return subprocess.CompletedProcess(
        args=[str(script), *args],
        returncode=returncode,
        stdout=stdout_buf.getvalue(),
        stderr=stderr_buf.getvalue(),
    )


def _run(script_name: str, stdin: str = "", args: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    root = _rnd_root()
    script = root / "learning" / "engine" / script_name
    if not script.exists():
        raise FileNotFoundError(f"Learning engine script not found: {script}")

    if getattr(sys, "frozen", False):
        return _run_in_process(script, stdin, args or [], root)

    return subprocess.run(
        [sys.executable, str(script), *(args or [])],
        input=stdin,
        text=True,
        capture_output=True,
        cwd=str(root),
        timeout=120,
        check=False,
    )


def _receipts_dir() -> Path:
    return _rnd_root() / "operator_core" / "events" / "receipts"


def _write_completion_receipt(
    track_id: str,
    metadata: dict[str, Any],
    completed_unit: dict[str, Any],
    reward: dict[str, Any],
    next_unit_title: str | None,
) -> None:
    """Drop a lightweight 'just happened' receipt for the toast feed
    learning_receipts.js polls (/api/learning/receipts/latest in
    learning_events.py, which just reads the newest file under
    operator_core/events/receipts/).

    This is deliberately separate from the formal DistributionReceipt ledger
    under operator_core/distribution/ (operator_analytics.py's _receipts())
    - that one is the source-of-truth XP accounting trail and tracker.py's
    completion path already reconciles into it. This file only exists to
    make the completion toast fire; it's never read for XP math.

    Without this, tracker.py-driven completions (unlike the Boot.dev live
    bridge, which already writes here) never produce a toast at all - the
    gap this closes was found via a real completion through the new
    notebook "Mark Unit Complete" flow producing no notification.
    """
    now = datetime.now(timezone.utc)
    unit_slug = str(completed_unit.get("path", "unit")).strip("/").replace("/", "_") or "unit"
    filename = f"{now.strftime('%Y%m%d_%H%M%S')}_learning_{track_id}_{unit_slug}.json"

    payload = {
        "event_id": f"learning:{track_id}:{completed_unit.get('path', unit_slug)}",
        "provider": "Learning Hub",
        "resource_id": track_id,
        "track": metadata.get("title", track_id),
        "chapter": completed_unit.get("title", ""),
        "unit_id": unit_slug,
        "unit_title": completed_unit.get("title", ""),
        "xp": reward.get("total_xp", 0),
        "competency_distribution": [
            {
                "competency_id": item["competency_id"],
                "weight": item["weight_percentage"] / 100,
                "xp": item["xp"],
            }
            for item in reward.get("items", [])
        ],
        "next_unit": next_unit_title,
        "status": "completed",
        "verification": "notebook_mark_complete",
        "mapping_confidence": "high",
        "processed_at": now.isoformat(),
    }

    receipts_dir = _receipts_dir()
    receipts_dir.mkdir(parents=True, exist_ok=True)
    (receipts_dir / filename).write_text(json.dumps(payload, indent=2), encoding="utf-8")


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
    # Best-effort pre-capture of what's about to be completed, so a receipt
    # can be written afterward - failures here must never block the actual
    # completion below, so they're swallowed rather than surfaced.
    track = metadata = completed_unit = reward = context = None
    before_progress: dict[str, Any] = {}
    try:
        track = _track_by_id(track_id)
        before_progress = _load_json(track / "progress.json")
        context = _current_unit_context(track)
        metadata, completed_unit = context["metadata"], context["unit"]
        reward = _reward_preview(metadata, completed_unit)
    except Exception:
        pass

    try:
        result = _run("tracker.py", f"{_selection(track_id)}\n")
        output = (result.stdout + "\n" + result.stderr).strip()
    except Exception as error:
        output = f"LEARNING ENGINE ERROR\n{error}"

    if track is not None and completed_unit is not None and reward is not None:
        try:
            after_progress = _load_json(track / "progress.json")
            advanced = int(after_progress.get("total_xp", 0)) > int(
                before_progress.get("total_xp", 0)
            ) or len(after_progress.get("completed_units", [])) > len(
                before_progress.get("completed_units", [])
            )
            if advanced:
                units = metadata.get("units", [])
                new_index = max(0, min(int(after_progress.get("current_unit_index", 0)), len(units) - 1))
                next_unit_title = (
                    units[new_index].get("title")
                    if units and new_index != context["unit_index"]
                    else None
                )
                _write_completion_receipt(track_id, metadata, completed_unit, reward, next_unit_title)
        except Exception:
            pass  # the receipt is a notification side-channel, never worth failing the request over

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
