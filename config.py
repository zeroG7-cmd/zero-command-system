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
