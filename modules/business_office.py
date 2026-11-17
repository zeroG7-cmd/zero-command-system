"""zeroGravity Office - Business module (build 1).

Hash-routed HUD shell at /business/ (templates/workspaces/business/office.html
+ static/css/business_office.css + static/js/business_office.js), same
pattern as the Operator HUD: one JSON endpoint (/business/data) assembled
here, each hub built in its own try/except so one bad source can't blank
the rest.

Design rule (agreed 30 Oct / 16 Nov): nothing in here has a manual "done"
switch. Every Launch Readiness item clears only when its check passes, and
a pass writes a receipt. Time spent in the module earns 0 XP.

Data lives in the zeroGravity business repo, not here:
    zeroGravity/operations/office/readiness.json   gates + checks
    zeroGravity/operations/office/leads.json       leads board
    zeroGravity/operations/office/plan_judge.json  AI judge results
    zeroGravity/operations/office/competitors.json research data
    zeroGravity/operations/office/content_tags.json clip tags
    zeroGravity/operations/office/receipts/        one per cleared item
    zeroGravity/operations/office/evidence/        certificates (gitignored)
Footage is read from the sibling zeroGravity-media folder.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, render_template, request

from config import ZEROGRAVITY_DB, ZEROGRAVITY_ROOT
from modules.business_judge import (
    JudgeError, api_ready, evidence_state, rubrics, run_plan_judge, stale_sections, verify_evidence,
)

business_office_bp = Blueprint("business_office", __name__, url_prefix="/business")

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".mts"}
RENDER_EXT = VIDEO_EXT | {".png", ".exr", ".jpg", ".jpeg", ".webm"}
# Manifest "type": client = paid/real shoot (counts for Footage edited + Portfolio),
# showreel = cut of real drone footage (counts for Footage edited only),
# brand / animation = launch video, animation clips (tracked, counts for neither).
PROJECT_TYPES = ("client", "showreel", "brand", "animation")
LEAD_STATUSES = ["contacted", "replied", "quoted", "booked", "lost"]
TAG_VALUES = {"none", "hero", "broll", "rej"}


# ---------------------------------------------------------------- paths / io
def _office_dir() -> Path:
    return Path(ZEROGRAVITY_ROOT) / "operations" / "office"


def _media_root() -> Path:
    configured = os.environ.get("ZEROGRAVITY_MEDIA_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    # Sibling of the business repo. Derived from ZEROGRAVITY_ROOT (which the
    # Electron launcher passes in) rather than config.WORKSPACE_ROOT, because
    # in the PyInstaller build WORKSPACE_ROOT resolves inside the bundle.
    return (Path(ZEROGRAVITY_ROOT).parent / "zeroGravity-media").resolve()


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _safe(getter, *args, **kwargs) -> tuple[Any, str | None]:
    try:
        return getter(*args, **kwargs), None
    except Exception as error:  # one hub failing must not blank the Office
        return None, f"{type(error).__name__}: {error}"


# ---------------------------------------------------------------- media scan
_FFPROBE = shutil.which("ffprobe")
_duration_cache: dict[tuple[str, float], float | None] = {}


def _duration(path: Path) -> float | None:
    if not _FFPROBE:
        return None
    key = (str(path), path.stat().st_mtime)
    if key in _duration_cache:
        return _duration_cache[key]
    value: float | None = None
    try:
        out = subprocess.run(
            [_FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=15, check=False,
        )
        value = float(out.stdout.strip()) if out.stdout.strip() else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        value = None
    _duration_cache[key] = value
    return value


def _videos(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXT)


def _manifests() -> list[dict[str, Any]]:
    folder = Path(ZEROGRAVITY_ROOT) / "media" / "manifests"
    found = []
    for path in sorted(folder.glob("ZG-MEDIA-*.json")):
        try:
            found.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return found


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _yes(value: Any) -> bool:
    return str(value).strip().lower() in {"y", "yes", "true", "1"}


def scan_media() -> dict[str, Any]:
    root = _media_root() / "projects"
    manifests = _manifests()
    by_key = {}
    for m in manifests:
        by_key[_norm(m.get("title", ""))] = m
        by_key[_norm(Path(str(m.get("media_root", "")).replace("\\", "/")).name)] = m
    projects = []
    if root.is_dir():
        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
            raw = _videos(folder / "raw")
            edits_dir = folder / "edits"
            edits = _videos(edits_dir)
            prproj = sorted(edits_dir.glob("*.prproj")) if edits_dir.is_dir() else []
            prproj += sorted((folder / "premiere pro").glob("*.prproj")) if (folder / "premiere pro").is_dir() else []
            exports = _videos(folder / "exports")
            renders_dir = folder / "renders"
            renders = [p for p in renders_dir.rglob("*") if p.is_file() and p.suffix.lower() in RENDER_EXT] if renders_dir.is_dir() else []
            manifest = by_key.get(_norm(folder.name))
            ptype = str((manifest or {}).get("type", "client")).lower()
            ptype = ptype if ptype in PROJECT_TYPES else "client"
            rights = (manifest or {}).get("rights", {})
            permission = "yes" if _yes(rights.get("portfolio_permission")) else ("unknown" if manifest is None or str(rights.get("portfolio_permission", "unknown")).lower() in {"", "unknown"} else "no")
            export_info = [{"name": p.name, "seconds": _duration(p), "bytes": p.stat().st_size} for p in exports]
            # A video in edits/ named like the project itself is usually a finished cut in the wrong folder.
            misplaced = [p.name for p in edits if _norm(p.stem) == _norm(folder.name)]
            projects.append({
                "name": folder.name,
                "raw": len(raw),
                "trims": [{"name": p.name, "bytes": p.stat().st_size, "seconds": None} for p in edits if p.name not in misplaced],
                "prproj": [str(p) for p in prproj],
                "exports": export_info,
                "misplaced_cuts": misplaced,
                "manifest_id": (manifest or {}).get("project_id"),
                "type": ptype,
                "renders": len(renders),
                "destinations": (manifest or {}).get("destinations", []),
                "portfolio_permission": permission,
                "empty": not raw and not edits and not exports and not prproj and not renders,
            })
    return {"root": str(root), "exists": root.is_dir(), "ffprobe": bool(_FFPROBE), "projects": projects}


# ---------------------------------------------------------------- plan file
_PLACEHOLDER = re.compile(
    r"\[(?:Write|Month Year|Name|Date|Amount|Price|Item|Supplier|Insurance|Strengths|Weaknesses|Service|"
    r"Competitor \d|Next step|Final step|Step \d|Website|Number|Explain|Cost|Notes|Payment terms|Reason|"
    r"Details|handle|follower count|Yes / No|New / Second-hand)\b[^\]]*\]"
)
_BRACKET_FIGURE = re.compile(r"£\s*\[[0-9,.]+\]|\*\*\s*\[[A-Za-z]+\]\s*\*\*")


def _plan_sections(readiness: dict[str, Any]) -> dict[int, str]:
    path = Path(ZEROGRAVITY_ROOT) / readiness.get("plan_file", "docs/01_business_plan/kings_trust/business_plan_template.md")
    text = path.read_text(encoding="utf-8")
    parts = re.split(r"^# Section (\w+)", text, flags=re.M)
    words = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5, "Six": 6, "Seven": 7, "Eight": 8}
    sections: dict[int, str] = {}
    for i in range(1, len(parts) - 1, 2):
        number = words.get(parts[i].strip(":"))
        if number:
            sections[number] = parts[i + 1]
    return sections


def plan_status(readiness: dict[str, Any]) -> dict[str, Any]:
    sections = _plan_sections(readiness)
    judge = _load_json(_office_dir() / "plan_judge.json", {"sections": {}, "cross_checks": []})
    stale = set(stale_sections(sections))
    out = []
    for number in range(1, 9):
        body = sections.get(number, "")
        holders = _PLACEHOLDER.findall(body)
        figures = _BRACKET_FIGURE.findall(body) if number == 1 else []
        money = 0
        if number == 8:
            # Only the subsections that hold real numbers: payment terms,
            # suppliers, equipment, transport, insurance.
            for sub in ("8.3", "8.4", "8.6", "8.7", "8.9"):
                m = re.search(rf"^## {re.escape(sub)}\b(.*?)(?=^## |\Z)", body, flags=re.M | re.S)
                if m:
                    money += len(_PLACEHOLDER.findall(m.group(1)))
        j = judge.get("sections", {}).get(str(number), {})
        items = [{"c": c, "met": bool(m), "note": n} for c, m, n in j.get("items", [])]
        out.append({
            "number": number,
            "title": j.get("title", f"§{number}"),
            "verdict": j.get("verdict", "NOT JUDGED"),
            "placeholders": len(holders),
            "bracket_figures": len(figures),
            "money_placeholders": money,
            "stale": number in stale,
            "met": sum(1 for i in items if i["met"]),
            "total": len(items),
            "items": items,
        })
    return {"sections": out, "cross_checks": judge.get("cross_checks", []), "judge_source": judge.get("source"),
            "judge_run_at": judge.get("run_at"), "judge_model": judge.get("model"), "api_ready": api_ready(),
            "stale_count": len(stale)}


# ---------------------------------------------------------------- checks
_http_cache: dict[str, tuple[float, bool, str]] = {}


def _http_ok(domain: str) -> tuple[bool, str]:
    cached = _http_cache.get(domain)
    if cached and time.time() - cached[0] < 600:
        return cached[1], cached[2]
    url = domain if domain.startswith("http") else f"https://{domain}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ZeroCommand-Office"}), timeout=6) as resp:
            ok, note = resp.status == 200, f"HTTP {resp.status} on {url}"
    except Exception as error:
        ok, note = False, f"{url} not reachable ({type(error).__name__})"
    _http_cache[domain] = (time.time(), ok, note)
    return ok, note


def _receipt(item_id: str, evidence: str) -> str:
    path = _office_dir() / "receipts" / f"{item_id}.json"
    now = datetime.now().isoformat(timespec="seconds")
    existing = _load_json(path, None)
    if existing is None:
        existing = {"item": item_id, "first_passed_at": now}
    existing.update({"last_checked_at": now, "evidence": evidence,
                     "evidence_hash": hashlib.sha256(evidence.encode("utf-8")).hexdigest()[:16]})
    _save_json(path, existing)
    return existing["first_passed_at"][:10]


def _evaluate(item: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    check = item.get("check", {})
    kind = check.get("type")
    res = {"passed": False, "status": "TO DO", "cls": "todo", "now": ""}

    if kind == "evidence":
        ev = evidence_state(item["id"])
        st = ev["state"]
        if st == "verified":
            res.update(passed=True, evidence=f"{ev.get('doc') or 'document'} · expires {ev.get('expiry') or 'not stated'}",
                       now=f"Vision check passed · expires {ev.get('expiry') or 'not stated'}")
        elif st == "expired":
            res.update(status="EXPIRED", cls="bad", now=f"Expired {ev['expiry']}. Re-locked until you file a current one")
        elif st == "rejected":
            res.update(status="REJECTED", cls="bad", can_verify=True, now="; ".join(ev.get("reasons", [])) or "Didn't pass")
        elif st == "filed":
            res.update(status="FILED", cls="conf", filed=True, can_verify=True,
                       now=f"{ev['file']} in the vault. Press VERIFY to run the vision check")
        else:
            res["now"] = f"No file in evidence/{item['id']}/ yet"

    elif kind == "glob":
        base = Path(ZEROGRAVITY_ROOT)
        hits = list(base.glob(check["pattern"]))
        if len(hits) >= check.get("min", 1):
            res.update(passed=True, evidence=", ".join(p.name for p in hits[:3]))
            res["now"] = f"{len(hits)} file(s) found"
        else:
            res["now"] = f"Nothing at {check['pattern']}"

    elif kind == "media_raw":
        media = ctx["media"]
        total = sum(p["raw"] for p in media["projects"])
        with_raw = [p["name"] for p in media["projects"] if p["raw"]]
        if total >= check.get("min", 1):
            res.update(passed=True, evidence=f"{total} raw clips: {', '.join(with_raw)}")
            res["now"] = f"{total} raw clips across {len(with_raw)} projects"
        else:
            res["now"] = "No raw clips found in zeroGravity-media/projects"

    elif kind == "media_export":
        media = ctx["media"]
        need = check.get("min", 1)
        min_s = check.get("min_seconds", 30)
        good, unknown = [], 0
        types = check.get("types") or (["client"] if check.get("require_permission") else ["client", "showreel"])
        for p in media["projects"]:
            if p["type"] not in types:
                continue
            if check.get("require_permission") and p["portfolio_permission"] != "yes":
                continue
            for e in p["exports"]:
                if e["seconds"] is None:
                    unknown += 1
                elif e["seconds"] >= min_s:
                    good.append(f"{p['name']}/{e['name']}")
        trims = sum(len(p["trims"]) for p in media["projects"])
        if len(good) >= need:
            res.update(passed=True, evidence=", ".join(good[:need]), now=f"{len(good)} export(s) of {min_s}s+")
        elif unknown:
            res.update(status="IN PROGRESS", cls="wip", now=f"{unknown} export(s) found but ffprobe isn't installed to check length")
        elif good or trims:
            res.update(status="IN PROGRESS", cls="wip",
                       now=f"{len(good)} of {need} qualifying exports. {trims} trims waiting in edits/")
        else:
            res["now"] = "No exports yet"

    elif kind == "http":
        domain = ctx["readiness"].get("website_domain", "").strip()
        if not domain:
            res["now"] = "Set website_domain in readiness.json once the site is up"
        else:
            ok, note = _http_ok(domain)
            res.update(passed=ok, evidence=note, now=note)

    elif kind == "plan_sections":
        plan = ctx["plan"]
        wanted = [s for s in plan["sections"] if s["number"] in check.get("sections", [])]
        holders = sum(s["placeholders"] for s in wanted)
        passing = sum(1 for s in wanted if s["verdict"] == "PASS" and s["placeholders"] == 0 and not s.get("stale"))
        changed = sum(1 for s in wanted if s.get("stale"))
        if wanted and passing == len(wanted):
            res.update(passed=True, evidence=f"{passing} section(s) pass, 0 placeholders", now="All sections pass")
        else:
            res.update(status="IN PROGRESS", cls="wip",
                       now=f"{passing} of {len(wanted)} pass. {holders} placeholder(s) left" + (f". {changed} need judging" if changed else ""))

    elif kind == "plan_figures":
        plan = ctx["plan"]
        s1 = next((s for s in plan["sections"] if s["number"] == 1), None)
        s8 = next((s for s in plan["sections"] if s["number"] == 8), None)
        left = (s1["bracket_figures"] if s1 else 0) + (s8["money_placeholders"] if s8 else 0)
        if left == 0:
            res.update(passed=True, evidence="no bracketed figures or §8 placeholders", now="Filled")
        else:
            res["now"] = f"{left} figure(s) still in [brackets] across §1.3 and §8 money sections"

    elif kind == "watcher_pending":
        res["now"] = "Waits on the Gmail / payments watcher (build 2)"

    if res["passed"]:
        since = _receipt(item["id"], res.get("evidence", ""))
        res.update(status="VERIFIED", cls="done", now=f"Receipt: pass since {since} · {res['now']}")
    return res


def readiness_status(media: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    readiness = _load_json(_office_dir() / "readiness.json", {"gates": []})
    ctx = {"media": media, "plan": plan, "readiness": readiness}
    gates, quick, total, verified, filed, wip = [], [], 0, 0, 0, 0
    for gate in readiness.get("gates", []):
        items = []
        for item in gate.get("items", []):
            r = _evaluate(item, ctx)
            total += 1
            verified += r["passed"]
            filed += r.get("filed", False)
            wip += r["status"] == "IN PROGRESS"
            items.append({"id": item["id"], "title": item["title"], "check": item.get("check", {}).get("label", ""), **r})
            if item.get("quick") and not r["passed"] and not r.get("filed"):
                quick.append({"title": item["title"], **item["quick"]})
        gates.append({"id": gate["id"], "name": gate["name"],
                      "score": f"{sum(1 for i in items if i['passed'])} / {len(items)}", "items": items})
    for extra in readiness.get("extra_quick_wins", []):
        quick.append(extra)
    quick.sort(key=lambda q: -q.get("weight", 0))
    ratio = verified / total if total else 0
    return {"gates": gates, "total": total, "verified": verified, "filed": filed, "in_progress": wip,
            "ratio": round(ratio, 2), "quick_wins": quick[:3], "fleet": readiness.get("fleet", {}),
            "website_domain": readiness.get("website_domain", "")}


# ---------------------------------------------------------------- research
def _split_multi(value: str) -> list[str]:
    """Split a Google Forms multi-select answer on commas that aren't inside
    brackets, so "Events (weddings, parties), Social media content" is two
    answers, not three."""
    out, depth, buf = [], 0, ""
    for ch in value or "":
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            if buf.strip():
                out.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        out.append(buf.strip())
    return out


def survey_status() -> dict[str, Any]:
    db = Path(ZEROGRAVITY_DB)
    if not db.exists():
        return {"total": 0, "warning": f"Survey database not found: {db}"}
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute("SELECT * FROM customer_survey_responses")]
    total = len(rows)

    def counts(field: str, multi: bool = False) -> list[list[Any]]:
        tally: dict[str, int] = {}
        for r in rows:
            values = _split_multi(r.get(field) or "") if multi else [(r.get(field) or "").strip()]
            for v in values:
                if v:
                    tally[v] = tally.get(v, 0) + 1
        return sorted(([k, v] for k, v in tally.items()), key=lambda kv: -kv[1])

    imported = [r.get("imported_at") for r in rows if r.get("imported_at")]
    services = counts("service_interest", multi=True)
    known = ("event", "social", "real estate", "construction")
    return {
        "total": total,
        "last_synced": max(imported) if imported else None,
        "services": services,
        "budgets": counts("budget_range"),
        "segments": counts("customer_type"),
        "used_before": counts("used_drone_services"),
        "would_consider": counts("would_consider_drone_services"),
        "buying_factors": counts("key_buying_factor", multi=True),
        "other_answers": [s for s in services if not any(k in s[0].lower() for k in known)],
        "warning": None,
    }


def research_status() -> dict[str, Any]:
    survey, survey_error = _safe(survey_status)
    competitors = _load_json(_office_dir() / "competitors.json", {"areas": [], "competitors": []})
    return {"survey": survey, "survey_error": survey_error, "competitors": competitors}


def _zerogravity_python() -> Path | None:
    root = Path(ZEROGRAVITY_ROOT)
    for rel in (".venv/Scripts/python.exe", "venv/Scripts/python.exe", ".venv/bin/python", "venv/bin/python"):
        candidate = root / rel
        if candidate.exists():
            return candidate
    return None


@business_office_bp.post("/survey/sync")
def survey_sync():
    """Run scripts/marketing/survey_pipeline.py with the zeroGravity repo's
    OWN virtualenv. Never sys.executable: in the frozen build that's this
    backend's .exe, and the pipeline's Google client libraries aren't
    bundled into it anyway, so the in-process runpy route can't work here."""
    script = Path(ZEROGRAVITY_ROOT) / "scripts" / "marketing" / "survey_pipeline.py"
    python = _zerogravity_python()
    if python is None:
        return jsonify({"ok": False, "message": "No .venv found in the zeroGravity repo. Create it and pip install -r requirements.txt."}), 400
    try:
        out = subprocess.run([str(python), str(script)], cwd=str(ZEROGRAVITY_ROOT), capture_output=True,
                             text=True, timeout=120, check=False)
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "message": "Survey sync timed out after 120s"}), 504
    tail = (out.stdout or out.stderr or "").strip().splitlines()[-3:]
    return jsonify({"ok": out.returncode == 0, "message": " · ".join(tail) or f"exit {out.returncode}"}), (200 if out.returncode == 0 else 500)


