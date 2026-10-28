from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify

from config import SHADOW_DB, SHADOW_PROGRESS_JSON, SHADOW_TELEMETRY_JSON


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(SHADOW_DB)
    connection.row_factory = sqlite3.Row
    return connection


def _safe_scalar(query: str, parameters: tuple[Any, ...] = ()) -> int:
    try:
        with _connect() as connection:
            row = connection.execute(query, parameters).fetchone()
            return int(row[0]) if row else 0
    except (sqlite3.Error, OSError, TypeError, ValueError):
        return 0


def get_latest_telemetry() -> dict[str, Any] | None:
    try:
        with _connect() as connection:
            row = connection.execute(
                """
                SELECT
                    timestamp,
                    battery_voltage,
                    battery_percentage,
                    latitude,
                    longitude,
                    altitude,
                    roll,
                    pitch,
                    yaw,
                    link_quality,
                    flight_mode
                FROM telemetry
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()

        return dict(row) if row else None
    except (sqlite3.Error, OSError):
        return None


def get_vehicle_record() -> dict[str, Any]:
    try:
        with _connect() as connection:
            row = connection.execute(
                """
                SELECT
                    asset_name,
                    asset_type,
                    model,
                    operational_status,
                    last_seen
                FROM vehicle
                ORDER BY id ASC
                LIMIT 1
                """
            ).fetchone()

        if row:
            return dict(row)
    except (sqlite3.Error, OSError):
        pass

    return {
        "asset_name": "Shadow MK1",
        "asset_type": "Companion Aerial Robot",
        "model": "MK1",
        "operational_status": "Offline",
        "last_seen": None,
    }


def get_latest_simulated_telemetry() -> dict[str, Any] | None:
    # Deliberately NOT using _connect() here - that's scoped to
    # SHADOW_DB, which per the real schema (scripts/init_databases.py)
    # only holds real-hardware tables (vehicle, telemetry, missions,
    # hardware_health, faults, maintenance, battery_cycles).
    # simulated_telemetry and simulation_runs genuinely live in
    # ZERO_GRAVITY_RND_DB instead - this function was incorrectly
    # querying SHADOW_DB before, which is why it never returned real
    # data even with telemetry_bridge.py actually running.
    from config import ZERO_GRAVITY_RND_DB

    try:
        connection = sqlite3.connect(ZERO_GRAVITY_RND_DB)
        connection.row_factory = sqlite3.Row
        with connection:
            row = connection.execute(
                """
                SELECT
                    st.timestamp,
                    st.battery_voltage,
                    st.battery_percentage,
                    st.latitude,
                    st.longitude,
                    st.altitude,
                    st.roll,
                    st.pitch,
                    st.yaw,
                    st.flight_mode,
                    sr.scenario_name,
                    sr.status AS run_status
                FROM simulated_telemetry st
                JOIN simulation_runs sr ON sr.id = st.simulation_run_id
                ORDER BY st.id DESC
                LIMIT 1
                """
            ).fetchone()

        return dict(row) if row else None
    except (sqlite3.Error, OSError):
        return None


def get_shadow_summary() -> dict[str, Any]:
    vehicle = get_vehicle_record()

    return {
        "database_online": Path(SHADOW_DB).exists(),
        "database_path": str(SHADOW_DB),
        "vehicle": {
            "name": vehicle.get("asset_name", "Shadow MK1"),
            "type": vehicle.get("asset_type", "Companion Aerial Robot"),
            "model": vehicle.get("model", "MK1"),
            "status": vehicle.get("operational_status", "Offline"),
            "last_seen": vehicle.get("last_seen"),
        },
        "telemetry": {
            "samples": _safe_scalar("SELECT COUNT(*) FROM telemetry"),
            "latest": get_latest_telemetry(),
        },
        "missions": {
            "total": _safe_scalar("SELECT COUNT(*) FROM missions"),
            "completed": _safe_scalar(
                """
                SELECT COUNT(*)
                FROM missions
                WHERE LOWER(TRIM(status)) = 'completed'
                """
            ),
        },
        "faults": {
            "open": _safe_scalar(
                """
                SELECT COUNT(*)
                FROM faults
                WHERE resolved_at IS NULL
                """
            ),
        },
        "maintenance": {
            "records": _safe_scalar("SELECT COUNT(*) FROM maintenance"),
        },
    }


# How stale the live telemetry file can be before the frontend should
# treat it as "simulation isn't running" rather than genuinely live -
# nodes/telemetry_publisher.py writes at ~20Hz (one sample every 50ms),
# so any gap a poller would actually notice means the publisher or the
# sim itself has stopped, not normal timing jitter between writes.
LIVE_TELEMETRY_STALE_SECONDS = 2.0


def get_live_telemetry() -> dict[str, Any] | None:
    """Read the latest snapshot nodes/telemetry_publisher.py writes to
    SHADOW_TELEMETRY_JSON: connection/arm state, odometry (position +
    orientation + linear/angular velocity), rc_out (real per-motor PWM),
    and imu_filtered/imu_raw (EKF-filtered vs. raw IMU) - per that
    script's own docstring, confirmed live Oct 3 2026 after the IMU
    noise debugging arc (see the roadmap doc).

    Returns None if the file doesn't exist yet (publisher never
    started) or can't be parsed. The publisher's write is already
    atomic (temp file + os.replace), so a reader should never catch a
    half-written file, but a transient race or genuine corruption is
    still handled the same way get_latest_simulated_telemetry() treats
    a missing row: no live data available, not an error to raise.

    The snapshot itself carries no wall-clock timestamp - its only time
    field, imu.stamp_sec, is Gazebo sim time, which is exactly what
    made a stale, never-restarted Gazebo process look live during that
    debugging arc. So staleness here is judged off the file's own
    mtime instead, and merged into the returned dict as 'stale' /
    'age_seconds' rather than left for every caller to recompute.
    """
    try:
        raw = SHADOW_TELEMETRY_JSON.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None

    try:
        age_seconds = time.time() - SHADOW_TELEMETRY_JSON.stat().st_mtime
    except OSError:
        age_seconds = None

    payload["age_seconds"] = age_seconds
    payload["stale"] = age_seconds is None or age_seconds > LIVE_TELEMETRY_STALE_SECONDS
    return payload


def get_skill_progress() -> dict[str, Any] | None:
    """Read shadow_drone's own progress.json - the real, git-tracked
    file nodes/run_skill.py writes every skill pass/fail to (streak +1
    on pass, reset to 0 on any fail, unlocked at streak 3). This is
    skill-tree state, not live telemetry: it only changes when a
    training run actually happens on the Ubuntu machine, which could
    be minutes or days old, so unlike get_live_telemetry() there's no
    'stale' concept to compute here - an old file is just the correct,
    current unlock state, not a sign anything has stopped running.

    Returns None if the file doesn't exist yet (no training has ever
    run) or can't be parsed - same "no data available" handling as
    the other Shadow reads in this file, not an error to raise.
    """
    try:
        raw = SHADOW_PROGRESS_JSON.read_text(encoding="utf-8")
        return json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None


shadow_bp = Blueprint("shadow", __name__, url_prefix="/shadow")


@shadow_bp.after_request
def _allow_cross_origin_reads(response):
    """The Simulation Bay (three.js) runs as a published artifact on
    claude.ai's own origin, not inside this Flask app, so the browser
    treats a fetch() to this route as cross-origin and blocks the
    response unless it carries an Access-Control-Allow-Origin header -
    without this, polling just fails silently with no telemetry ever
    reaching the page. Scoped to this blueprint only (via Blueprint's
    own after_request, not app.after_request), not the whole Flask app.
    Read-only, and this app only ever binds to 127.0.0.1, so a
    permissive '*' here doesn't expose anything that a browser on this
    machine couldn't already reach directly.
    """
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


@shadow_bp.get("/telemetry")
def telemetry():
    """JSON API for the Digital Lab's three.js frontend (Simulation Bay)
    to poll. Same service-plus-blueprint-plus-JSON-API shape as the
    Flight Log Hub (modules/operator_flights.py calling into
    operator_core.flights.service) - kept as functions in this file
    rather than a separate service module, since Shadow's telemetry
    read has no engine-side logic (XP, events, competencies) for
    anything else to share.

    Always returns 200, even with no live data: "the simulation isn't
    running right now" is a normal, expected result for a frontend
    that polls continuously, not an error condition worth a non-2xx
    status - the client branches on the 'available'/'stale' fields
    instead.
    """
    live = get_live_telemetry()
    if live is None:
        return jsonify({"available": False, "stale": True, "age_seconds": None})
    return jsonify({"available": True, **live})


@shadow_bp.get("/progress")
def progress():
    """JSON API for the Digital Lab's skill-tree panel: which skills
    are unlocked and their current streak, read straight from
    shadow_drone's real progress.json, not mocked/example numbers.

    Always returns 200 - no file yet just means no training run has
    ever happened on this machine, a normal state for a fresh checkout,
    not an error.
    """
    skills = get_skill_progress()
    return jsonify({"available": skills is not None, "skills": skills or {}})
