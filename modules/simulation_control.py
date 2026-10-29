"""Simulation control - lets Zero Command's UI actually trigger the
same scripts you'd otherwise run by hand in a terminal. Genuinely the
same script either way, just triggered by a click instead of typing -
same principle discussed earlier tonight about UI buttons being a thin
layer over the real backend commands, not a separate system.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import statistics
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Blueprint, jsonify, request

bp = Blueprint("simulation_control", __name__, url_prefix="/simulation")

SCRIPTS_DIR = Path.home() / "shadow_ws" / "scripts"

# Oct 17 (later): the Mind's own decision log - one JSON object per line,
# written by run_mind.py (see that file's log_event()). Read-only from
# this side; Flask never writes to it, only tails it for the UI panel.
MIND_LOG_FILE = Path.home() / "shadow_sim_runtime" / "logs" / "mind.jsonl"

# Worlds the "Start Simulation" world picker is allowed to request.
# run_full_sim.sh takes the world name as its one positional arg -
# allowlisting it here (rather than passing whatever the request body
# says straight through to bash) is what makes that safe to expose as
# a dropdown value instead of a terminal arg.
#
# Oct 17: living_room/empty were PX4 Gazebo-Classic Makefile targets -
# stale since the ArduPilot/Gazebo Harmonic migration. shadow_runway is
# the only world that actually exists for the new stack (lives at
# ardu_ws/src/ardupilot_gazebo/worlds/shadow_runway.sdf) - living_room
# was never ported to the new SDF format (see the roadmap doc's "Repo
# changes to shadow_drone" table), so there's genuinely only one choice
# right now, not a picker with one option artificially removed.
ALLOWED_WORLDS = {"shadow_runway"}

# Missions the "Run Mission" dropdown in the Simulation Bay can trigger -
# Oct 24, 2026, added alongside shadow/skills/deliver_payload.py. Same
# allowlist-by-dict pattern as ALLOWED_WORLDS above: the dropdown's value
# picks a key here, it's never passed straight through to bash.
#
# Both scripts share run_mission.sh's own lock file (run_mission.lock),
# not independent locks each - what that lock actually protects is "only
# one process drives Shadow's flight controller at a time," which is true
# across both missions, not specific to run_mission.sh's own filename.
ALLOWED_MISSIONS = {
    "flight_smoke": "run_mission.sh",
    "deliver_payload": "run_deliver_payload.sh",
    # Oct 25, 2026 (later) - the first mission flown by a trained policy
    # (shadow/skills/learned_flight.py) instead of hand-coded control
    # math. Same shared run_mission.lock reasoning as deliver_payload
    # above - only one process drives Shadow at a time.
    "learned_flight": "run_learned_flight.sh",
}

# Human-readable names for the Training Log's merged Events timeline -
# deliberately distinct wording from the Skill Tests' "Learned Flight
# (trained policy)" / "Waypoint Circuit (trained policy)" rows, even
# where they fly the exact same underlying skill, so an Events entry
# reads as "this was the Mission button" rather than looking like a
# duplicate of a Skill Test run.
MISSION_NAMES = {
    "flight_smoke": "Flight-Skills Smoke Sequence",
    "deliver_payload": "Deliver Payload",
    "learned_flight": "Learned Flight (Mission)",
}

# Oct 26, 2026 (later still) - same zerogravity_rnd.db every other
# simulation-linked table lives in (skill_attempts, simulated_telemetry,
# simulation_runs - see telemetry_bridge.py/run_skill.py's own DB_PATH
# comments for why). Missions tag into that same DB rather than getting
# a separate store, per Zer0's own call: no separate mission-log system.
RND_DB_PATH = Path.home() / "zeroGravity-rnd" / "lab" / "database" / "zerogravity_rnd.db"


def _ensure_mission_events_table(conn: sqlite3.Connection) -> None:
    # Mirrors shadow.py's own _ensure_mission_events_table() exactly -
    # same "two separate Python environments, no shared module path"
    # reasoning _ensure_skill_attempts_table() duplication already
    # documents elsewhere in this codebase.
    conn.execute(
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


def _record_mission_started(mission_key: str, mission_name: str) -> int | None:
    """Tags this mission launch to whichever simulation_runs row
    telemetry_bridge.py currently has marked 'running' - same linking
    nodes/run_skill.py's own _record_skill_attempt() already does for
    individual skills, so a mission run shows up in the same Training
    Log Reports/Events a skill test would, not a separate system.

    Returns the new mission_events row's id so the launching script can
    report its own outcome back into that same row via the new
    shadow_ws/scripts/record_mission_result.py helper (passed through as
    this process's one positional arg - see run_mission.sh/
    run_deliver_payload.sh/run_learned_flight.sh). Returns None if
    there's no live 'running' run to link to, or the DB write failed -
    deliberately best-effort and never blocks the mission launch itself,
    same reasoning _record_skill_attempt() documents for the same
    situation.
    """
    try:
        conn = sqlite3.connect(str(RND_DB_PATH))
        try:
            _ensure_mission_events_table(conn)
            row = conn.execute(
                "SELECT id FROM simulation_runs WHERE status = 'running' "
                "ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            cursor = conn.execute(
                """
                INSERT INTO mission_events (
                    simulation_run_id, mission_key, mission_name, status, started_at
                ) VALUES (?, ?, ?, 'started', ?)
                """,
                (row[0], mission_key, mission_name, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()
    except sqlite3.Error:
        return None


# Oct 26, 2026 (even later still) - Zer0 hit this blind twice in one
# session: clicking Run Mission (Deliver Payload) while a skill test's
# own flight was still in the air, and clicking Evaluate while Train
# was still running. Both are correctly refused deep inside the shell
# script - run_mission.sh/run_deliver_payload.sh/run_learned_flight.sh/
# run_skill_test.sh all share run_mission.lock ("only one process
# drives Shadow at a time"), and run_checkpoint_eval.sh shares
# run_training.lock with run_training.sh/run_agility_training.sh - but
# _run_detached() below used to just fire the script and return
# {"ok": True} immediately, with no way to know the script would
# self-refuse moments later. That's exactly what left Deliver Payload's
# mission_events row frozen at "started" forever (its EVENT_ID was
# created before the refusal, and the refusal branch in those three
# scripts never resolved it - see record_mission_result.py and the
# matching fix in each script's own lock block), and what made
# Evaluate look like it silently did nothing while Train was mid-run,
# rather than correctly refusing. This mirrors the same `kill -0`
# check those scripts already do on themselves, in Python, so the
# route can catch and report the same refusal BEFORE launching.
LOCK_DIR = Path.home() / "shadow_sim_runtime" / "logs"
LOCK_NAMES = {
    "mission": "run_mission.lock",
    "training": "run_training.lock",
}


def _lock_holder_pid(lock: str) -> int | None:
    """Returns the PID currently holding a lock file, or None if it's
    free/stale (file missing, unreadable, or its PID is no longer
    alive - a crashed script's lock file can outlive the process that
    wrote it, same as the bash scripts' own `[ -f ... ] && kill -0 ...`
    check already tolerates)."""
    try:
        pid = int((LOCK_DIR / LOCK_NAMES[lock]).read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return pid


def _run_detached(script_name: str, args: list[str] | None = None, lock: str | None = None) -> dict:
    if lock is not None:
        holder = _lock_holder_pid(lock)
        if holder is not None:
            busy_with = "a training or evaluation run" if lock == "training" else "a mission or skill test"
            return {"ok": False, "error": f"{busy_with} is already in progress (PID {holder}) - wait for it to finish, then try again."}

    script_path = SCRIPTS_DIR / script_name
    if not script_path.exists():
        return {"ok": False, "error": f"Script not found: {script_path}"}

    # start_new_session=True detaches this from Flask's own process -
    # it keeps running after the request finishes, which matters since
    # these scripts start long-running background processes.
    subprocess.Popen(
        ["bash", str(script_path), *(args or [])],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"ok": True}


@bp.route("/start", methods=["POST"])
def start_simulation():
    body = request.get_json(silent=True) or {}
    world = body.get("world", "shadow_runway")
    if world not in ALLOWED_WORLDS:
        return jsonify({"ok": False, "error": f"Unknown world: {world}"})
    return jsonify(_run_detached("run_full_sim.sh", [world]))


@bp.route("/stop", methods=["POST"])
def stop_simulation():
    return jsonify(_run_detached("stop_full_sim.sh"))


@bp.route("/run-mission", methods=["POST"])
def run_mission():
    body = request.get_json(silent=True) or {}
    mission = body.get("mission", "flight_smoke")
    script = ALLOWED_MISSIONS.get(mission)
    if script is None:
        return jsonify({"ok": False, "error": f"Unknown mission: {mission}"})
    # Oct 26, 2026 (even later still) - the lock check now runs FIRST,
    # before _record_mission_started() creates any row at all. Used to
    # be the other way round: a mission_events "started" row got
    # created unconditionally, then the script would self-refuse inside
    # its own lock check a moment later and exit without ever calling
    # record_mission_result.py (that refusal branch didn't report
    # anything back - now fixed in the scripts themselves too, as a
    # second line of defence), leaving the row frozen at "started"
    # forever with no explanation. Checking here means a refused click
    # no longer creates a dangling event at all - the UI gets an honest
    # {"ok": False, "error": ...} immediately instead.
    holder = _lock_holder_pid("mission")
    if holder is not None:
        return jsonify({"ok": False, "error": f"a mission or skill test is already in progress (PID {holder}) - wait for it to finish, then try again."})
    # Oct 26, 2026 (later still) - tag this launch into mission_events
    # BEFORE starting the detached script, so the event row (and its id,
    # which the script reports its own outcome back into) exists from
    # the first moment, not racing the script's own startup. event_id
    # defaults to "0" (a no-op for record_mission_result.py) when there's
    # no live 'running' simulation_runs row to link to - the mission
    # still launches either way, it just won't show up in the Training
    # Log, same as running it from a terminal with no sim started.
    mission_name = MISSION_NAMES.get(mission, mission)
    event_id = _record_mission_started(mission, mission_name)
    return jsonify(_run_detached(script, [str(event_id or 0)], lock="mission"))


@bp.route("/run-autotune", methods=["POST"])
def run_autotune():
    # NOT fixed for the ArduPilot/Harmonic migration as of Oct 17 - still
    # calls the retired PX4-era autotune_hover.py against a world/stack
    # that no longer matches it. Left as-is deliberately rather than
    # guessed at: the real fix needs a design call (keep a custom
    # autotune script vs. just use ArduCopter's own native AUTOTUNE
    # flight mode, which didn't exist as an option under the old PX4
    # setup), not on the critical path for the delivery-mission demo.
    # Clicking this button right now will not do anything useful.
    return jsonify(_run_detached("run_autotune.sh"))


@bp.route("/restart-world-view", methods=["POST"])
def restart_world_view():
    # NOT fixed for the ArduPilot/Harmonic migration as of Oct 17 - still
    # targets gzclient/gzserver (Gazebo Classic's process split), which
    # doesn't match how `gz sim` is launched in run_full_sim.sh now.
    # Harmonic does support a server/GUI split (`gz sim -s` / `gz sim -g`,
    # used once already during this migration's own GUI debugging), but
    # wiring that up means launching them as two separate processes in
    # run_full_sim.sh instead of one combined `gz sim -r world.sdf` call -
    # a real restructuring, not done this round. Clicking this button
    # right now will fail its own "is gzserver running" check and do
    # nothing useful; use Stop + Start Simulation instead if the view
    # gets stuck.
    return jsonify(_run_detached("restart_world_view.sh"))


@bp.route("/run-mind", methods=["POST"])
def run_mind():
    """Launches run_mind.py (see shadow_ws/scripts/run_mind.py) - the
    Mind layer's real first implementation: a bounded LLM decision loop
    that picks among Shadow's already-proven skills and actually runs
    them via run_skill.py. Needs ANTHROPIC_API_KEY set wherever this
    script's shell actually runs (see run_mind.sh's own note on
    non-login shells not sourcing ~/.bashrc - the same gotcha
    run_full_sim.sh hit with GZ_IP). Requires a live SITL+Gazebo session
    (Start Simulation first) for anything beyond --dry-run to do
    anything meaningful.
    """
    body = request.get_json(silent=True) or {}
    args = []
    if body.get("dry_run"):
        args.append("--dry-run")
    max_steps = body.get("max_steps")
    if isinstance(max_steps, int) and 1 <= max_steps <= 8:
        args += ["--max-steps", str(max_steps)]
    return jsonify(_run_detached("run_mind.sh", args))


@bp.route("/mind-log", methods=["GET"])
def mind_log():
    """Tails the Mind's own decision log for the Simulation Bay's live
    transcript panel. Read-only, never errors the page if the log
    doesn't exist yet (no Mind run has happened) or has a bad line -
    a malformed/partial line (the log is append-only but a reader could
    still race an in-progress write) is just skipped, not fatal.
    """
    if not MIND_LOG_FILE.exists():
        return jsonify({"ok": True, "events": []})

    events = []
    try:
        lines = MIND_LOG_FILE.read_text().splitlines()
    except OSError as exc:
        return jsonify({"ok": False, "error": str(exc), "events": []})

    for line in lines[-100:]:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # tolerate a torn line from an in-progress write

    return jsonify({"ok": True, "events": events})


# ---- Training task registry (Oct 25, 2026, later) --------------------------
#
# Zer0's own ask, after watching the training-button list grow to two
# flat, hand-written entries ("Start Training (go_to)", "Start Agility
# Training") with no shared structure: "maybe we could design a
# training panel and maybe the attribute behind the training... let's
# arrange it better and have better names, group it better too." This
# list is the fix - ONE definition per training task, read by BOTH the
# launch route and the status route below, and by the dashboard's
# training panel (GET /simulation/training-tasks). Adding a third task
# (a future vision+flight hybrid, say) means one new entry here, not a
# new route, a new button, and a new bit of bespoke JS each time.
#
# "name" is what a human reads in the panel - deliberately NOT the same
# as the internal task key or the script filename, so the panel can use
# plain language ("Point-to-Point Flight") while the code underneath
# keeps using its existing names (go_to). "feeds_attributes" is which
# Drone Attributes score(s) this task's crash-free rate currently
# contributes to - both tasks feed AGILITY today, by design: AGILITY is
# the attribute name (an ability score), not a synonym for any one
# task, precisely so a later task can feed it too, or feed a different
# attribute entirely (PRECISION, once deliver_payload has a real
# success-rate source - see drone-attributes-system.md's own "not yet
# wired" list) without this registry's shape needing to change.
# EVAL_TASKS (Oct 26, 2026, later) - decoupled from TRAINING_TASKS/
# SKILL_TESTS display lists on purpose. eval_checkpoint.py only knows
# two tasks, go_to and agility_circuit, each backed by one checkpoint
# file - but THREE different buttons now want to trigger/read that
# same evaluation: the Waypoint Circuit Training card (agility_circuit),
# and the Skill Tests' Sequences buttons for Learned Flight (flies
# go_to's checkpoint by default) and Waypoint Circuit - skill test
# (flies agility_circuit's). Point-to-Point Flight's own Training card
# was removed below (Zer0's call - Go To already exists as a Basic
# Skills test, so a separate training card felt redundant) but go_to's
# checkpoint/training script/eval task are all untouched - this registry
# is what keeps Learned Flight able to show and re-run that same eval
# even with no go_to card left anywhere on the page.
EVAL_TASKS = {
    "go_to": {
        "checkpoint_path": Path.home() / "shadow_ws" / "ml" / "models" / "go_to" / "go_to_ppo_final.zip",
        "eval_experiment": "shadow-go-to-eval",
        "eval_metric_key": "eval_success_rate",
        "eval_metric_label": "held-out success rate",
    },
    "agility_circuit": {
        "checkpoint_path": Path.home() / "shadow_ws" / "ml" / "models" / "agility_circuit" / "agility_circuit_ppo_final.zip",
        "eval_experiment": "shadow-agility-circuit-eval",
        "eval_metric_key": "eval_crash_free_rate",
        "eval_metric_label": "held-out crash-free rate",
    },
}

TRAINING_TASKS = [
    {
        "key": "go_to",
        # Oct 26, 2026 (even later still) - re-added so Learned Flight's
        # Skill Tests row can grow its own Train button, same generic
        # train_task_key mechanism waypoint_circuit already proved out
        # (see that entry's own comment below). This is the SAME
        # checkpoint/training script/mlflow experiment go_to's old
        # standalone Training card used before it was removed (Zer0's
        # call, at the time - "Go To already exists as a Basic Skills
        # test, so a separate training card felt redundant") - nothing
        # about the underlying task changed, only which row on the page
        # can kick off a real gradient-updating run of it. Zer0's own
        # ask tonight: "we do need a train button for the learn [flight],
        # because if that's the case, it only has run evaluation, it's
        # not really training then" - correct catch, since without this
        # Learned Flight's row could only ever replay whatever checkpoint
        # happened to already exist on disk.
        "name": "Learned Flight",
        "description": (
            "PPO learns go_to's core primitive - fly from wherever Shadow "
            "currently is to a freshly sampled random goal point, over and "
            "over - the exact same checkpoint Learned Flight's Skill Tests "
            "row flies (go_to_ppo_final.zip)."
        ),
        "script": "run_training.sh",
        "checkpoint_path": EVAL_TASKS["go_to"]["checkpoint_path"],
        "mlflow_experiment": "shadow-go-to",
        "feeds_attributes": ["agility", "stability"],
        "log_file": "training.log",
        "eval_experiment": "shadow-go-to-eval",
        "eval_metric_key": "eval_success_rate",
        "eval_metric_label": "held-out success rate",
    },
    {
        "key": "agility_circuit",
        # Oct 26, 2026 (even later still) - this was the Training panel's
        # last remaining card ("Train: Waypoint Circuit", briefly, after
        # an earlier rename from "Waypoint Circuit"). Zer0 flagged it as
        # a duplicate of the Skill Tests' "Waypoint Circuit (trained
        # policy)" row three times - this entry (and TRAINING_TASKS/the
        # standalone panel it backed) is unchanged, but the panel no
        # longer renders it as its own card: the dashboard's Skill Tests
        # row now reads this task's checkpoint/training stats directly
        # (see SKILL_TESTS' "train_task_key" and /skill-tests' merge of
        # _training_task_stats() above) and gained its own Train button
        # that still calls /run-training-task -> run_agility_training.sh
        # (the only thing that actually gradient-updates this policy;
        # the row's own Run/Run & Evaluate buttons only ever fly the
        # checkpoint that already exists). "name" below is now only used
        # by the still-reachable /training-tasks API, not the page.
        "name": "Waypoint Circuit",
        "description": (
            "PPO learns to race continuously through a fixed six-point "
            "circuit - the real payload/pad coordinates from "
            "shadow_runway.sdf - lap after lap. \"Agility-lite\": fast, "
            "precise flight between real points under time pressure, "
            "not literal gate-passing yet."
        ),
        "script": "run_agility_training.sh",
        "checkpoint_path": EVAL_TASKS["agility_circuit"]["checkpoint_path"],
        "mlflow_experiment": "shadow-agility-circuit",
        "feeds_attributes": ["agility", "stability"],
        "log_file": "agility_training.log",
        # Oct 25, 2026 (even later) - train_agility.py's own
        # --reset-from-go-to flag (go_to as this task's baseline - see
        # that script's docstring), now reachable from the dashboard
        # too, not just a terminal. go_to has no training card of its
        # own to click this from anymore, but the flag/script/checkpoint
        # underneath are all still there - this just means kicking off
        # a go_to retrain yourself (run_training.sh go_to) would now be
        # a terminal job rather than a dashboard button, same as before
        # any of these buttons existed.
        "supports_reset_from_go_to": True,
        # Oct 26, 2026 - agility_circuit has no single "arrived"
        # terminal state (see eval_checkpoint.py's own docstring for
        # why), so its held-out eval is scored as crash-free rate +
        # waypoint coverage instead of a forced pass/fail. The panel
        # shows eval_crash_free_rate as the headline number.
        "eval_experiment": "shadow-agility-circuit-eval",
        "eval_metric_key": "eval_crash_free_rate",
        "eval_metric_label": "held-out crash-free rate",
    },
]

_TRAINING_TASKS_BY_KEY = {t["key"]: t for t in TRAINING_TASKS}


@bp.route("/run-training-task", methods=["POST"])
def run_training_task():
    """Registry-driven replacement for the old separate /run-training
    and /run-agility-training routes (removed same night this was
    built - nothing else referenced those two URLs, only the dashboard
    JS this was deployed alongside). Looks `task` up in TRAINING_TASKS
    rather than branching on a hardcoded if/elif per task, so a new
    registry entry needs no new route. Same real SITL+Gazebo physics,
    same "no live progress panel here, use mlflow ui" reasoning as
    before either specific route had its own docstring.
    """
    body = request.get_json(silent=True) or {}
    task = _TRAINING_TASKS_BY_KEY.get(body.get("task"))
    if task is None:
        return jsonify({"ok": False, "error": f"Unknown training task: {body.get('task')!r}"})
    args = []
    total_timesteps = body.get("total_timesteps")
    if isinstance(total_timesteps, int) and 100 <= total_timesteps <= 2_000_000:
        args += ["--total-timesteps", str(total_timesteps)]
    # reset_from_go_to (Oct 25, 2026, even later) - only honoured for a
    # task whose own registry entry opts in (today, just agility_circuit
    # - see TRAINING_TASKS). A request for a task that doesn't support
    # it is silently ignored rather than passed through to a script
    # that has no matching flag and would just error on startup.
    if body.get("reset_from_go_to") and task.get("supports_reset_from_go_to"):
        args.append("--reset-from-go-to")
    return jsonify(_run_detached(task["script"], args, lock="training"))


# ---- Drone Attributes scoring sheet (Oct 25, 2026) -------------------------
#
# Zer0 asked for a gamified "attribute system" for each drone he builds -
# an ability-score sheet that shows where it's actually strong/weak, tied
# to something real so Start Training (go_to) stops feeling like it's
# "going to waste." Every number below is DERIVED from an existing real
# source on disk, never hand-set - if a source doesn't exist yet (no
# training run, no progress.json), the attribute reports score: None and
# says why, rather than inventing a placeholder number that would look
# like real progress.

# Same file digital_lab.html's dormant Skill Tree panel already reads via
# its own /shadow/progress route (see run_skill.py: it setdefaults an
# entry here per skill, increments streak on PASS, resets to 0 on FAIL,
# and flips unlocked=True once streak hits STREAK_TO_UNLOCK=3).
PROGRESS_FILE = Path.home() / "shadow_ws" / "src" / "shadow_drone" / "progress.json"
CORE_SKILLS = ("arm", "takeoff", "go_to", "land", "hover")

# train_go_to.py's own MLflow SQLite backend (sqlite:///mlruns/mlflow.db,
# set in that script) - read-only from here, same file `mlflow ui` itself
# reads.
MLFLOW_DB = Path.home() / "shadow_ws" / "ml" / "mlruns" / "mlflow.db"

# go_to_env.py caps an episode at 300 steps; agility_circuit_env.py caps
# it at 600 (a longer course, more waypoints to chase - see that file's
# own docstring). Checked against the real metrics on Oct 25: episodes
# that end well short of their own cap consistently logged a large,
# near-constant ~-10 reward (an immediate out-of-bounds/crash penalty),
# while episodes that ran the full cap logged a much smaller, gradually-
# varying penalty (distance-to-goal, accumulated over time) - i.e. short
# episode_length is a crash, not an early success. Oct 25 (later) - now
# that there are two training tasks with two different episode-length
# caps, a single hardcoded absolute threshold (the old 250.0, meant only
# for go_to's 300-step cap) would silently mis-score agility-circuit runs
# as "crashing" far more often than they actually are. Fixed by reading
# each run's own max_episode_steps param back out of mlflow and scaling
# the threshold proportionally instead of hardcoding it.
CRASH_LEN_FRACTION = 0.8  # same margin below 300's old 250 (250/300 ~= 0.83,
                          # rounded down slightly to be a bit more forgiving)
RECENT_EPISODE_WINDOW = 20


def _core_flight_score() -> dict:
    """How many of Shadow's hand-coded flight primitives have actually
    proven themselves - the same real, git-tracked streak-of-3 unlock
    gate run_skill.py already maintains, read straight from disk."""
    try:
        progress = json.loads(PROGRESS_FILE.read_text())
    except (OSError, ValueError):
        return {
            "score": None,
            "detail": f"{PROGRESS_FILE.name} not found - run a skill via run_skill.py first",
        }

    unlocked = [name for name in CORE_SKILLS if progress.get(name, {}).get("unlocked")]
    score = round(len(unlocked) / len(CORE_SKILLS) * 100)
    detail = (
        f"{len(unlocked)}/{len(CORE_SKILLS)} core skills proven: {', '.join(unlocked)}"
        if unlocked
        else f"0/{len(CORE_SKILLS)} core skills proven yet"
    )
    return {"score": score, "detail": detail}


def _agility_score() -> dict:
    """Either training task's PPO run (go_to's Start Training, or the
    newer waypoint-circuit Start Agility Training), scored as the
    crash-free rate over the most recently started run's last 20 logged
    episodes - whichever task that most recent run happens to be.
    Deliberately not a raw SB3 reward number (not something a non-ML
    reading of this panel should have to interpret) and not "best
    episode ever" (one lucky easy goal would make an otherwise untrained
    policy look mastered) - crash-free rate is the most honest single
    number available right now: did it survive the episode without
    immediately flying out of bounds, as a percentage over the most
    recent batch. See areas/search-and-deliver-mission.md for the real
    numbers this was checked against before picking this formula.

    Oct 25 (later): reads the run's own logged max_episode_steps param
    back out of mlflow and scales the crash-length threshold off THAT,
    rather than a hardcoded absolute step count - see CRASH_LEN_FRACTION's
    own comment for why a fixed number stopped being correct the moment
    a second training task (a different episode-length cap) existed."""
    if not MLFLOW_DB.exists():
        return {"score": None, "detail": "no training run recorded yet - click Start Training"}

    try:
        conn = sqlite3.connect(str(MLFLOW_DB), timeout=2.0)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT run_uuid, name FROM runs ORDER BY start_time DESC LIMIT 1")
        latest = cur.fetchone()
        lengths: list[float] = []
        max_episode_steps = None
        if latest is not None:
            cur.execute(
                "SELECT value FROM metrics WHERE run_uuid=? AND key='episode_length' "
                "ORDER BY step ASC",
                (latest["run_uuid"],),
            )
            lengths = [row["value"] for row in cur.fetchall()]
            cur.execute(
                "SELECT value FROM params WHERE run_uuid=? AND key='max_episode_steps'",
                (latest["run_uuid"],),
            )
            param_row = cur.fetchone()
            if param_row is not None:
                try:
                    max_episode_steps = float(param_row["value"])
                except (TypeError, ValueError):
                    max_episode_steps = None
        conn.close()
    except sqlite3.Error as exc:
        return {"score": None, "detail": f"couldn't read mlflow.db: {exc}"}

    if latest is None:
        return {"score": None, "detail": "no training run recorded yet - click Start Training"}
    if not lengths:
        return {"score": None, "detail": f"run '{latest['name']}' has no completed episodes yet"}
    if max_episode_steps is None or max_episode_steps <= 0:
        # Shouldn't happen for any run logged by train_go_to.py/
        # train_agility.py (both always log this param) - but an old or
        # hand-run experiment might not have, so fail honestly rather
        # than guess a threshold for a cap we don't actually know.
        return {
            "score": None,
            "detail": f"run '{latest['name']}' didn't log max_episode_steps - can't score crash-free rate",
        }

    crash_len_threshold = max_episode_steps * CRASH_LEN_FRACTION
    window = lengths[-RECENT_EPISODE_WINDOW:]
    crash_free = sum(1 for length in window if length >= crash_len_threshold)
    score = round(crash_free / len(window) * 100)
    return {
        "score": score,
        "detail": (
            f"{crash_free}/{len(window)} of the last {len(window)} episodes "
            f"(run '{latest['name']}') completed without crashing"
        ),
    }


# deliver_payload's own real pass/fail streak - the same progress.json
# mechanism _core_flight_score() above already reads (run_skill.py
# writes an entry here for EVERY skill it runs, not just the 5
# CORE_SKILLS; deliver_payload just was never one of those 5 since it's
# a mission, not a flight primitive). An earlier pass at this doc
# flagged it as unconfirmed whether this entry even gets written for
# deliver_payload (a suspected working-directory mismatch) - checked
# directly against the real file on Oct 25 (even later) and it does:
# {'streak': 0, 'unlocked': False} after Runs 6-9's repeated
# `limits() failed` aborts. That suspicion is resolved, not just
# assumed away.
PRECISION_SKILL_KEY = "deliver_payload"
PRECISION_STREAK_TO_UNLOCK = 3  # matches run_skill.py's own STREAK_TO_UNLOCK


def _precision_score() -> dict:
    """How reliably the WHOLE search -> lock-on -> pickup -> transit ->
    drop-off -> land pipeline completes end to end without a single
    aborted/crashed phase - the most demanding number on this sheet,
    since any one phase failing fails the whole mission. Same streak-
    of-3 shape as _core_flight_score(), just scoped to one skill
    (deliver_payload) instead of five: score = how far into a clean
    streak the most recent runs have gotten, 0-100. Honest about the
    real state as of tonight: every real run so far has aborted via
    limits(), so this currently reports 0, not a fabricated number -
    see deliver_payload.log for why each one aborted."""
    try:
        progress = json.loads(PROGRESS_FILE.read_text())
    except (OSError, ValueError):
        return {
            "score": None,
            "detail": f"{PROGRESS_FILE.name} not found - run the Deliver Payload mission first",
        }

    entry = progress.get(PRECISION_SKILL_KEY)
    if entry is None:
        return {
            "score": None,
            "detail": "no Deliver Payload run recorded yet - run it from Mission Control first",
        }

    streak = entry.get("streak", 0)
    unlocked = entry.get("unlocked", False)
    score = round(min(streak, PRECISION_STREAK_TO_UNLOCK) / PRECISION_STREAK_TO_UNLOCK * 100)

    if unlocked:
        detail = f"proven reliable - hit a {PRECISION_STREAK_TO_UNLOCK}+ clean-delivery streak at some point"
        if streak == 0:
            detail += " (current streak is back to 0 after a more recent miss)"
    elif streak > 0:
        detail = f"streak {streak}/{PRECISION_STREAK_TO_UNLOCK} clean deliveries - not proven reliable yet"
    else:
        detail = f"0/{PRECISION_STREAK_TO_UNLOCK} - every run so far has aborted before finishing (see deliver_payload.log)"

    return {"score": score, "detail": detail}


def _stability_score() -> dict:
    """Consistency of flight, not raw performance - a deliberately
    different question from AGILITY's crash-free RATE above, computed
    from the exact same already-logged episode_length metrics (whichever
    training run was started most recently across any experiment - same
    run _agility_score() itself reads, so the panel's AGILITY/STABILITY
    pair are always talking about the same run). AGILITY asks "what
    fraction of recent episodes survived"; STABILITY asks "how
    consistent is that, episode to episode" - a policy whose episode
    lengths swing wildly (crashing almost instantly on some episodes,
    flying the full length on others) is genuinely less stable than one
    that's merely mediocre but consistent, even if the two could share
    the same crash-free percentage.

    Measured as 100 * (1 - coefficient of variation) over the run's
    last RECENT_EPISODE_WINDOW episode lengths (stdev / mean), with the
    CV clamped to [0, 1] first so a wildly erratic run floors at 0
    rather than going negative. Not PID-autotune-based - see
    run_autotune()'s own docstring for why that source is still dead
    for this ArduPilot/Harmonic stack; this uses a source that's real
    and already on disk instead of waiting on that migration fix.

    Checked Oct 25 (even later) against the real agility-circuit data on
    the machine: a run with lengths swinging 600/600/600/600/505/1/1/1/
    600/600/600 (three near-instant crashes mixed with full-length laps)
    scores 39; a hypothetical steady run varying only in the 590-610
    range scores 99 - the spread this is meant to catch is a real
    pattern seen in Shadow's own data, not a hypothetical worked out on
    paper."""
    if not MLFLOW_DB.exists():
        return {"score": None, "detail": "no training run recorded yet - click Start on a training task"}

    try:
        conn = sqlite3.connect(str(MLFLOW_DB), timeout=2.0)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT run_uuid, name FROM runs ORDER BY start_time DESC LIMIT 1")
        latest = cur.fetchone()
        lengths: list[float] = []
        if latest is not None:
            cur.execute(
                "SELECT value FROM metrics WHERE run_uuid=? AND key='episode_length' "
                "ORDER BY step ASC",
                (latest["run_uuid"],),
            )
            lengths = [row["value"] for row in cur.fetchall()]
        conn.close()
    except sqlite3.Error as exc:
        return {"score": None, "detail": f"couldn't read mlflow.db: {exc}"}

    if latest is None:
        return {"score": None, "detail": "no training run recorded yet - click Start on a training task"}

    window = lengths[-RECENT_EPISODE_WINDOW:]
    if len(window) < 2:
        return {
            "score": None,
            "detail": f"run '{latest['name']}' doesn't have enough completed episodes yet to measure consistency",
        }

    mean_len = statistics.fmean(window)
    if mean_len <= 0:
        return {"score": None, "detail": f"run '{latest['name']}' has no usable episode-length data yet"}

    stdev_len = statistics.pstdev(window)
    coefficient_of_variation = min(stdev_len / mean_len, 1.0)
    score = round(100 * (1 - coefficient_of_variation))
    return {
        "score": score,
        "detail": (
            f"episode length varied ~{stdev_len:.0f} steps around a {mean_len:.0f}-step mean "
            f"over the last {len(window)} episodes (run '{latest['name']}') - "
            f"{'steady' if score >= 70 else 'erratic'} control"
        ),
    }


@bp.route("/attributes", methods=["GET"])
def attributes():
    """Real, derived scoring-sheet data for the Simulation Bay's Drone
    Attributes panel. All four attributes are wired to a real source as
    of Oct 25, 2026 (even later): AGILITY and CORE FLIGHT shipped first
    (see each one's own docstring above); PRECISION (deliver_payload's
    own progress.json streak) and STABILITY (training's own episode-
    length consistency, not PID autotune - see _stability_score()'s own
    docstring for why) were added the same night once a real source was
    confirmed on disk for each, rather than being guessed at. If a
    future attribute's source genuinely doesn't exist yet, it still
    belongs in not_yet_wired below rather than a fabricated number -
    this list staying empty right now reflects real state, not a
    relaxed rule."""
    return jsonify({
        "ok": True,
        "vehicle": "Shadow MK1",
        "attributes": {
            "agility": _agility_score(),
            "core_flight": _core_flight_score(),
            "precision": _precision_score(),
            "stability": _stability_score(),
        },
        "not_yet_wired": [],
    })


def _training_task_stats(experiment_name: str) -> dict:
    """Same crash-free-rate formula as _agility_score() above (see that
    function's own docstring for the full reasoning and the real
    numbers it was checked against), but scoped to ONE experiment's own
    most recent run rather than whichever run across ALL experiments
    started most recently. _agility_score() answers "how good is
    Shadow's agility right now" (one number, for the attribute sheet);
    this answers "how is THIS specific task's own checkpoint doing"
    (one number per task, for the training panel) - different
    questions, so this is a separate function rather than a refactor of
    the first, to avoid changing already-deployed, already-working
    scoring logic while building something new next to it."""
    if not MLFLOW_DB.exists():
        return {"has_run": False, "detail": "never run yet - click Start"}

    try:
        conn = sqlite3.connect(str(MLFLOW_DB), timeout=2.0)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT experiment_id FROM experiments WHERE name=?", (experiment_name,))
        exp_row = cur.fetchone()
        if exp_row is None:
            conn.close()
            return {"has_run": False, "detail": "never run yet - click Start"}

        cur.execute(
            "SELECT run_uuid, name, status FROM runs WHERE experiment_id=? "
            "ORDER BY start_time DESC LIMIT 1",
            (exp_row["experiment_id"],),
        )
        latest = cur.fetchone()
        if latest is None:
            conn.close()
            return {"has_run": False, "detail": "never run yet - click Start"}

        cur.execute(
            "SELECT value FROM metrics WHERE run_uuid=? AND key='episode_length' ORDER BY step ASC",
            (latest["run_uuid"],),
        )
        lengths = [row["value"] for row in cur.fetchall()]

        cur.execute("SELECT key, value FROM params WHERE run_uuid=?", (latest["run_uuid"],))
        params = {row["key"]: row["value"] for row in cur.fetchall()}
        conn.close()
    except sqlite3.Error as exc:
        return {"has_run": False, "detail": f"couldn't read mlflow.db: {exc}"}

    result: dict = {
        "has_run": True,
        "run_name": latest["name"],
        "run_status": latest["status"],
        "episode_count": len(lengths),
        # None here means "predates the Oct 25 checkpoint-resume fix" -
        # that param simply didn't exist to log yet on an older run,
        # not a fault in this run specifically. The panel shows that
        # as "unknown", never as "no".
        "resumed_from_checkpoint": params.get("resumed_from_checkpoint"),
    }

    max_episode_steps = None
    try:
        max_episode_steps = float(params["max_episode_steps"])
    except (KeyError, TypeError, ValueError):
        pass

    if not lengths:
        result["crash_free_pct"] = None
        result["detail"] = f"run '{latest['name']}' has no completed episodes yet"
    elif max_episode_steps is None or max_episode_steps <= 0:
        result["crash_free_pct"] = None
        result["detail"] = f"run '{latest['name']}' didn't log max_episode_steps"
    else:
        crash_len_threshold = max_episode_steps * CRASH_LEN_FRACTION
        window = lengths[-RECENT_EPISODE_WINDOW:]
        crash_free = sum(1 for length in window if length >= crash_len_threshold)
        pct = round(crash_free / len(window) * 100)
        result["crash_free_pct"] = pct
        result["detail"] = (
            f"{crash_free}/{len(window)} of the last {len(window)} episodes "
            f"(run '{latest['name']}') completed without crashing"
        )

    return result


def _format_eval_detail(task: dict, metrics: dict) -> str:
    """Builds the human sentence for an eval result by reading whichever
    eval_* metrics that run actually logged, rather than only ever
    showing the one metric a task is configured with as its headline.
    Caught live (Oct 26, 2026, even later): a 70% crash-free rate told
    Zer0 nothing about whether that circuit run actually reached any of
    the real payload waypoints - eval_checkpoint.py's run_agility_eval()
    was already computing and logging eval_mean_waypoints_reached and
    eval_lap_completion_rate right alongside crash-free rate, this just
    never read them back out past the single configured metric."""
    parts = []
    headline_value = metrics.get(task["eval_metric_key"])
    if headline_value is not None:
        parts.append(f"{task['eval_metric_label']}: {headline_value}%")
    if "eval_mean_waypoints_reached" in metrics:
        parts.append(f"avg {metrics['eval_mean_waypoints_reached']} waypoints reached per episode")
    if "eval_lap_completion_rate" in metrics:
        parts.append(f"{metrics['eval_lap_completion_rate']}% of episodes completed a full lap")
    if "eval_success_rate" in metrics and task["eval_metric_key"] != "eval_success_rate":
        parts.append(f"{metrics['eval_success_rate']}% reached the goal")
    if "eval_crash_rate" in metrics and task["eval_metric_key"] != "eval_crash_rate":
        parts.append(f"{metrics['eval_crash_rate']}% crashed")
    episode_count = metrics.get("eval_episode_count")
    detail = ", ".join(parts) if parts else "evaluated, but no metrics were logged"
    if episode_count:
        detail += f" (over {int(episode_count)} held-out episodes)"
    return detail


def _evaluation_status(task: dict) -> dict:
    """Status for any 'Evaluate' button pointed at an EVAL_TASKS entry -
    the Training panel's Waypoint Circuit card, and the Skill Tests'
    Learned Flight / Waypoint Circuit (skill test) rows - all three call
    this the same way, passing in EVAL_TASKS[key] rather than their own
    shape, so this only ever needs checkpoint_path/eval_experiment/
    eval_metric_key/eval_metric_label, nothing display-specific. Reads
    the held-out, deterministic result eval_checkpoint.py logged to
    that eval_experiment, if any, with one honesty check on top of the
    usual "no run yet" handling: the checkpoint file's CURRENT mtime is
    compared against the mtime eval_checkpoint.py logged as a param at
    evaluation time. If they differ, the checkpoint has been retrained
    (or re-reset) since that evaluation ran, so the old pass rate no
    longer describes the checkpoint that exists now - stale=True, and
    the panel shows that instead of a number that looks current but
    isn't.
    """
    checkpoint_path = task["checkpoint_path"]
    if not checkpoint_path.exists():
        return {"has_eval": False, "eval_detail": "no checkpoint to evaluate yet - train this task first"}

    if not MLFLOW_DB.exists():
        return {"has_eval": False, "eval_detail": "never evaluated yet - click Evaluate"}

    try:
        conn = sqlite3.connect(str(MLFLOW_DB), timeout=2.0)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT experiment_id FROM experiments WHERE name=?", (task["eval_experiment"],))
        exp_row = cur.fetchone()
        if exp_row is None:
            conn.close()
            return {"has_eval": False, "eval_detail": "never evaluated yet - click Evaluate"}

        cur.execute(
            "SELECT run_uuid, start_time FROM runs WHERE experiment_id=? "
            "ORDER BY start_time DESC LIMIT 1",
            (exp_row["experiment_id"],),
        )
        latest = cur.fetchone()
        if latest is None:
            conn.close()
            return {"has_eval": False, "eval_detail": "never evaluated yet - click Evaluate"}

        cur.execute("SELECT key, value FROM params WHERE run_uuid=?", (latest["run_uuid"],))
        params = {row["key"]: row["value"] for row in cur.fetchall()}
        cur.execute("SELECT key, value FROM metrics WHERE run_uuid=?", (latest["run_uuid"],))
        metrics = {row["key"]: row["value"] for row in cur.fetchall()}
        conn.close()
    except sqlite3.Error as exc:
        return {"has_eval": False, "eval_detail": f"couldn't read mlflow.db: {exc}"}

    evaluated_mtime = None
    try:
        evaluated_mtime = float(params.get("checkpoint_mtime"))
    except (TypeError, ValueError):
        pass

    current_mtime = checkpoint_path.stat().st_mtime
    stale = evaluated_mtime is None or abs(current_mtime - evaluated_mtime) > 1.0  # 1s float-precision margin

    metric_value = metrics.get(task["eval_metric_key"])

    return {
        "has_eval": True,
        "eval_stale": stale,
        "eval_metric_label": task["eval_metric_label"],
        "eval_metric_value": metric_value,
        "eval_episode_count": metrics.get("eval_episode_count"),
        # Every eval_* metric that run actually logged, not just the
        # one headline number - lets a future UI show all of it, not
        # only whatever _format_eval_detail() chose to put in the
        # sentence below.
        "eval_metrics": {k: v for k, v in metrics.items() if k.startswith("eval_")},
        "eval_detail": (
            "checkpoint retrained since this evaluation - re-run Evaluate"
            if stale else
            _format_eval_detail(task, metrics)
        ),
    }


#  ---- Skill tests (Oct 26, 2026) - Basic Skills / Sequences buttons ---------
#
# Zer0's ask: he was running these one at a time by hand in a terminal
# (ros2 run shadow_drone run_skill.py <skill>) and wanted a UI button
# for it in the Training panel instead, nested into two categories -
# Basic Skills (the five hand-coded flight primitives) and Sequences
# (the longer, multi-phase Skills). Same allowlist-by-dict pattern as
# ALLOWED_MISSIONS/TRAINING_TASKS above: a button's key picks a known,
# pre-approved arg list here, never passed straight through to bash
# from the request body. "args" mirrors run_mission.sh's own choices
# for go_to/takeoff (a fixed 1m offset, 2.0m altitude) rather than
# inventing new defaults.
SKILL_TESTS = [
    {"key": "arm", "name": "Arm", "category": "basic", "args": []},
    {"key": "takeoff", "name": "Takeoff", "category": "basic", "args": ["--altitude", "2.0"]},
    {"key": "hover", "name": "Hover", "category": "basic", "args": ["--duration", "5"]},
    {"key": "go_to", "name": "Go To", "category": "basic", "args": ["--x", "1.0", "--y", "0.0", "--z", "2.0"]},
    {"key": "land", "name": "Land", "category": "basic", "args": []},
    # Sequences - the longer, multi-phase Skills. These are the SAME
    # run_skill.py entries Mission Control's "Run Mission" dropdown
    # already launches (via run_deliver_payload.sh/run_learned_flight.sh) -
    # this just gives them a second, more granular home under Training
    # too, since that's where Zer0 thinks about "testing a skill" from.
    # Nothing here replaces or changes Mission Control's own dropdown.
    {"key": "deliver_payload", "name": "Deliver Payload", "category": "sequences", "args": []},
    # learned_flight and waypoint_circuit are the two Skill Tests
    # actually flown by a trained policy's forward pass rather than
    # hand-coded control math (run_skill.py's SKILLS dict points both
    # at the same LearnedFlightSkill class - see that file's own
    # comment - just handed a different checkpoint each). Those are
    # the only two with "eval_task_key" set below: a hand-coded skill
    # either satisfies its own requirements()/limits() or it doesn't,
    # already fully captured by pass/fail, so arm/takeoff/hover/go_to/
    # land/deliver_payload get no Evaluate button - only a skill whose
    # behaviour comes from a trained checkpoint needs a held-out check
    # of whether that checkpoint is actually any good.
    {"key": "learned_flight", "name": "Learned Flight (trained policy)", "category": "sequences", "args": [], "eval_task_key": "go_to", "train_task_key": "go_to"},
    # Oct 26, 2026 (even later still) - "train_task_key" added when the
    # Training panel's "Train: Waypoint Circuit" card was removed outright
    # (Zer0's third, unambiguous ask - he'd rather this one surface live
    # here than as a second card that just repeats this row's own name).
    # Points at TRAINING_TASKS["agility_circuit"], whose Start button is
    # still the only thing that actually gradient-updates this policy -
    # see /skill-tests below, which now folds that task's checkpoint/
    # training stats into this one row instead of a separate card.
    {"key": "waypoint_circuit", "name": "Waypoint Circuit (trained policy)", "category": "sequences", "args": [], "eval_task_key": "agility_circuit", "train_task_key": "agility_circuit"},
]
_SKILL_TESTS_BY_KEY = {t["key"]: t for t in SKILL_TESTS}


@bp.route("/run-skill-test", methods=["POST"])
def run_skill_test():
    """Launches run_skill_test.sh for ONE entry in SKILL_TESTS - the
    Training panel's new Basic Skills / Sequences buttons. Shares
    run_mission.sh's own lock file (run_mission.lock) - see
    run_skill_test.sh's own header for why - so this correctly refuses
    to start while a mission sequence (or another skill test) is
    already flying Shadow, and vice versa.
    """
    body = request.get_json(silent=True) or {}
    test = _SKILL_TESTS_BY_KEY.get(body.get("skill"))
    if test is None:
        return jsonify({"ok": False, "error": f"Unknown skill test: {body.get('skill')!r}"})
    return jsonify(_run_detached("run_skill_test.sh", [test["key"], "--", *test["args"]], lock="mission"))


@bp.route("/skill-tests", methods=["GET"])
def skill_tests():
    """Status feed for the Training panel's Basic Skills / Sequences
    buttons - each test's category plus its live streak/unlocked state
    read straight from progress.json, same file _core_flight_score()
    above already reads, so these numbers always agree with the Drone
    Attributes panel's CORE FLIGHT score. Never 500s if progress.json
    doesn't exist yet - same "no data yet is normal" handling as every
    other read in this file."""
    try:
        progress = json.loads(PROGRESS_FILE.read_text())
    except (OSError, ValueError):
        progress = {}

    tests = []
    for test in SKILL_TESTS:
        entry = progress.get(test["key"], {})
        row = {
            "key": test["key"],
            "name": test["name"],
            "category": test["category"],
            "streak": entry.get("streak", 0),
            "unlocked": entry.get("unlocked", False),
        }
        eval_task_key = test.get("eval_task_key")
        if eval_task_key:
            row["eval_task_key"] = eval_task_key
            row.update(_evaluation_status(EVAL_TASKS[eval_task_key]))
        # Oct 26, 2026 (even later still) - folds the former standalone
        # Training panel card's own info into this row (see
        # "train_task_key" on SKILL_TESTS above): checkpoint existence,
        # whether the last training run resumed from a prior checkpoint,
        # and that run's crash-free stats. _training_task_stats()'s own
        # keys (has_run/run_name/run_status/episode_count/
        # resumed_from_checkpoint/crash_free_pct/detail) don't collide
        # with _evaluation_status()'s (has_eval/eval_stale/
        # eval_metric_value/eval_metric_label/eval_detail) above, so
        # both merge into the same row safely.
        train_task_key = test.get("train_task_key")
        if train_task_key:
            train_task = _TRAINING_TASKS_BY_KEY[train_task_key]
            row["train_task_key"] = train_task_key
            row["checkpoint_exists"] = train_task["checkpoint_path"].exists()
            row["supports_reset_from_go_to"] = train_task.get("supports_reset_from_go_to", False)
            row.update(_training_task_stats(train_task["mlflow_experiment"]))
        tests.append(row)
    return jsonify({"ok": True, "tests": tests})


@bp.route("/training-tasks", methods=["GET"])
def training_tasks():
    """Status feed for the Simulation Bay's new Training panel (Oct 25,
    2026, later) - one row per TRAINING_TASKS entry, each with whether
    a checkpoint already exists on disk and that task's own most
    recent run's crash-free stats (see _training_task_stats() above).
    Read-only, tolerates every missing-file/no-run-yet case the same
    way attributes() already does - never 500s the page just because a
    task hasn't been trained yet."""
    tasks = []
    for task in TRAINING_TASKS:
        stats = _training_task_stats(task["mlflow_experiment"])
        tasks.append({
            "key": task["key"],
            "name": task["name"],
            "description": task["description"],
            "feeds_attributes": task["feeds_attributes"],
            "checkpoint_exists": task["checkpoint_path"].exists(),
            "log_file": task["log_file"],
            "supports_reset_from_go_to": task.get("supports_reset_from_go_to", False),
            **stats,
            **_evaluation_status(task),
        })
    return jsonify({"ok": True, "tasks": tasks})