# ---------------------------------------------------------------- leads
def _leads_path() -> Path:
    return _office_dir() / "leads.json"


def leads_status() -> dict[str, Any]:
    data = _load_json(_leads_path(), {"leads": []})
    leads = data.get("leads", [])
    return {"leads": leads, "statuses": LEAD_STATUSES,
            "counts": {s: sum(1 for l in leads if l.get("status") == s) for s in LEAD_STATUSES}}


@business_office_bp.post("/leads")
def add_lead():
    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()
    if not name:
        return jsonify({"ok": False, "message": "Name is required"}), 400
    data = _load_json(_leads_path(), {"version": 1, "leads": []})
    lead = {
        "id": uuid.uuid4().hex[:8],
        "name": name[:120],
        "type": str(body.get("type", "Other"))[:60],
        "source": str(body.get("source", ""))[:60],
        "area": str(body.get("area", ""))[:60],
        "next_action": str(body.get("next_action", ""))[:200],
        "next_date": str(body.get("next_date", ""))[:20],
        "status": "contacted",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    data.setdefault("leads", []).append(lead)
    _save_json(_leads_path(), data)
    return jsonify({"ok": True, "lead": lead})


@business_office_bp.post("/leads/<lead_id>/status")
def set_lead_status(lead_id: str):
    status = str((request.get_json(silent=True) or {}).get("status", ""))
    if status not in LEAD_STATUSES:
        return jsonify({"ok": False, "message": "Unknown status"}), 400
    data = _load_json(_leads_path(), {"leads": []})
    for lead in data.get("leads", []):
        if lead.get("id") == lead_id:
            lead["status"] = status
            lead["updated_at"] = datetime.now().isoformat(timespec="seconds")
            _save_json(_leads_path(), data)
            return jsonify({"ok": True})
    return jsonify({"ok": False, "message": "Lead not found"}), 404


# ---------------------------------------------------------------- content
def _tags_path() -> Path:
    return _office_dir() / "content_tags.json"


def content_status(media: dict[str, Any]) -> dict[str, Any]:
    tags = _load_json(_tags_path(), {"tags": {}}).get("tags", {})
    projects = media["projects"]
    heroes = sum(1 for v in tags.values() if v == "hero")
    needs = []
    for p in projects:
        for cut in p["misplaced_cuts"]:
            needs.append({"title": f"{cut}", "sub": f"{p['name']}: looks like a finished cut sitting in edits/", "ev": "Move it to exports/ if it's final", "tag": "CHECK", "cls": "wip"})
        if not p["empty"] and not p["manifest_id"]:
            needs.append({"title": p["name"], "sub": "No manifest", "ev": "Run media/manifests/create_manifest.py", "tag": "MANIFEST", "cls": "conf"})
        elif p["manifest_id"] and p["portfolio_permission"] != "yes":
            sub = "Uses client footage: confirm every source project can be shown publicly" if p["type"] == "showreel" else "Portfolio permission not confirmed"
            needs.append({"title": p["name"], "sub": sub, "ev": "Update the manifest's rights", "tag": "PERMISSION", "cls": "conf"})
        if p["empty"] and not p["manifest_id"]:
            needs.append({"title": p["name"], "sub": "Empty project folder", "ev": "", "tag": "CLEAN UP", "cls": "todo"})
    select = max(projects, key=lambda p: len(p["trims"]), default=None)
    clips = []
    if select:
        for t in select["trims"]:
            key = f"{select['name']}/{t['name']}"
            clips.append({**t, "key": key, "tag": tags.get(key, "none")})
    stages = [
        ["CAPTURE", sum(p["raw"] for p in projects), "clips shot", "FLIGHTS"],
        ["INGEST", sum(1 for p in projects if p["manifest_id"]), "projects with manifest", "AUTO"],
        ["VERIFY", sum(1 for p in projects if p["portfolio_permission"] == "yes"), "permission ok", "YOU"],
        ["SELECT", heroes, "heroes", "YOU"],
        ["EDIT", sum(len(p["trims"]) + p["renders"] for p in projects), "trims + renders", "PREMIERE"],
        ["REVIEW", 0, "cuts checked", "YOU"],
        ["EXPORT", sum(len(p["exports"]) for p in projects), "exports", "AUTO CHECK"],
        ["PUBLISH", 0, "on website", "AUTO CHECK"],
        ["ARCHIVE", 0, "to NAS", "AUTO"],
    ]
    return {"root": media["root"], "exists": media["exists"], "ffprobe": media["ffprobe"],
            "projects": projects, "stages": stages, "needs": needs,
            "select_project": select["name"] if select else None, "clips": clips, "heroes": heroes}


@business_office_bp.post("/content/tag")
def tag_clip():
    body = request.get_json(silent=True) or {}
    key, tag = str(body.get("key", "")), str(body.get("tag", ""))
    if not key or tag not in TAG_VALUES:
        return jsonify({"ok": False, "message": "Bad tag"}), 400
    data = _load_json(_tags_path(), {"version": 1, "tags": {}})
    if tag == "none":
        data.setdefault("tags", {}).pop(key, None)
    else:
        data.setdefault("tags", {})[key] = tag
    _save_json(_tags_path(), data)
    return jsonify({"ok": True})


@business_office_bp.post("/content/open")
def open_premiere():
    name = str((request.get_json(silent=True) or {}).get("project", ""))
    project = next((p for p in scan_media()["projects"] if p["name"] == name), None)
    if not project or not project["prproj"]:
        return jsonify({"ok": False, "message": "No Premiere project file in this project"}), 404
    if not hasattr(os, "startfile"):
        return jsonify({"ok": False, "message": "Opening Premiere only works on Windows"}), 400
    os.startfile(project["prproj"][0])  # noqa: S606 - local desktop app, path comes from our own scan
    return jsonify({"ok": True, "message": f"Opening {Path(project['prproj'][0]).name}"})


# ---------------------------------------------------------------- judge routes
@business_office_bp.post("/judge/plan")
def judge_plan():
    body = request.get_json(silent=True) or {}
    which = body.get("sections")
    which = [int(n) for n in which] if isinstance(which, list) and which else None
    readiness = _load_json(_office_dir() / "readiness.json", {})
    try:
        sections = _plan_sections(readiness)
    except OSError as error:
        return jsonify({"ok": False, "message": f"Plan file not readable: {error}"}), 500
    result = run_plan_judge(sections, which, force=bool(body.get("force")))
    if not result["judged"] and not result["errors"]:
        return jsonify({"ok": True, "message": "Nothing changed since the last judge run"})
    msg = (f"Judged §{', §'.join(str(n) for n in result['judged'])}" if result["judged"] else "")
    if result["errors"]:
        msg = (msg + " · " if msg else "") + " · ".join(result["errors"])
    return jsonify({"ok": not result["errors"], "message": msg}), (200 if result["judged"] or not result["errors"] else 502)


@business_office_bp.post("/evidence/<item_id>/verify")
def verify_item(item_id: str):
    if item_id not in rubrics().get("evidence", {}):
        return jsonify({"ok": False, "message": "Unknown evidence item"}), 404
    try:
        verdict = verify_evidence(item_id)
    except JudgeError as error:
        return jsonify({"ok": False, "message": str(error)}), 502
    if verdict["passed"]:
        return jsonify({"ok": True, "message": f"Verified · expires {verdict['expiry_date'] or 'not stated'}"})
    return jsonify({"ok": False, "message": "Rejected: " + "; ".join(verdict["reasons"])})


# ---------------------------------------------------------------- company
def company_status(ready: dict[str, Any], leads: dict[str, Any]) -> dict[str, Any]:
    comp_gate = next((g for g in ready["gates"] if g["id"] == "compliance"), {"items": []})
    compliance = sum(1 for i in comp_gate["items"] if i["passed"]) / max(1, len(comp_gate["items"]))
    active = sum(leads["counts"].get(s, 0) for s in ("contacted", "replied", "quoted"))
    fleet = ready.get("fleet", {})
    fleet_total = sum(len(fleet.get(k, [])) for k in ("airworthy", "in_build", "planned")) or 1
    portfolio_item = next((i for g in ready["gates"] for i in g["items"] if i["id"] == "portfolio"), None)
    return {
        "level": 1, "xp": 0,
        "formula_note": "Placeholder formulas until targets are agreed",
        "stats": [
            ["REPUTATION", 0.0], ["PIPELINE", round(min(1, active / 10), 2)], ["REVENUE", 0.0],
            ["PORTFOLIO", 1.0 if portfolio_item and portfolio_item["passed"] else 0.0],
            ["FLEET", round(len(fleet.get("airworthy", [])) / fleet_total, 2)], ["COMPLIANCE", round(compliance, 2)],
        ],
    }


# ---------------------------------------------------------------- routes
@business_office_bp.get("/")
def office():
    return render_template("workspaces/business/office.html")


@business_office_bp.get("/data")
def office_data():
    media, media_error = _safe(scan_media)
    media = media or {"root": str(_media_root()), "exists": False, "ffprobe": bool(_FFPROBE), "projects": []}
    readiness_cfg = _load_json(_office_dir() / "readiness.json", {})
    plan, plan_error = _safe(plan_status, readiness_cfg)
    plan_for_checks = plan or {"sections": [], "cross_checks": []}
    ready, ready_error = _safe(readiness_status, media, plan_for_checks)
    leads, leads_error = _safe(leads_status)
    research, research_error = _safe(research_status)
    content, content_error = _safe(content_status, media)
    company, company_error = (None, None)
    if ready and leads:
        company, company_error = _safe(company_status, ready, leads)
    return jsonify({
        "phase": 1,
        "ready": ready, "ready_error": ready_error,
        "plan": plan, "plan_error": plan_error,
        "leads": leads, "leads_error": leads_error,
        "research": research, "research_error": research_error,
        "content": content, "content_error": content_error or media_error,
        "company": company, "company_error": company_error,
        "office_dir": str(_office_dir()),
        "frozen": bool(getattr(sys, "frozen", False)),
    })
