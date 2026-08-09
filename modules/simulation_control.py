"""Simulation control - lets Zero Command's UI actually trigger the
same scripts you'd otherwise run by hand in a terminal. Genuinely the
same script either way, just triggered by a click instead of typing -
same principle discussed earlier tonight about UI buttons being a thin
layer over the real backend commands, not a separate system.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from flask import Blueprint, jsonify

bp = Blueprint("simulation_control", __name__, url_prefix="/simulation")

SCRIPTS_DIR = Path.home() / "shadow_ws" / "scripts"


def _run_detached(script_name: str) -> dict:
    script_path = SCRIPTS_DIR / script_name
    if not script_path.exists():
        return {"ok": False, "error": f"Script not found: {script_path}"}

    # start_new_session=True detaches this from Flask's own process -
    # it keeps running after the request finishes, which matters since
    # these scripts start long-running background processes.
    subprocess.Popen(
        ["bash", str(script_path)],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"ok": True}


@bp.route("/start", methods=["POST"])
def start_simulation():
    return jsonify(_run_detached("run_full_sim.sh"))


@bp.route("/stop", methods=["POST"])
def stop_simulation():
    return jsonify(_run_detached("stop_full_sim.sh"))


@bp.route("/run-mission", methods=["POST"])
def run_mission():
    return jsonify(_run_detached("run_mission.sh"))