@bp.route("/run-checkpoint-eval", methods=["POST"])
def run_checkpoint_eval():
    """Launches run_checkpoint_eval.sh for ONE EVAL_TASKS entry - the
    Training panel's Waypoint Circuit 'Evaluate' button AND the Skill
    Tests' Learned Flight / Waypoint Circuit (skill test) 'Evaluate'
    buttons, all three pointed at this same registry now (Oct 26, 2026,
    even later) rather than TRAINING_TASKS specifically, since go_to's
    own training card was removed but its checkpoint can still be
    evaluated from Learned Flight's button. Same allowlist-by-dict
    pattern as every other launch route here: the button's task key
    picks a known entry, never passed straight through to bash from the
    request body."""
    body = request.get_json(silent=True) or {}
    task_key = body.get("task")
    if task_key not in EVAL_TASKS:
        return jsonify({"ok": False, "error": f"Unknown eval task: {task_key!r}"})
    return jsonify(_run_detached("run_checkpoint_eval.sh", [task_key], lock="training"))


@bp.route("/run-skill-test-and-eval", methods=["POST"])
def run_skill_test_and_eval():
    """Launches run_skill_test_and_eval.sh for ONE SKILL_TESTS entry
    that has an eval_task_key - the Sequences section's combined 'Run &
    Evaluate' button for Learned Flight / Waypoint Circuit (skill test)
    (Oct 26, 2026, even later - Zer0's own ask: "it's both doing the
    same thing... I just want to click one button"). Chains the exact
    same skill-test flight and held-out eval batch that already existed
    as two separate buttons - see that script's own header for why
    sequencing them in one script is safe (different lock files,
    strictly one after the other, never concurrent). Same allowlist-by-
    dict pattern as every other launch route here.
    """
    body = request.get_json(silent=True) or {}
    test = _SKILL_TESTS_BY_KEY.get(body.get("skill"))
    if test is None or not test.get("eval_task_key"):
        return jsonify({"ok": False, "error": f"Unknown or non-evaluable skill test: {body.get('skill')!r}"})
    return jsonify(_run_detached(
        "run_skill_test_and_eval.sh",
        [test["key"], test["eval_task_key"], "--", *test["args"]],
        lock="mission",
    ))


