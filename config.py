from pathlib import Path


# Zero Command repository root
BASE_DIR = Path(__file__).resolve().parent


# External repositories
ZERO_GRAVITY_RND_ROOT = Path.home() / "zeroGravity-rnd"
ZEROGRAVITY_ROOT = Path.home() / "zeroGravity"


# Databases
SHADOW_DB = (
    ZERO_GRAVITY_RND_ROOT
    / "database"
    / "shadow.db"
)

ZEROGRAVITY_DB = (
    ZEROGRAVITY_ROOT
    / "database"
    / "zeroGravity.db"
)


# Operator Development data
OPERATOR_STATS = (
    ZERO_GRAVITY_RND_ROOT
    / "learning"
    / "operator"
    / "stats.json"
)

COMPETENCIES_FILE = (
    ZERO_GRAVITY_RND_ROOT
    / "learning"
    / "config"
    / "competencies.json"
)

SKILL_TREE_FILE = (
    ZERO_GRAVITY_RND_ROOT
    / "learning"
    / "config"
    / "skill_tree.json"
)
