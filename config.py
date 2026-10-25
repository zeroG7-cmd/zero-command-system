"""Zero Command configuration.

External repository locations can be overridden with ``ZERO_GRAVITY_RND_ROOT``
and ``ZEROGRAVITY_ROOT``. By default, Zero Command looks for sibling
repositories inside the same ``zero Gravity`` parent folder.
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = BASE_DIR.parent


def _external_root(env_name: str, sibling_name: str) -> Path:
    configured = os.environ.get(env_name)
    if configured:
        return Path(configured).expanduser().resolve()
    return (WORKSPACE_ROOT / sibling_name).resolve()


ZERO_GRAVITY_RND_ROOT = _external_root("ZERO_GRAVITY_RND_ROOT", "zeroGravity-rnd")
ZEROGRAVITY_ROOT = _external_root("ZEROGRAVITY_ROOT", "zeroGravity")

SHADOW_DB = ZERO_GRAVITY_RND_ROOT / "lab" / "database" / "legacy_shadow.db"
ZERO_GRAVITY_RND_DB = ZERO_GRAVITY_RND_ROOT / "lab" / "database" / "zerogravity_rnd.db"
ZEROGRAVITY_DB = ZEROGRAVITY_ROOT / "database" / "zeroGravity.db"

OPERATOR_STATS = ZERO_GRAVITY_RND_ROOT / "operator_core" / "hubs" / "learning" / "stats" / "learning_stats.json"
COMPETENCIES_FILE = ZERO_GRAVITY_RND_ROOT / "operator_core" / "capabilities" / "competencies.json"
SKILL_TREE_FILE = ZERO_GRAVITY_RND_ROOT / "operator_core" / "capabilities" / "skill_tree.json"
CAPABILITY_GRAPH_FILE = ZERO_GRAVITY_RND_ROOT / "operator_core" / "capabilities" / "capability_graph.json"

# nodes/telemetry_publisher.py (shadow_drone, Oct 3 2026) writes Shadow's
# live sim snapshot here at ~20Hz, atomically (temp file + os.replace) -
# same override convention as the two repo roots above. Matches that
# script's own DEFAULT_OUTPUT_PATH ('~/shadow_sim_runtime/telemetry/latest.json')
# exactly when SHADOW_SIM_RUNTIME_ROOT isn't overridden, since WORKSPACE_ROOT
# is this app's own parent folder - the same folder shadow_sim_runtime lives
# in as a sibling, not a guess.
SHADOW_SIM_RUNTIME_ROOT = _external_root("SHADOW_SIM_RUNTIME_ROOT", "shadow_sim_runtime")
SHADOW_TELEMETRY_JSON = SHADOW_SIM_RUNTIME_ROOT / "telemetry" / "latest.json"

# shadow_drone's own progress.json (the real, git-tracked file
# nodes/run_skill.py writes every skill pass/fail to - streak/unlocked
# per skill, not telemetry). Same override convention as the two repo
# roots above; by default resolves to WORKSPACE_ROOT/shadow_ws/src/shadow_drone,
# which matches this machine's real layout (shadow_ws and
# zero-command-system are both direct siblings under /home/zero).
SHADOW_DRONE_REPO_ROOT = _external_root("SHADOW_DRONE_REPO_ROOT", "shadow_ws/src/shadow_drone")
SHADOW_PROGRESS_JSON = SHADOW_DRONE_REPO_ROOT / "progress.json"