# checkpoint_eval.log is shared by EVERY Evaluate click ever made (any
# task, any button) - run_checkpoint_eval.sh always appends to the same
# file, never its own per-run file. /eval-log below scopes itself to
# whatever's after the LAST "starting eval_checkpoint.py" line so a
# live feed never shows a previous run's stale episodes.
EVAL_LOG_FILE = Path.home() / "shadow_sim_runtime" / "logs" / "checkpoint_eval.log"

# Matches eval_checkpoint.py's own per-episode print lines exactly -
# see that file's run_go_to_eval()/run_agility_eval(). go_to's line has
# no waypoints_reached=... segment; agility_circuit's does - the whole
# group is optional so one pattern reads both.
_EVAL_EPISODE_RE = re.compile(
    r"\[eval_checkpoint\] \S+ seed=(?P<seed>\d+): reason=(?P<reason>\S+)"
    r"(?: waypoints_reached=(?P<waypoints_reached>\d+))? reward=(?P<reward>-?[\d.]+) length=(?P<length>\d+)"
)

# Oct 26, 2026 (even later still again) - same "live progress feed off
# the log, not a new mechanism" idea as /eval-log below, this time for
# Train: Zer0's own ask - "maybe I could see a progress bar... when
# it's nearly complete" - train_go_to.py/train_agility.py's own
# MLflowEpisodeLogger now prints timesteps=self.num_timesteps on every
# episode line (SB3's own cumulative step counter), and the "Starting
# PPO for N timesteps" line already printed before model.learn() is
# both this run's own start marker (same "only the current run, not a
# stale one" scoping /eval-log already uses) AND where total_timesteps
# comes from - no separate param needed, the frontend doesn't have to
# already know what a given Train click asked for.
_TRAIN_START_RE = re.compile(r"Starting PPO for (?P<total>\d+) timesteps")
# Oct 26, 2026 (even later still again, caught live #2) - real bug, caught
# from Zer0's own screenshot: /train-log used to anchor start_at on the
# LAST "Starting PPO for N timesteps" line in the whole file, but that
# line is printed by train_go_to.py/train_agility.py itself, only after
# rclpy/ROS2 import + connecting to the live SITL/Gazebo session + loading
# the existing checkpoint - which can easily take 10-60+ real seconds.
# Click Train again during that window and the feed was still anchored on
# the PREVIOUS run's own "Starting PPO"/"Done. Final model saved" pair,
# so it showed "Training complete" with the old run's episodes while a
# brand new one was already flying Shadow in the sim view. Fixed by
# anchoring instead on run_training.sh/run_agility_training.sh's own
# "starting train_*.py" line - printed the INSTANT the lock file is
# grabbed, before any of that slow setup - same "wrapper's own immediate
# marker, not the script's first real print" idea /eval-log's own
# "starting eval_checkpoint.py" anchor already uses.
_TRAIN_WRAPPER_START_RE = re.compile(r"\[run_\S+\.sh\] .*: starting (?P<py_script>train_\S+\.py)")
_TRAIN_EPISODE_RE = re.compile(
    r"episode (?P<episode>\d+): reward=(?P<reward>-?[\d.]+) length=(?P<length>\d+)"
    r"(?: reason=(?P<reason>\S+))?(?: waypoints=(?P<waypoints>\d+))? timesteps=(?P<timesteps>\d+)"
)


