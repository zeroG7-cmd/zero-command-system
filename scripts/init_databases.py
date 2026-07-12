from __future__ import annotations

import sqlite3
from pathlib import Path

from config import SHADOW_DB, ZERO_GRAVITY_RND_DB


RND_SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_name TEXT NOT NULL,
    category TEXT,
    status TEXT NOT NULL DEFAULT 'planned',
    hypothesis TEXT,
    method TEXT,
    conclusion TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS test_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER,
    test_name TEXT NOT NULL,
    component TEXT,
    source TEXT NOT NULL DEFAULT 'simulation',
    result TEXT,
    notes TEXT,
    timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (experiment_id) REFERENCES experiments(id)
);

CREATE TABLE IF NOT EXISTS simulation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER,
    simulator TEXT,
    scenario_name TEXT,
    vehicle_model TEXT,
    status TEXT NOT NULL DEFAULT 'planned',
    started_at TEXT,
    completed_at TEXT,
    notes TEXT,
    FOREIGN KEY (experiment_id) REFERENCES experiments(id)
);

CREATE TABLE IF NOT EXISTS simulated_telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_run_id INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    battery_voltage REAL,
    battery_percentage REAL,
    latitude REAL,
    longitude REAL,
    altitude REAL,
    velocity_x REAL,
    velocity_y REAL,
    velocity_z REAL,
    roll REAL,
    pitch REAL,
    yaw REAL,
    flight_mode TEXT,
    FOREIGN KEY (simulation_run_id) REFERENCES simulation_runs(id)
);

CREATE TABLE IF NOT EXISTS datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER,
    name TEXT NOT NULL,
    dataset_type TEXT,
    source_path TEXT,
    description TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (experiment_id) REFERENCES experiments(id)
);

CREATE TABLE IF NOT EXISTS model_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER,
    model_name TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL,
    notes TEXT,
    evaluated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (experiment_id) REFERENCES experiments(id)
);
"""


SHADOW_SCHEMA = """
CREATE TABLE IF NOT EXISTS vehicle (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_name TEXT NOT NULL,
    asset_type TEXT,
    model TEXT,
    serial_number TEXT,
    operational_status TEXT NOT NULL DEFAULT 'offline',
    last_seen TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    battery_voltage REAL,
    battery_percentage REAL,
    latitude REAL,
    longitude REAL,
    altitude REAL,
    velocity_x REAL,
    velocity_y REAL,
    velocity_z REAL,
    roll REAL,
    pitch REAL,
    yaw REAL,
    link_quality REAL,
    flight_mode TEXT
);

CREATE TABLE IF NOT EXISTS missions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_name TEXT NOT NULL,
    mission_type TEXT,
    status TEXT NOT NULL DEFAULT 'planned',
    started_at TEXT,
    completed_at TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS hardware_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    component_name TEXT NOT NULL,
    health_status TEXT NOT NULL,
    temperature REAL,
    voltage REAL,
    current_draw REAL,
    checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS faults (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    component_name TEXT,
    fault_code TEXT,
    severity TEXT,
    description TEXT NOT NULL,
    detected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT,
    resolution_notes TEXT
);

CREATE TABLE IF NOT EXISTS maintenance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    component_name TEXT,
    maintenance_type TEXT NOT NULL,
    description TEXT,
    performed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    next_due_at TEXT
);

CREATE TABLE IF NOT EXISTS battery_cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    battery_identifier TEXT NOT NULL,
    cycle_number INTEGER,
    start_voltage REAL,
    end_voltage REAL,
    charged_capacity_mah REAL,
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def initialise_database(path: Path, schema: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(schema)
        connection.commit()


def seed_shadow_vehicle() -> None:
    with sqlite3.connect(SHADOW_DB) as connection:
        row = connection.execute(
            "SELECT COUNT(*) FROM vehicle"
        ).fetchone()

        if row and row[0] == 0:
            connection.execute(
                """
                INSERT INTO vehicle (
                    asset_name,
                    asset_type,
                    model,
                    operational_status
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    "Shadow MK1",
                    "Companion Aerial Robot",
                    "MK1",
                    "offline",
                ),
            )
            connection.commit()


def main() -> None:
    initialise_database(Path(ZERO_GRAVITY_RND_DB), RND_SCHEMA)
    initialise_database(Path(SHADOW_DB), SHADOW_SCHEMA)
    seed_shadow_vehicle()

    print(f"R&D database ready: {ZERO_GRAVITY_RND_DB}")
    print(f"Shadow database ready: {SHADOW_DB}")


if __name__ == "__main__":
    main()
