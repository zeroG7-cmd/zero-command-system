from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request

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


# ---- Training Log (Oct 26, 2026) - reports + manual log, inside Digital
# Twin -----------------------------------------------------------------------
#
# Zer0's ask: a screen inside Digital Twin, same list->detail shape as
# his Learning Hub entries, except the entries write themselves - one
# auto-generated report per simulation run, pulling together the three
# things that used to have no idea about each other (the run itself,
# which skill(s) were attempted during it - skill_attempts, wired up
# Oct 25 night - and a telemetry summary), plus a second, manual side
# (his own notes/log) replacing Test_Logger.py's intent properly:
# structured into the database instead of an interactive terminal
# script writing loose .txt files nobody ever read back (checked
# directly - it produced exactly one file, ever, six months ago).

MAX_CHART_POINTS = 300


def _connect_rnd() -> sqlite3.Connection:
    from config import ZERO_GRAVITY_RND_DB

    connection = sqlite3.connect(ZERO_GRAVITY_RND_DB)
    connection.row_factory = sqlite3.Row
    return connection


def _ensure_skill_attempts_table(connection: sqlite3.Connection) -> None:
    # Mirrors nodes/run_skill.py's own _ensure_skill_attempts_table()
    # exactly - duplicated rather than imported, since this Flask app
    # and run_skill.py are two separate Python environments (this
    # app's venv vs. the ROS2-sourced one run_skill.py runs under)
    # with no shared module path between them. Idempotent either way,
    # so it's safe to call even once run_skill.py has already created
    # the real table.
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS skill_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            simulation_run_id INTEGER NOT NULL,
            skill_name TEXT NOT NULL,
            result TEXT NOT NULL,
            reason TEXT,
            streak_after INTEGER,
            attempted_at TEXT NOT NULL
        )
        """
    )


def _ensure_mission_events_table(connection: sqlite3.Connection) -> None:
    # Oct 26, 2026 (later still) - Zer0's call: missions don't get a
    # separate log/report system of their own. They tag into the same
    # simulation_runs row and the same Training Log Reports/Events
    # view skill_attempts already uses, not a parallel one. Mirrors
    # simulation_control.py's own _ensure_mission_events_table() exactly,
    # same reasoning _ensure_skill_attempts_table() above already
    # documents for why this is duplicated rather than imported (two
    # separate Python environments, no shared module path). Idempotent
    # either way.
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS mission_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            simulation_run_id INTEGER NOT NULL,
            mission_key TEXT NOT NULL,
            mission_name TEXT NOT NULL,
            status TEXT NOT NULL,
            detail TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT
        )
        """
    )


def _ensure_manual_test_logs_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS manual_test_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_name TEXT NOT NULL,
            component TEXT,
            result TEXT NOT NULL,
            notes TEXT,
            simulation_run_id INTEGER,
            logged_at TEXT NOT NULL
        )
        """
    )


def _decimate(rows: list, max_points: int = MAX_CHART_POINTS) -> list:
    """Evenly-spaced downsampling, not just the first N rows - a long
    run's telemetry (potentially thousands of 1Hz samples) stays a
    reasonably small chart payload without losing the overall shape a
    short run's chart would otherwise show at full resolution."""
    n = len(rows)
    if n <= max_points:
        return rows
    step = n / max_points
    return [rows[int(i * step)] for i in range(max_points)]