@bp.route("/eval-log", methods=["GET"])
def eval_log():
    """Tails checkpoint_eval.log for the Skill Tests' live 'Run &
    Evaluate' progress feed - same read-only tail-a-log pattern as
    /mind-log above, but parsing eval_checkpoint.py's own per-episode
    print lines into structured events (seed/reason/reward/length,
    plus waypoints_reached for agility_circuit) instead of raw JSON
    lines, so the UI can show a progress count and a scrolling feed
    without its own regex. Never errors the page if evaluation hasn't
    started yet or the log doesn't exist."""
    if not EVAL_LOG_FILE.exists():
        return jsonify({"ok": True, "started": False, "done": False, "error": None, "episodes": []})

    try:
        lines = EVAL_LOG_FILE.read_text().splitlines()
    except OSError as exc:
        return jsonify({"ok": False, "error": str(exc), "started": False, "done": False, "episodes": []})

    start_at = 0
    for i, line in enumerate(lines):
        if "starting eval_checkpoint.py" in line:
            start_at = i
    recent = lines[start_at:]

    episodes, done, error = [], False, None
    for line in recent:
        match = _EVAL_EPISODE_RE.search(line)
        if match:
            episodes.append({
                "seed": match.group("seed"),
                "reason": match.group("reason"),
                "reward": float(match.group("reward")),
                "length": int(match.group("length")),
                "waypoints_reached": (
                    int(match.group("waypoints_reached"))
                    if match.group("waypoints_reached") is not None else None
                ),
            })
        elif "eval_checkpoint.py exited 0" in line:
            done = True
        elif "aborting" in line or "Never got" in line or "No checkpoint found" in line:
            error = line.rsplit("] ", 1)[-1] if "] " in line else line

    return jsonify({
        "ok": True,
        "started": len(recent) > 1,
        "done": done,
        "error": error,
        "episodes": episodes,
    })


