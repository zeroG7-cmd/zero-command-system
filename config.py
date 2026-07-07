import os

BASE_DIR = os.path.dirname(__file__)

SHADOW_DB = os.path.abspath(
    os.path.join(
        BASE_DIR,
        "..",
        "shadow-drone-rnd",
        "database",
        "shadow.db"
    )
)

ZEROGRAVITY_DB = os.path.abspath(
    os.path.join(
        BASE_DIR,
        "..",
        "zeroGravity",
        "database",
        "zeroGravity.db"
    )
)