def list_simulation_run_reports(limit: int = 50) -> list[dict[str, Any]]:
    """Generated reports - one per simulation_runs row, most recent
    first, for the Training Log's Reports tab list view."""
    try:
        with _connect_rnd() as connection:
            _ensure_skill_attempts_table(connection)
            _ensure_mission_events_table(connection)
            runs = connection.execute(
                """
                SELECT id, scenario_name, vehicle_model, status, started_at, completed_at
                FROM simulation_runs ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()

            reports = []
            for run in runs:
                run_id = run["id"]
                skills = connection.execute(
                    """
                    SELECT skill_name, result, streak_after FROM skill_attempts
                    WHERE simulation_run_id = ? ORDER BY attempted_at ASC
                    """,
                    (run_id,),
                ).fetchall()
                missions = connection.execute(
                    """
                    SELECT mission_key, mission_name, status FROM mission_events
                    WHERE simulation_run_id = ? ORDER BY started_at ASC
                    """,
                    (run_id,),
                ).fetchall()
                summary = connection.execute(
                    """
                    SELECT COUNT(*) AS sample_count,
                           MIN(altitude) AS altitude_min, MAX(altitude) AS altitude_max,
                           MIN(battery_percentage) AS battery_min, MAX(battery_percentage) AS battery_max
                    FROM simulated_telemetry WHERE simulation_run_id = ?
                    """,
                    (run_id,),
                ).fetchone()
                reports.append({
                    "id": run_id,
                    "scenario_name": run["scenario_name"],
                    "vehicle_model": run["vehicle_model"],
                    "status": run["status"],
                    "started_at": run["started_at"],
                    "completed_at": run["completed_at"],
                    "skills": [dict(s) for s in skills],
                    "missions": [dict(m) for m in missions],
                    "telemetry_sample_count": summary["sample_count"] or 0,
                    "altitude_min": summary["altitude_min"],
                    "altitude_max": summary["altitude_max"],
                    "battery_min": summary["battery_min"],
                    "battery_max": summary["battery_max"],
                })
            return reports
    except (sqlite3.Error, OSError):
        return []


def get_simulation_run_report(run_id: int) -> dict[str, Any] | None:
    """Full detail for ONE simulation run - the generated report Zer0
    opens from the Training Log's list, same list->detail shape as his
    Learning Hub entries. The telemetry series is decimated (see
    _decimate() above) so the chart payload stays small."""
    try:
        with _connect_rnd() as connection:
            run = connection.execute(
                """
                SELECT id, scenario_name, vehicle_model, status, started_at, completed_at
                FROM simulation_runs WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
            if run is None:
                return None

            _ensure_skill_attempts_table(connection)
            skills = connection.execute(
                """
                SELECT skill_name, result, reason, streak_after, attempted_at
                FROM skill_attempts WHERE simulation_run_id = ? ORDER BY attempted_at ASC
                """,
                (run_id,),
            ).fetchall()

            _ensure_mission_events_table(connection)
            missions = connection.execute(
                """
                SELECT mission_key, mission_name, status, detail, started_at, completed_at
                FROM mission_events WHERE simulation_run_id = ? ORDER BY started_at ASC
                """,
                (run_id,),
            ).fetchall()

            telemetry = connection.execute(
                """
                SELECT timestamp, altitude, battery_percentage, flight_mode
                FROM simulated_telemetry WHERE simulation_run_id = ? ORDER BY id ASC
                """,
                (run_id,),
            ).fetchall()

        telemetry_rows = [dict(t) for t in telemetry]
        mission_rows = [dict(m) for m in missions]

        # Oct 26, 2026 (later still) - the merged "bigger picture" view
        # Zer0 asked for: one chronological timeline across whatever
        # actually happened in this run, not separate chip rows per
        # source. Missions tag in here the same way skills already do -
        # by timestamp, into the same list - rather than getting their
        # own parallel log/report. Each entry gets a 'kind' so the
        # frontend can style skill vs. mission rows differently without
        # needing two separate fetches. A mission's own start AND end
        # both become entries (end only once record_mission_result.py -
        # called by the mission script itself on exit - has actually
        # reported back; a mission still 'started' with no end yet just
        # means it's still flying or the script never got a chance to
        # report, same honest "no data yet" handling as everything else
        # here rather than guessing an outcome).
        # "key" (Oct 26, 2026, even later still) - added alongside the
        # existing display fields so the new in-depth-report feature has
        # something to hand back to /simulation/event-log-context: for a
        # skill it's just skill_name (label already was this), for a
        # mission it's mission_key (flight_smoke/deliver_payload/
        # learned_flight - "label" is the human-readable mission_name,
        # not reliably matchable against the lowercase key log lines
        # actually use).
        events = []
        for s in skills:
            events.append({
                "kind": "skill",
                "key": s["skill_name"],
                "label": s["skill_name"],
                "status": s["result"],
                "detail": s["reason"],
                "timestamp": s["attempted_at"],
            })
        for m in mission_rows:
            events.append({
                "kind": "mission",
                "key": m["mission_key"],
                "label": m["mission_name"],
                "status": "started",
                "detail": None,
                "timestamp": m["started_at"],
            })
            if m["completed_at"]:
                events.append({
                    "kind": "mission",
                    "key": m["mission_key"],
                    "label": m["mission_name"],
                    "status": m["status"],
                    "detail": m["detail"],
                    "timestamp": m["completed_at"],
                })
        events.sort(key=lambda e: e["timestamp"] or "")

        return {
            "id": run["id"],
            "scenario_name": run["scenario_name"],
            "vehicle_model": run["vehicle_model"],
            "status": run["status"],
            "started_at": run["started_at"],
            "completed_at": run["completed_at"],
            "skills": [dict(s) for s in skills],
            "missions": mission_rows,
            "events": events,
            "telemetry_sample_count": len(telemetry_rows),
            "telemetry_series": _decimate(telemetry_rows),
        }
    except (sqlite3.Error, OSError):
        return None


def list_manual_test_logs(limit: int = 50) -> list[dict[str, Any]]:
    try:
        with _connect_rnd() as connection:
            _ensure_manual_test_logs_table(connection)
            rows = connection.execute(
                """
                SELECT id, test_name, component, result, notes, simulation_run_id, logged_at
                FROM manual_test_logs ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
    except (sqlite3.Error, OSError):
        return []


def create_manual_test_log(test_name: str, component: str, result: str, notes: str) -> dict[str, Any]:
    """Zer0's own old Test_Logger.py's intent, done properly: a
    structured, database-backed manual log entry instead of an
    interactive terminal script writing loose .txt files. Auto-links
    to whichever simulation_runs row is currently 'running', if any -
    same lookup nodes/run_skill.py's own _record_skill_attempt()
    already uses - so a note taken during a live sim session is tied
    to that session automatically."""
    from datetime import datetime, timezone

    with _connect_rnd() as connection:
        _ensure_manual_test_logs_table(connection)
        active_run = connection.execute(
            "SELECT id FROM simulation_runs WHERE status = 'running' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        run_id = active_run["id"] if active_run else None

        cursor = connection.execute(
            """
            INSERT INTO manual_test_logs (test_name, component, result, notes, simulation_run_id, logged_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (test_name, component, result, notes, run_id, datetime.now(timezone.utc).isoformat()),
        )
        connection.commit()
        return {
            "id": cursor.lastrowid,
            "test_name": test_name,
            "component": component,
            "result": result,
            "notes": notes,
            "simulation_run_id": run_id,
        }


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


@shadow_bp.get("/reports")
def reports():
    """JSON API for the Digital Twin's Training Log - Reports tab list
    view. Always 200; an empty list just means no sim run has happened
    yet, a normal state, not an error."""
    return jsonify({"ok": True, "reports": list_simulation_run_reports()})


@shadow_bp.get("/reports/<int:run_id>")
def report_detail(run_id: int):
    """JSON API for one report's detail view, including the decimated
    telemetry series the Training Log's charts are built from."""
    report = get_simulation_run_report(run_id)
    if report is None:
        return jsonify({"ok": False, "error": f"No simulation run with id {run_id}"}), 404
    return jsonify({"ok": True, "report": report})


@shadow_bp.get("/manual-logs")
def manual_logs():
    """JSON API for the Training Log's My Log tab list view."""
    return jsonify({"ok": True, "logs": list_manual_test_logs()})


@shadow_bp.post("/manual-logs")
def create_manual_log():
    """Creates one manual log entry - the My Log tab's own form, the
    structured replacement for Test_Logger.py's interactive terminal
    prompts (test name, component, result, notes - same fields, now a
    web form writing to the database instead of a loose .txt file)."""
    body = request.get_json(silent=True) or {}
    test_name = (body.get("test_name") or "").strip()
    if not test_name:
        return jsonify({"ok": False, "error": "test_name is required"}), 400
    entry = create_manual_test_log(
        test_name=test_name,
        component=(body.get("component") or "").strip(),
        result=(body.get("result") or "note").strip(),
        notes=(body.get("notes") or "").strip(),
    )
    return jsonify({"ok": True, "log": entry})