@bp.route("/train-log", methods=["GET"])
def train_log():
    """Tails whichever TRAINING_TASKS entry's own log file for the Train
    button's new live progress feed - same read-a-log-while-it-runs idea
    as /eval-log above, just scoped to a training run instead of an
    eval batch. Progress is real: total_timesteps comes straight out of
    this run's own "Starting PPO for N timesteps" line (so the frontend
    never has to already know what total_timesteps a given click used),
    and the "current" position is the latest episode's own
    timesteps=self.num_timesteps - SB3's own cumulative counter, not an
    estimate. Never errors the page if training hasn't started yet or
    the log doesn't exist, same tolerance every other read in this file
    already has."""
    task_key = request.args.get("task")
    if task_key not in _TRAINING_TASKS_BY_KEY:
        return jsonify({"ok": False, "error": f"Unknown training task: {task_key!r}", "episodes": []})

    log_path = Path.home() / "shadow_sim_runtime" / "logs" / _TRAINING_TASKS_BY_KEY[task_key]["log_file"]
    if not log_path.exists():
        return jsonify({
            "ok": True, "started": False, "done": False, "error": None,
            "total_timesteps": None, "episodes": [],
        })

    try:
        lines = log_path.read_text(errors="replace").splitlines()
    except OSError as exc:
        return jsonify({"ok": False, "error": str(exc), "started": False, "done": False, "episodes": []})

    # Anchor on the WRAPPER's own immediate "starting train_*.py" line,
    # not train_go_to.py/train_agility.py's own later "Starting PPO for
    # N timesteps" print - see _TRAIN_WRAPPER_START_RE's own comment for
    # why (the latter can lag the actual process start by a minute or
    # more, during which this used to keep reporting the PREVIOUS run's
    # own "done" state).
    start_at = 0
    for i, line in enumerate(lines):
        if _TRAIN_WRAPPER_START_RE.search(line):
            start_at = i
    recent = lines[start_at:]

    # total_timesteps only comes from a "Starting PPO" line AFTER that
    # anchor - if the new run hasn't reached it yet, this correctly stays
    # None (frontend shows "Training started..." rather than a stale
    # total from whatever run happened to log one last).
    total_timesteps = None
    for line in recent:
        match = _TRAIN_START_RE.search(line)
        if match:
            total_timesteps = int(match.group("total"))

    episodes, done, error = [], False, None
    for line in recent:
        match = _TRAIN_EPISODE_RE.search(line)
        if match:
            episodes.append({
                "episode": int(match.group("episode")),
                "reward": float(match.group("reward")),
                "length": int(match.group("length")),
                "reason": match.group("reason"),
                "waypoints": int(match.group("waypoints")) if match.group("waypoints") is not None else None,
                "timesteps": int(match.group("timesteps")),
            })
        elif "Done. Final model saved" in line:
            done = True
        elif "already in progress" in line:
            error = line.rsplit("] ", 1)[-1] if "] " in line else line
        elif "aborting before starting training" in line or "Never got" in line:
            error = line.rsplit("] ", 1)[-1] if "] " in line else line

    return jsonify({
        "ok": True,
        "started": len(recent) > 1,
        "done": done,
        "error": error,
        "total_timesteps": total_timesteps,
        "episodes": episodes,
    })


