"""Home brief: the speech bubble Zero says on the home screen.

GET /home/brief            -> today's brief (read only)
GET /home/brief?boot=1     -> same, and records this as a boot (the home page
                              sends boot=1 once per app start, never when you
                              come back out of a room, so the mood and the
                              "since last boot" celebration don't replay)

Contract (agreed in the 19 Nov home-screen brief):
    {mood: "normal"|"good"|"away", greeting, lines:[{room, hub, kind, text,
     source, route}], footer, since_last_boot:{cleared:[], xp:0}}

Rules this module enforces:
- At most 3 lines; exactly 1 on an away day.
- Every line names a room and comes from a real file. No source, no line.
  Each collector runs in its own try/except, so a missing or broken file
  just drops that line instead of blanking the bubble.
- Exact verbs: nothing here says "clears" unless a gate really cleared.
- Prefer the smallest real next action.
- Celebrate first if something passed since the last boot.
- Away (the newer of last boot / last operator event is 5+ days old): kind
  tone, no counts, no "overdue". The next boot is normal again.
- No red anywhere: the bubble only ever gets kinds win/next/check/gentle.

Numbers are never re-derived here. The Office plan score uses the exact
rule business_office.js uses for its "x / 7 PASS" (sections 1-7, verdict
PASS, zero placeholders), on top of business_office.plan_status(). Learning
uses operator_learning._card(), the same card the Learning hub renders.

Boot state is per machine and never committed: it lives in the user's home
folder (~/.zero-command/home_state.json), so Windows and Linux each keep
their own. "Cleared since last boot" compares sets of ids saved at the last
boot (receipt files, PASS sections), not file times, because a git pull
rewrites file times and would fake a celebration.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from flask import Blueprint, jsonify, request, url_for

home_brief_bp = Blueprint("home_brief", __name__, url_prefix="/home")

NAME = "Zero"            # who Zero greets
AWAY_DAYS = 5
MAX_LINES = 3
ROOM_ORDER = ("office", "operator", "lab", "flight")
NUMBER_WORDS = {1: "One thing", 2: "Two things", 3: "Three things"}


# ---------------------------------------------------------------- helpers
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _state_path() -> Path:
    override = os.environ.get("ZERO_COMMAND_STATE_DIR")
    base = Path(override).expanduser() if override else Path.home() / ".zero-command"
    return base / "home_state.json"


def _load_state() -> dict[str, Any]:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _save_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _greeting_word(local_hour: int) -> str:
    if local_hour < 12:
        return "Morning"
    if local_hour < 18:
        return "Afternoon"
    return "Evening"


def _rel(path: Path, root: Path) -> str:
    try:
        return f"{root.name}/{path.relative_to(root).as_posix()}"
    except ValueError:
        return path.name


def _line(room: str, hub: str, kind: str, text: str, source: str, route: str) -> dict[str, str]:
    return {"room": room, "hub": hub, "kind": kind, "text": text, "source": source, "route": route}


def _safe(fn: Callable[..., Any], *args: Any) -> Any:
    try:
        return fn(*args)
    except Exception:  # noqa: BLE001 - one bad source must never blank the bubble
        return None


# ---------------------------------------------------------------- office
def _office_snapshot() -> dict[str, Any]:
    from config import ZEROGRAVITY_ROOT
    from modules import business_office as bo

    office_dir = bo._office_dir()
    readiness_cfg = bo._load_json(office_dir / "readiness.json", {})
    plan = bo.plan_status(readiness_cfg)
    sections = plan["sections"]
    passing = [s["number"] for s in sections if s["number"] <= 7 and s["verdict"] == "PASS" and s["placeholders"] == 0]
    receipts_dir = office_dir / "receipts"
    receipts = sorted(p.stem for p in receipts_dir.glob("*.json")) if receipts_dir.exists() else []
    titles = {i["id"]: i["title"] for g in readiness_cfg.get("gates", []) for i in g.get("items", [])}
    quick = []
    for gate in readiness_cfg.get("gates", []):
        for item in gate.get("items", []):
            if not item.get("quick") or item["id"] in receipts:
                continue
            if item.get("check", {}).get("type") == "evidence":
                state = (_safe(bo.evidence_state, item["id"]) or {}).get("state")
                if state in ("filed", "verified"):   # already in the vault: the Office asks for VERIFY, not a new action
                    continue
            if True:
                quick.append({"id": item["id"], "title": item["title"], **item["quick"]})
    quick.sort(key=lambda q: -q.get("weight", 0))
    return {
        "root": Path(ZEROGRAVITY_ROOT), "office_dir": office_dir, "sections": sections, "passing": passing,
        "receipts": receipts, "titles": titles, "quick": quick, "judge_run_at": plan.get("judge_run_at"),
    }


def _office_lines(snap: dict[str, Any], away: bool) -> list[dict[str, str]]:
    lines: list[dict[str, str]] = []
    root, office_dir = snap["root"], snap["office_dir"]
    # Smallest plan fix: the section (1-7, not yet PASS) with the fewest unmet judge items.
    open_sections = [s for s in snap["sections"] if s["number"] <= 7 and s["number"] not in snap["passing"]]
    candidates = [s for s in open_sections if any(not i["met"] for i in s["items"])]
    if candidates:
        s = min(candidates, key=lambda x: (sum(1 for i in x["items"] if not i["met"]), x["number"]))
        unmet = [i for i in s["items"] if not i["met"]]
        first = unmet[0]
        note = first["note"].strip().split(". ")[0].rstrip(".")
        note = note[:1].lower() + note[1:] if note else ""
        judged = f" · judged {snap['judge_run_at']}" if snap.get("judge_run_at") else ""
        if away:
            text = f"If you feel like it: one small fix in plan §{s['number']}, {first['c']}."
        else:
            fixes = "one fix" if len(unmet) == 1 else f"{len(unmet)} fixes"
            text = f"Plan §{s['number']} needs {fixes}. Start with {first['c']}: {note}."
        lines.append(_line("office", "PLAN", "next", text, _rel(office_dir / "plan_judge.json", root) + judged,
                           url_for("business_office.office") + "#plan"))
    # Quick win from the readiness checklist (items that clear by evidence, not a manual tick).
    if snap["quick"]:
        q = snap["quick"][0]
        text = f"{q['title']}: {q['sub'][:1].lower() + q['sub'][1:]}." if q.get("sub") else f"{q['title']} is the quickest readiness win."
        lines.append(_line("office", "READY", "next", text.replace("..", "."), _rel(office_dir / "readiness.json", root),
                           url_for("business_office.office") + "#ready"))
    return lines


# ---------------------------------------------------------------- operator (learning)
def _learning_lines(away: bool) -> list[dict[str, str]]:
    from modules import operator_learning as ol

    best = None
    for track in ol._track_paths():
        progress_file = track / "progress.json"
        card = ol._card(track)
        total, done = card["unit_count"], card["completed_count"]
        if not total or done >= total or str(card.get("status", "")).lower() == "completed":
            continue
        key = (done > 0, progress_file.stat().st_mtime)   # started tracks first, then most recently touched
        if best is None or key > best[0]:
            best = (key, card, track)
    if not best:
        return []
    _, card, track = best
    unit = card.get("current_unit") or {}
    unit_title = unit.get("title") or unit.get("name")
    if away:
        text = f"One small thing, if you feel like it: a few minutes of {card['title']} counts."
    elif card["completed_count"] == 0:
        text = f"{card['title']} hasn't started yet. One lesson gets it moving."
    else:
        nxt = f" Next up: {unit_title}." if unit_title else " One more lesson keeps it moving."
        text = f"{card['title']}: {card['completed_count']} of {card['unit_count']} done.{nxt}"
    root = ol._rnd_root()
    return [_line("operator", "LEARN", "gentle" if away else "next", text, _rel(track / "progress.json", root),
                  url_for("operator_learning.dashboard"))]


# ---------------------------------------------------------------- lab (Shadow)
def _shadow_lines(away: bool) -> list[dict[str, str]]:
    """Only speaks if shadow_drone's own progress.json is reachable on this
    machine (normally the Linux side). On Windows it's usually absent, and
    then there is simply no Shadow line: no source, no line."""
    from config import SHADOW_PROGRESS_JSON

    if away or not SHADOW_PROGRESS_JSON.exists():
        return []
    data = json.loads(SHADOW_PROGRESS_JSON.read_text(encoding="utf-8"))
    skills = data.get("skills", data) if isinstance(data, dict) else {}
    if not isinstance(skills, dict):
        return []
    locked = [(name, s) for name, s in skills.items() if isinstance(s, dict) and not s.get("unlocked")]
    if not locked:
        return []
    name, s = locked[0]
    streak = s.get("streak")
    label = name.replace("_", " ")
    text = f"Shadow's next skill is {label}." + (f" Streak so far: {streak}." if isinstance(streak, int) else "")
    return [_line("lab", "SHADOW", "next", text, f"shadow_drone/{SHADOW_PROGRESS_JSON.name}",
                  url_for("research_development.dashboard"))]


# ---------------------------------------------------------------- events
def _events(since: datetime | None) -> tuple[datetime | None, int]:
    """Newest operator event time, and XP distributed after `since`."""
    from modules import operator_learning as ol

    path = ol._rnd_root() / "operator_core" / "events" / "operator_events.jsonl"
    if not path.exists():
        return None, 0
    newest, xp = None, 0
    with path.open(encoding="utf-8") as fh:
        for raw in fh:
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            t = _parse_time(ev.get("occurred_at"))
            if t and (newest is None or t > newest):
                newest = t
            if since and t and t > since and ev.get("event_type") == "xp_distributed":
                xp += int((ev.get("payload") or {}).get("total_xp") or 0)
    return newest, xp


# ---------------------------------------------------------------- brief
def build_brief(record_boot: bool = False, local_hour: int | None = None) -> dict[str, Any]:
    state = _load_state()
    last_boot = _parse_time(state.get("last_boot"))
    last_event, xp_since = _safe(_events, last_boot) or (None, 0)
    newest_activity = max([t for t in (last_boot, last_event) if t], default=None)
    away = bool(last_boot) and newest_activity is not None and (_now() - newest_activity).days >= AWAY_DAYS

    snap = _safe(_office_snapshot)
    cleared: list[dict[str, str]] = []
    if snap and last_boot:
        for rid in sorted(set(snap["receipts"]) - set(state.get("receipts", []))):
            cleared.append({"id": f"ready.{rid}", "title": snap["titles"].get(rid, rid)})
        for n in sorted(set(snap["passing"]) - set(state.get("passing", []))):
            cleared.append({"id": f"plan.s{n}", "title": f"Plan §{n}"})
    xp_since = xp_since if last_boot else 0
    mood = "away" if away else ("good" if cleared or xp_since > 0 else "normal")

    by_room: dict[str, list[dict[str, str]]] = {r: [] for r in ROOM_ORDER}
    for room, lines in (("office", _safe(_office_lines, snap, away) if snap else None),
                        ("operator", _safe(_learning_lines, away)),
                        ("lab", _safe(_shadow_lines, away))):
        by_room[room] = lines or []

    picked: list[dict[str, str]] = []
    if mood == "good" and cleared:   # celebrate first
        c = cleared[0]
        more = f" (and {len(cleared) - 1} more)" if len(cleared) > 1 else ""
        verb = "passed the judge" if c["id"].startswith("plan.") else "cleared"
        picked.append(_line("office", "PLAN" if c["id"].startswith("plan.") else "READY", "win",
                            f"{c['title']} {verb} since you last booted{more}.",
                            _rel(snap["office_dir"] / ("plan_judge.json" if c["id"].startswith("plan.") else "receipts"), snap["root"]),
                            url_for("business_office.office") + ("#plan" if c["id"].startswith("plan.") else "#ready")))
    # One line per room first (spread across rooms), then fill with seconds.
    for room in ROOM_ORDER:
        if by_room[room]:
            picked.append(by_room[room].pop(0))
    for room in ROOM_ORDER:
        while by_room[room] and len(picked) < MAX_LINES:
            picked.append(by_room[room].pop(0))
    if away:
        gentle = [l for l in picked if l["room"] == "operator"] or picked
        picked = gentle[:1]
    picked = picked[:MAX_LINES]

    hour = local_hour if local_hour is not None else datetime.now().hour
    word = _greeting_word(hour)
    if mood == "away":
        greeting = f"Welcome back, {NAME}. Good to see you."
        footer = "Everything else keeps."
    elif mood == "good":
        greeting = f"{word}, {NAME}! Something moved since you last booted."
        footer = f"+{xp_since} XP since last boot" if xp_since else None
    else:
        greeting = f"{word}, {NAME}. {NUMBER_WORDS.get(len(picked), 'Nothing urgent')} today." if picked else f"{word}, {NAME}. Nothing urgent today."
        footer = None

    brief = {
        "mood": mood, "greeting": greeting, "lines": picked, "footer": footer,
        "since_last_boot": {"cleared": [c["id"] for c in cleared], "xp": xp_since},
        "last_boot": state.get("last_boot"),
    }

    if record_boot:
        new_state = dict(state)
        new_state["last_boot"] = _now().isoformat()
        if snap:
            new_state["receipts"] = snap["receipts"]
            new_state["passing"] = snap["passing"]
        _safe(_save_state, new_state)
    return brief


@home_brief_bp.get("/layout")
def layout():
    """home_layout.json with each room's endpoint resolved to a real URL, plus
    which world models exist. A room whose endpoint doesn't resolve gets
    route null (shown, not enterable) instead of a dead link."""
    from flask import current_app
    from werkzeug.routing import BuildError

    static = Path(current_app.static_folder)
    data = json.loads((static / "data" / "home_layout.json").read_text(encoding="utf-8"))
    for room in data.get("rooms", []):
        endpoint = room.pop("endpoint", None)
        try:
            room["route"] = url_for(endpoint) + room.pop("hash", "") if endpoint else None
        except BuildError:
            room["route"] = None
    models = {}
    for key, name in (("shadow", "shadow_mk1_world.glb"), ("zero", "zero_world.glb")):
        models[key] = url_for("static", filename=f"models/{name}") if (static / "models" / name).exists() else None
    data["models"] = models
    return jsonify(data)


@home_brief_bp.get("/brief")
def brief():
    hour = request.args.get("hour", type=int)   # the page sends its local hour so the greeting follows your clock
    return jsonify(build_brief(record_boot=request.args.get("boot") == "1",
                               local_hour=hour if hour is not None and 0 <= hour <= 23 else None))
