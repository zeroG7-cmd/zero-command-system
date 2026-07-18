from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from config import ZEROGRAVITY_DB


def connect_zerogravity_db() -> sqlite3.Connection:
    db_path = Path(ZEROGRAVITY_DB)
    if not db_path.exists():
        raise FileNotFoundError(
            f"ZeroGravity database not found: {db_path}. "
            "Keep zeroGravity beside zero-command-system or set ZEROGRAVITY_ROOT."
        )
    return sqlite3.connect(db_path)


def count_multi_select_answers(values: list[str | None]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for value in values:
        if not value:
            continue
        for answer in value.split(","):
            clean_answer = answer.strip()
            if clean_answer:
                counts[clean_answer] += 1
    return dict(counts)


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def get_survey_summary() -> dict[str, Any]:
    try:
        with connect_zerogravity_db() as conn:
            if not _table_exists(conn, "customer_survey_responses"):
                return {
                    "total_responses": 0,
                    "service_interest": {},
                    "budget_range": {},
                    "warning": "Survey table has not been created yet.",
                    "database_path": str(ZEROGRAVITY_DB),
                }

            total = conn.execute(
                "SELECT COUNT(*) FROM customer_survey_responses"
            ).fetchone()[0]
            service_rows = conn.execute(
                "SELECT service_interest FROM customer_survey_responses"
            ).fetchall()
            budget_rows = conn.execute(
                """SELECT budget_range, COUNT(*)
                   FROM customer_survey_responses
                   GROUP BY budget_range
                   ORDER BY COUNT(*) DESC"""
            ).fetchall()

        return {
            "total_responses": total,
            "service_interest": count_multi_select_answers([row[0] for row in service_rows]),
            "budget_range": dict(budget_rows),
            "warning": None,
            "database_path": str(ZEROGRAVITY_DB),
        }
    except (FileNotFoundError, sqlite3.Error) as error:
        return {
            "total_responses": 0,
            "service_interest": {},
            "budget_range": {},
            "warning": str(error),
            "database_path": str(ZEROGRAVITY_DB),
        }