def _eval_run_episode_breakdown(log_lines, starts, run_start_ms, window_sec=180):
    """Oct 26, 2026 (even later still again, research pass) - Zer0's own
    ask after seeing a bare "0%" with no way to tell WHY: tallies one
    past Evaluate run's own episodes by termination reason (arrived /
    limits_violation / timeout / lost_position_estimate), instead of
    just the single aggregate percentage _evaluation_status()/
    eval_history() already return. Reuses checkpoint_eval.log exactly
    the way _event_log_context() already reuses the skill/mission logs
    for the in-depth report feature: nearest-timestamp matching, not an
    exact guess, since nothing in mlflow records which log segment a
    given run's own episodes landed in.

    starts is a pre-scanned list of (line_index, parsed_timestamp) for
    every "starting eval_checkpoint.py --task <this task>" line in
    log_lines - computed once per request by the caller rather than
    re-scanning the whole file per run, since a request can ask for up
    to 20 runs at once.
    """
    if not starts:
        return {}
    try:
        target = datetime.fromtimestamp(run_start_ms / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return {}

    best_idx, best_delta = None, None
    for idx, ts in starts:
        delta = abs((ts - target).total_seconds())
        if delta > window_sec:
            continue
        if best_delta is None or delta < best_delta:
            best_idx, best_delta = idx, delta
    if best_idx is None:
        return {}

    end_idx = len(log_lines)
    for idx, _ in starts:
        if idx > best_idx:
            end_idx = idx
            break

    counts = {}
    for line in log_lines[best_idx:end_idx]:
        match = _EVAL_EPISODE_RE.search(line)
        if match:
            reason = match.group("reason")
            counts[reason] = counts.get(reason, 0) + 1
    return counts


@bp.route("/eval-history", methods=["GET"])
def eval_history():
    """Every past Evaluate run for ONE EVAL_TASKS entry, oldest first -
    not just the latest one _evaluation_status() reads. This is what
    answers "is it actually getting better": the Training Log's
    Evaluations tab plots this task's headline metric across however
    many times Evaluate has been clicked, not only the most recent
    number (Oct 26, 2026, even later - Zer0's own ask). Each run also
    carries an "episode_breakdown" (see _eval_run_episode_breakdown
    above) - Zer0's own follow-up ask once he actually saw a bare "0%"
    on screen and had no way to tell whether that meant every episode
    crashed, every episode timed out lost, or something else entirely."""
    task_key = request.args.get("task")
    if task_key not in EVAL_TASKS:
        return jsonify({"ok": False, "error": f"Unknown eval task: {task_key!r}", "runs": []})
    task = EVAL_TASKS[task_key]

    if not MLFLOW_DB.exists():
        return jsonify({"ok": True, "task_key": task_key, "eval_metric_label": task["eval_metric_label"], "runs": []})

    try:
        conn = sqlite3.connect(str(MLFLOW_DB), timeout=2.0)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT experiment_id FROM experiments WHERE name=?", (task["eval_experiment"],))
        exp_row = cur.fetchone()
        if exp_row is None:
            conn.close()
            return jsonify({"ok": True, "task_key": task_key, "eval_metric_label": task["eval_metric_label"], "runs": []})

        cur.execute(
            "SELECT run_uuid, start_time FROM runs WHERE experiment_id=? "
            "ORDER BY start_time DESC LIMIT 20",
            (exp_row["experiment_id"],),
        )
        run_rows = cur.fetchall()

        runs = []
        for run_row in run_rows:
            cur.execute("SELECT key, value FROM metrics WHERE run_uuid=?", (run_row["run_uuid"],))
            metrics = {row["key"]: row["value"] for row in cur.fetchall()}
            runs.append({
                "run_uuid": run_row["run_uuid"],
                "start_time": run_row["start_time"],
                "metric_value": metrics.get(task["eval_metric_key"]),
                "metrics": {k: v for k, v in metrics.items() if k.startswith("eval_")},
            })
        conn.close()
    except sqlite3.Error as exc:
        return jsonify({"ok": False, "error": f"couldn't read mlflow.db: {exc}", "runs": []})

    # One read of checkpoint_eval.log for every run this request is
    # about to return, rather than one read per run - this file is
    # shared by every Evaluate click ever made (any task, any button),
    # so it's scanned once for every "starting eval_checkpoint.py
    # --task <task_key>" line, and each run below just finds its own
    # nearest match in that pre-scanned list.
    try:
        log_lines = EVAL_LOG_FILE.read_text(errors="replace").splitlines() if EVAL_LOG_FILE.exists() else []
    except OSError:
        log_lines = []
    start_marker = f"starting eval_checkpoint.py --task {task_key}"
    starts = []
    for i, line in enumerate(log_lines):
        if start_marker not in line:
            continue
        date_match = _BASH_DATE_RE.search(line)
        if date_match is None:
            continue
        parsed = _parse_bash_date(date_match.group(1))
        if parsed is not None:
            starts.append((i, parsed))
    for run in runs:
        run["episode_breakdown"] = _eval_run_episode_breakdown(log_lines, starts, run["start_time"])

    runs.reverse()  # oldest first - a trend reads left-to-right chronologically
    return jsonify({"ok": True, "task_key": task_key, "eval_metric_label": task["eval_metric_label"], "runs": runs})


# ---- In-depth event report (Oct 26, 2026, even later still) ----------------
#
# Zer0's own ask: the Events timeline already shows a one-line reason
# ("waypoint_circuit - limits() failed - aborted for safety") - this
# answers "show me more" for one specific event, by pulling the real
# raw log lines surrounding it from whichever log file that event's
# script actually wrote to, rather than inventing a second summarised
# layer on top of the first. Genuinely generated from the logs on
# disk, not a canned explanation per failure reason string.
#
# Deliberately coarse about WHICH file: a skill name can appear in more
# than one log depending on how it was launched (Mission Control's
# flight-skills smoke test runs arm/takeoff/go_to/land through
# run_mission.sh into mission.log; the exact same skill names clicked
# individually from Skill Tests go through run_skill_test.sh into
# skill_test.log) and skill_attempts/mission_events don't record which
# script launched them - so rather than guess wrong, this searches
# every plausible file for the given key and keeps whichever match's
# own nearby timestamp lands closest to the event's real timestamp.
EVENT_LOG_DIR = Path.home() / "shadow_sim_runtime" / "logs"
MISSION_LOG_FILES = {
    "flight_smoke": ["mission.log"],
    "deliver_payload": ["deliver_payload.log"],
    "learned_flight": ["learned_flight.log"],
}
SKILL_LOG_FILES = ["skill_test.log", "mission.log", "skill_test_and_eval.log"]

# Matches the $(date)-produced timestamp every run_*.sh script prefixes
# its own log lines with, e.g. "Mon 26 Oct 04:13:21 GMT 2026" - the
# machine's own locale only ever produces GMT or BST (it's a UK clock,
# British Summer Time ended partway through this very session), so
# those are the only two abbreviations handled.
_BASH_DATE_RE = re.compile(
    r"\b((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) "
    r"\d{2}:\d{2}:\d{2} (?:GMT|BST) \d{4})\b"
)
_TZ_OFFSET_HOURS = {"GMT": 0, "BST": 1}


def _parse_bash_date(raw: str) -> datetime | None:
    parts = raw.split()  # ['Mon','26','Oct','04:13:21','GMT','2026']
    if len(parts) != 6:
        return None
    tz_abbr = parts[4]
    try:
        naive = datetime.strptime(f"{parts[0]} {parts[1]} {parts[2]} {parts[3]} {parts[5]}", "%a %d %b %H:%M:%S %Y")
    except ValueError:
        return None
    return naive.replace(tzinfo=timezone.utc) - timedelta(hours=_TZ_OFFSET_HOURS.get(tz_abbr, 0))


def _event_log_context(kind: str, key: str, timestamp_iso: str | None, window: int = 15) -> dict:
    try:
        target = datetime.fromisoformat(timestamp_iso) if timestamp_iso else None
    except ValueError:
        target = None
    if target is not None and target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)

    candidates = MISSION_LOG_FILES.get(key, []) if kind == "mission" else SKILL_LOG_FILES
    word_re = re.compile(r"(?<!\w)" + re.escape(key) + r"(?!\w)")

    best = None  # (abs_delta_seconds, filename, line_index, lines)
    for filename in candidates:
        path = EVENT_LOG_DIR / filename
        if not path.exists():
            continue
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            continue

        current_ts = None
        for i, line in enumerate(lines):
            date_match = _BASH_DATE_RE.search(line)
            if date_match:
                parsed = _parse_bash_date(date_match.group(1))
                if parsed is not None:
                    current_ts = parsed
            if not word_re.search(line):
                continue
            if target is None or current_ts is None:
                continue  # can't score how close this match is in time - skip it rather than guess
            delta = abs((current_ts - target).total_seconds())
            if best is None or delta < best[0]:
                best = (delta, filename, i, lines)

    if best is None:
        return {
            "ok": True,
            "found": False,
            "message": (
                f"No surrounding log context found for \"{key}\" near this event's own timestamp - "
                "either the matching log line has since rotated/been overwritten, or this ran before "
                "it could be matched to a timestamped line nearby."
            ),
        }

    delta, filename, idx, lines = best
    start, end = max(0, idx - window), min(len(lines), idx + window + 1)
    return {
        "ok": True,
        "found": True,
        "source_file": filename,
        "matched_line_index": idx,
        "seconds_from_event": round(delta, 1),
        "lines": lines[start:end],
        "highlight_index": idx - start,
    }


@bp.route("/event-log-context", methods=["GET"])
def event_log_context():
    """Backs the Training Log's in-depth report sub-page: given one
    Events-timeline entry's kind/key/timestamp (exactly as
    shadow.py's get_simulation_run_report() now returns them), finds
    and returns the real raw log lines around it. Read-only, never
    guesses an explanation beyond what the logs actually say."""
    kind = request.args.get("kind")
    key = request.args.get("key")
    timestamp = request.args.get("timestamp")
    if kind not in ("skill", "mission") or not key:
        return jsonify({"ok": False, "error": "kind (skill|mission) and key are required", "found": False})
    return jsonify(_event_log_context(kind, key, timestamp))
