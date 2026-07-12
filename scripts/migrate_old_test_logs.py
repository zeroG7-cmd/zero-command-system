from __future__ import annotations

import sqlite3
from pathlib import Path

from config import SHADOW_DB, ZERO_GRAVITY_RND_DB


def table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def main() -> None:
    shadow_path = Path(SHADOW_DB)
    rnd_path = Path(ZERO_GRAVITY_RND_DB)

    if not shadow_path.exists():
        print(f"No existing Shadow database found at: {shadow_path}")
        return

    rnd_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(shadow_path) as source:
        source.row_factory = sqlite3.Row

        if not table_exists(source, "test_logs"):
            print("No legacy test_logs table found. Nothing to migrate.")
            return

        rows = source.execute(
            """
            SELECT
                test_name,
                component,
                result,
                notes,
                source,
                timestamp
            FROM test_logs
            ORDER BY id ASC
            """
        ).fetchall()

    with sqlite3.connect(rnd_path) as destination:
        destination.executemany(
            """
            INSERT INTO test_runs (
                test_name,
                component,
                result,
                notes,
                source,
                timestamp
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["test_name"],
                    row["component"] if "component" in row.keys() else None,
                    row["result"],
                    row["notes"] if "notes" in row.keys() else None,
                    row["source"] if "source" in row.keys() else "hardware",
                    row["timestamp"] if "timestamp" in row.keys() else None,
                )
                for row in rows
            ],
        )
        destination.commit()

    print(f"Migrated {len(rows)} legacy test records into {rnd_path}")
    print("The original test_logs table was not deleted from shadow.db.")


if __name__ == "__main__":
    main()
