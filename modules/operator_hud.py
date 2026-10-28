"""Operator Development - unified sci-fi HUD shell, live-data aggregator.

The shell page itself (templates/workspaces/operator/hud.html) is now what
GET /operator/ renders (see modules/operator.py's dashboard()). It is a
single static page with a client-side hash router; this module's one route
is the JSON endpoint that page fetches on load and after every action.

This module owns no business logic of its own. Every value below comes
from calling straight into each hub's own get_X_dashboard_data() - the
exact same function that hub's existing standalone page already renders
from (operator_execution.py, operator_flights.py, operator_challenges.py,
tasks.py and operator_journal.py didn't have one yet; each got the same
small, behavior-preserving extraction operator.py/operator_analytics.py/
operator_achievements.py/operator_fitness.py/operator_learning.py already
had - dashboard() itself is unchanged except for calling it). Re-deriving
any of this a second way here would let the HUD and a hub's real page
silently disagree over time, so this deliberately never does that.

Each hub is fetched independently and wrapped in its own try/except, so
one hub's bad data can't blank the rest of the HUD - matches the
isolation every other hub route in this app already gives its own page.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from flask import Blueprint, jsonify, request

from modules.operator import get_operator_dashboard_data
from modules.operator_analytics import get_analytics_dashboard_data
from modules.operator_achievements import get_achievements_dashboard_data
from modules.operator_execution import get_execution_dashboard_data
from modules.operator_flights import get_flights_dashboard_data
from modules.operator_challenges import get_challenges_dashboard_data
from modules.tasks import get_tasks_dashboard_data, DAY_BY_KEY
from modules.operator_fitness import get_fitness_dashboard_data
from modules.operator_journal import get_journal_dashboard_data
from modules.operator_learning import get_learning_hub_data

operator_hud_bp = Blueprint("operator_hud", __name__, url_prefix="/operator/hud")

_WEEKDAY_TO_KEY = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}


def _safe(getter, *args, **kwargs) -> tuple[Any, str | None]:
    try:
        return getter(*args, **kwargs), None
    except (FileNotFoundError, ValueError, OSError) as error:
        return None, str(error)
    except Exception as error:  # a hub-specific import/engine failure shouldn't blank the whole HUD
        return None, f"{type(error).__name__}: {error}"


@operator_hud_bp.get("/data")
def hud_data():
    today_key = _WEEKDAY_TO_KEY[date.today().weekday()]
    day_key = request.args.get("day", today_key)
    if day_key not in DAY_BY_KEY:
        day_key = today_key

    overview, overview_error = _safe(get_operator_dashboard_data)
    analytics, analytics_error = _safe(get_analytics_dashboard_data)
    achievements, achievements_error = _safe(get_achievements_dashboard_data)
    execution, execution_error = _safe(get_execution_dashboard_data)
    flights, flights_error = _safe(get_flights_dashboard_data)
    challenges, challenges_error = _safe(get_challenges_dashboard_data)
    tasks, tasks_error = _safe(get_tasks_dashboard_data, day_key)
    fitness, fitness_error = _safe(get_fitness_dashboard_data)
    # Journal's create() now redirects into this shell (see operator_journal.py's
    # _back()) rather than its own page, carrying the same created/error params
    # that page used to read itself - forward them so the HUD's Journal view can
    # show the "just saved" award banner the same way the standalone page did.
    journal, journal_error = _safe(
        get_journal_dashboard_data, request.args.get("created"), request.args.get("error")
    )
    learning, learning_error = _safe(get_learning_hub_data)

    return jsonify({
        "day_key": day_key,
        "overview": overview, "overview_error": overview_error,
        "analytics": analytics, "analytics_error": analytics_error,
        "achievements": achievements, "achievements_error": achievements_error,
        "execution": execution, "execution_error": execution_error,
        "flights": flights, "flights_error": flights_error,
        "challenges": challenges, "challenges_error": challenges_error,
        "tasks": tasks, "tasks_error": tasks_error,
        "fitness": fitness, "fitness_error": fitness_error,
        "journal": journal, "journal_error": journal_error,
        "learning": learning, "learning_error": learning_error,
    })
