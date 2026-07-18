"""Operator task hub.

Tasks are part of Operator Development because they provide execution and
Discipline evidence. This first version keeps storage deliberately simple and
local to zeroGravity-rnd.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, redirect, render_template, request, url_for

bp = Blueprint("operator_tasks", __name__, url_prefix="/operator/tasks")


def _rnd_root() -> Path:
    configured = os.getenv("ZERO_GRAVITY_RND_ROOT") or current_app.config.get("ZERO_GRAVITY_RND_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(current_app.root_path).resolve().parent / "zeroGravity-rnd"


def _tasks_file() -> Path:
    path = _rnd_root() / "operator_core" / "hubs" / "tasks" / "data" / "tasks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_tasks() -> list[dict[str, Any]]:
    path = _tasks_file()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def _save_tasks(tasks: list[dict[str, Any]]) -> None:
    _tasks_file().write_text(json.dumps(tasks, indent=2), encoding="utf-8")


@bp.route("/", methods=["GET", "POST"])
def dashboard():
    tasks = _load_tasks()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if title:
            tasks.insert(0, {
                "id": f"task-{int(datetime.now(timezone.utc).timestamp() * 1000)}",
                "title": title,
                "status": "open",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "stat": request.form.get("stat", "DISC"),
            })
            _save_tasks(tasks)
        return redirect(url_for("operator_tasks.dashboard"))
    return render_template("workspaces/operator/tasks.html", tasks=tasks)


@bp.post("/<task_id>/toggle")
def toggle(task_id: str):
    tasks = _load_tasks()
    for task in tasks:
        if task.get("id") == task_id:
            task["status"] = "done" if task.get("status") != "done" else "open"
            break
    _save_tasks(tasks)
    return redirect(url_for("operator_tasks.dashboard"))
