from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from config import SHADOW_DB


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
