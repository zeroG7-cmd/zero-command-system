"""Simulation control - lets Zero Command's UI actually trigger the
same scripts you'd otherwise run by hand in a terminal. Genuinely the
same script either way, just triggered by a click instead of typing -
same principle discussed earlier tonight about UI buttons being a thin
layer over the real backend commands, not a separate system.
"""
from __future__ import annotations

import json
import sqlite3
import statistics
import subprocess
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


def _run_detached(script_name: str, args: list[str] | None = None) -> dict:
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
    return jsonify(_run_detached(script))


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
TRAINING_TASKS = [
    {
        "key": "go_to",
        "name": "Point-to-Point Flight",
        "description": (
            "PPO learns to fly to one random goal point, as fast and "
            "precisely as possible. The foundational flight-control task "
            "everything else here builds on."
        ),
        "script": "run_training.sh",
        "checkpoint_path": Path.home() / "shadow_ws" / "ml" / "models" / "go_to" / "go_to_ppo_final.zip",
        "mlflow_experiment": "shadow-go-to",
        # Oct 25, 2026 (even later) - "stability" added once STABILITY
        # got wired below. Same episode_length data this task's own run
        # already logs, just a second question asked of it (consistency,
        # not crash-free rate) - see _stability_score()'s own docstring.
        "feeds_attributes": ["agility", "stability"],
        "log_file": "training.log",
    },
    {
        "key": "agility_circuit",
        "name": "Waypoint Circuit",
        "description": (
            "PPO learns to race continuously through a fixed six-point "
            "circuit - the real payload/pad coordinates from "
            "shadow_runway.sdf - lap after lap. \"Agility-lite\": fast, "
            "precise flight between real points under time pressure, "
            "not literal gate-passing yet."
        ),
        "script": "run_agility_training.sh",
        "checkpoint_path": Path.home() / "shadow_ws" / "ml" / "models" / "agility_circuit" / "agility_circuit_ppo_final.zip",
        "mlflow_experiment": "shadow-agility-circuit",
        "feeds_attributes": ["agility", "stability"],
        "log_file": "agility_training.log",
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
    return jsonify(_run_detached(task["script"], args))


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
            **stats,
        })
    return jsonify({"ok": True, "tasks": tasks})
