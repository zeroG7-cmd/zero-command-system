"""Zero Command System — Journal / Reflection Hub.

Thin Flask wrapper around zeroGravity-rnd's journal.engine package. Unlike
operator_fitness.py/operator_learning.py (which shell out to the engine's
CLI scripts), this imports the journal package directly — same choice
operator_execution.py makes for operator_core.execution.service — because
journal.engine is a proper importable package (has __init__.py throughout,
uses absolute package imports), not a collection of standalone CLI scripts.

Design choice made after walking the user through the CLI examples in
journal/README.md: they found the raw --base-xp/--target TYPE:ID:WEIGHT/
--evidence TYPE:REFERENCE:LABEL syntax genuinely confusing (colon-separated
codes, competency IDs you'd have to already know). This page keeps the
"no friction by default" path from journal/engine/xp_defaults.py front and
center — pick entry type(s), get the automatic XP, done — and folds the
manual override into one optional "give this entry its own XP" toggle that
never asks for a competency ID or colon syntax: it reuses the same
type-driven target split, just lets the user raise the XP number and
attach a plain-text evidence note when they want to make a deliberate,
evidenced claim instead of the automatic amount.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, redirect, render_template, request, url_for

operator_journal_bp = Blueprint("operator_journal", __name__, url_prefix="/operator/journal")

# Friendly labels for the entry types defined in journal/engine/models.py's
# ALLOWED_ENTRY_TYPES. Kept as a local copy rather than imported, same
# reasoning operator_fitness.py gives for its own HABIT_FIELDS copy.
TYPE_LABELS: dict[str, str] = {
    "reflection": "Reflection",
    "insight": "Insight",
    "epiphany": "Epiphany",
    "technical": "Technical",
    "business": "Business",
    "test_log": "Test Log",
    "learning": "Learning",
    "planning": "Planning",
    "spiritual": "Spiritual",
    "creative": "Creative",
    "decision": "Decision",
    "problem": "Problem",
    "personal": "Personal",
}


def _rnd_root() -> Path:
    env = os.getenv("ZERO_GRAVITY_RND_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    configured = current_app.config.get("ZERO_GRAVITY_RND_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(current_app.root_path).resolve().parent / "zeroGravity-rnd"


def _journal_module():
    root = _rnd_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from journal.engine import models, service, xp_defaults

    return models, service, xp_defaults


def _competencies() -> dict[str, Any]:
    import json

    path = _rnd_root() / "operator_core" / "capabilities" / "competencies.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("competencies", {})


def _stat_of(competency_id: str) -> str:
    return competency_id.split(".", 1)[0].upper()


def _resolve_target_names(targets: list[dict[str, Any]], registry: dict[str, Any]) -> list[dict[str, Any]]:
    resolved = []
    for target in targets:
        competency_id = str(target.get("competency_id", ""))
        competency = registry.get(competency_id, {})
        resolved.append(
            {
                "competency_id": competency_id,
                "name": competency.get("name", competency_id),
                "stat": _stat_of(competency_id),
                "weight": float(target.get("weight", 0)),
            }
        )
    return resolved


def _type_catalog() -> dict[str, dict[str, Any]]:
    """For each entry type, what it earns and where it goes by default.

    Powers both the server-rendered hints under each checkbox and the
    client-side live preview (as a JSON blob) when more than one type is
    picked at once - the exact question the user asked ("would this get
    distributed to two things?").
    """
    _, _, xp_defaults = _journal_module()
    registry = _competencies()
    catalog: dict[str, dict[str, Any]] = {}
    for entry_type, label in TYPE_LABELS.items():
        base_xp, targets = xp_defaults.resolve_default_xp((entry_type,))
        catalog[entry_type] = {
            "label": label,
            "base_xp": base_xp,
            "targets": _resolve_target_names(targets, registry),
        }
    return catalog


@operator_journal_bp.get("/")
def dashboard():
    models, service, xp_defaults = _journal_module()
    journal_service = service.JournalService()
    entries = journal_service.list_entries()[:20]

    just_created = None
    created_id = request.args.get("created")
    if created_id:
        just_created = journal_service.get(created_id)

    return render_template(
        "workspaces/operator/journal.html",
        type_catalog=_type_catalog(),
        allowed_types=list(TYPE_LABELS.keys()),
        entries=entries,
        just_created=just_created,
        error=request.args.get("error"),
    )


@operator_journal_bp.post("/create")
def create():
    models, service, xp_defaults = _journal_module()
    journal_service = service.JournalService()

    form = request.form
    title = form.get("title", "").strip()
    body = form.get("body", "").strip()
    entry_types = tuple(form.getlist("entry_types"))

    def split_csv(name: str) -> tuple[str, ...]:
        raw = form.get(name, "")
        return tuple(part.strip() for part in raw.split(",") if part.strip())

    custom_xp_raw = form.get("custom_xp", "").strip()
    evidence_note = form.get("evidence_note", "").strip()

    base_xp = 0
    xp_targets: tuple[dict[str, Any], ...] = ()
    evidence: tuple[Any, ...] = ()

    if custom_xp_raw:
        try:
            custom_xp = max(0, int(custom_xp_raw))
        except ValueError:
            custom_xp = 0
        if custom_xp > 0:
            if not evidence_note:
                return redirect(
                    url_for(
                        "operator_journal.dashboard",
                        error="A manual XP amount needs a proof note - that's the whole point of the guardrail.",
                    )
                )
            # Reuse the same type-driven split the automatic path uses -
            # the user only raises/lowers the total, never touches a
            # competency ID or a weight themselves.
            _, default_targets = xp_defaults.resolve_default_xp(entry_types)
            if not default_targets:
                return redirect(
                    url_for(
                        "operator_journal.dashboard",
                        error="Pick at least one entry type before setting a manual XP amount.",
                    )
                )
            base_xp = custom_xp
            xp_targets = tuple(default_targets)
            evidence = (
                models.JournalEvidence(
                    evidence_type="note",
                    reference=evidence_note,
                    label="Manual XP justification",
                ),
            )

    try:
        request_obj = models.JournalEntryRequest(
            title=title,
            body=body,
            entry_types=entry_types,
            tags=split_csv("tags"),
            projects=split_csv("projects"),
            domains=split_csv("domains"),
            concepts=split_csv("concepts"),
            capabilities=split_csv("capabilities"),
            base_xp=base_xp,
            xp_targets=xp_targets,
            evidence=evidence,
        )
        manifest = journal_service.create(request_obj)
    except ValueError as error:
        return redirect(url_for("operator_journal.dashboard", error=str(error)))

    return redirect(url_for("operator_journal.dashboard", created=manifest.entry_id))
