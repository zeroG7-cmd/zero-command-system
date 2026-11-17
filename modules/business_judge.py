"""zeroGravity Office - AI judge (build 2a).

Two Tier-2 checks that make the Office hard to cheat:

1. Plan judge: each King's Trust section + its rubric
   (zeroGravity/operations/office/judge_rubrics.json) goes to Claude, which
   returns met / not met per criterion. Template placeholders, copied
   template examples, filler and numbers that don't add up all fail. A
   cross-check call compares sections against each other and against
   pricing_strategy.md. Results land in operations/office/plan_judge.json
   with a hash per section, so the Office can flag sections that changed
   since they were last judged.

2. Evidence check: a certificate or policy in operations/office/evidence/<item>/
   is read by Claude (PDF or image). The verdict, which can hold ID numbers,
   stays inside the gitignored evidence folder. Only pass/fail and the expiry
   date go into the tracked receipt.

Uses the Messages API over plain urllib on purpose: the frozen backend only
bundles Flask, so no SDK dependency. API key: ANTHROPIC_API_KEY env var, or
zeroGravity/credentials/anthropic_api_key.txt (credentials/ is gitignored).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any

from config import ZEROGRAVITY_ROOT

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5-5"
EVIDENCE_TYPES = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
                  ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
MAX_EVIDENCE_BYTES = 20 * 1024 * 1024


class JudgeError(RuntimeError):
    pass


# ---------------------------------------------------------------- io
def office_dir() -> Path:
    return Path(ZEROGRAVITY_ROOT) / "operations" / "office"


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def _save(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def rubrics() -> dict[str, Any]:
    return _load(office_dir() / "judge_rubrics.json", {"sections": {}, "evidence": {}})


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


# ---------------------------------------------------------------- api
def api_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    path = Path(ZEROGRAVITY_ROOT) / "credentials" / "anthropic_api_key.txt"
    if path.exists():
        return path.read_text(encoding="utf-8").strip() or None
    return None


def api_ready() -> bool:
    return api_key() is not None


def _extract_json(text: str) -> Any:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if fence:
        text = fence.group(1).strip()
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise JudgeError("Judge reply had no JSON in it")
    end = max(text.rfind("}"), text.rfind("]"))
    return json.loads(text[start:end + 1])


def call_claude(content: list[dict[str, Any]], system: str, model: str | None = None, max_tokens: int = 2000) -> Any:
    key = api_key()
    if not key:
        raise JudgeError("No Anthropic API key. Put it in zeroGravity/credentials/anthropic_api_key.txt or set ANTHROPIC_API_KEY.")
    body = json.dumps({
        "model": model or rubrics().get("model") or DEFAULT_MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": content}],
    }).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, method="POST", headers={
        "x-api-key": key, "anthropic-version": API_VERSION, "content-type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("error", {}).get("message", detail)
        except json.JSONDecodeError:
            pass
        raise JudgeError(f"Claude API {error.code}: {detail[:300]}") from None
    except urllib.error.URLError as error:
        raise JudgeError(f"Couldn't reach the Claude API: {error.reason}") from None
    # The reply can start with a thinking block, so only read text blocks.
    text = "".join(b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text")
    return _extract_json(text)


# ---------------------------------------------------------------- plan judge
JUDGE_SYSTEM = (
    "You are a strict but fair assessor for the King's Trust Enterprise Programme in the UK. "
    "You judge one section of a young founder's business plan against a rubric. "
    "The plan was written into a template: text after 'Example:' lines, bullet lists of things to "
    "'consider', and anything in [square brackets] are template material, not the founder's answer. "
    "A criterion is NOT met if the answer is missing, still a placeholder, copied template guidance, "
    "vague filler, or contradicted by numbers elsewhere in the section. Be specific and short. "
    "Reply with JSON only."
)


def judge_section(number: int, body: str, model: str | None = None) -> dict[str, Any]:
    rub = rubrics().get("sections", {}).get(str(number))
    if not rub:
        raise JudgeError(f"No rubric for section {number}")
    criteria = "\n".join(f"- {c}" for c in rub["criteria"])
    prompt = (
        f"Section {number} of the plan:\n<section>\n{body.strip()}\n</section>\n\n"
        f"Rubric criteria:\n{criteria}\n\n"
        'Return JSON: {"items": [{"c": "<criterion as given>", "met": true|false, '
        '"note": "<max 20 words; quote the placeholder or the problem>"}], '
        '"verdict": "PASS" | "NEEDS WORK" | "FAIL"}. '
        "PASS only if every criterion is met. FAIL if half or more are not met."
    )
    out = call_claude([{"type": "text", "text": prompt}], JUDGE_SYSTEM, model)
    items = [[str(i.get("c", ""))[:160], bool(i.get("met")), str(i.get("note", ""))[:240]] for i in out.get("items", [])]
    verdict = str(out.get("verdict", "NEEDS WORK")).upper()
    if verdict not in {"PASS", "NEEDS WORK", "FAIL"}:
        verdict = "NEEDS WORK"
    if verdict == "PASS" and not all(i[1] for i in items):
        verdict = "NEEDS WORK"
    return {"title": rub["title"], "verdict": verdict, "items": items}


def cross_check(sections: dict[int, str], model: str | None = None) -> list[list[str]]:
    pricing = Path(ZEROGRAVITY_ROOT) / "docs" / "01_business_plan" / "pricing_strategy.md"
    pricing_text = pricing.read_text(encoding="utf-8") if pricing.exists() else "(pricing_strategy.md not found)"
    focus = "\n".join(f"- {f}" for f in rubrics().get("cross_check_focus", []))
    parts = "\n\n".join(f"<section n=\"{n}\">\n{sections[n].strip()}\n</section>" for n in sorted(sections) if n in (1, 3, 4, 5, 7))
    prompt = (
        f"Business plan sections:\n{parts}\n\n<pricing_strategy>\n{pricing_text}\n</pricing_strategy>\n\n"
        f"Check these for contradictions:\n{focus}\n\n"
        'Return JSON: {"checks": [{"title": "<e.g. §1.3 vs §1.2>", "status": "FAIL" | "MISMATCH" | "OK", '
        '"note": "<max 25 words, with the actual numbers>"}]}. Up to 6 checks, problems first.'
    )
    out = call_claude([{"type": "text", "text": prompt}], JUDGE_SYSTEM, model, max_tokens=1500)
    return [[str(c.get("title", ""))[:80], str(c.get("status", "MISMATCH")).upper()[:10], str(c.get("note", ""))[:240]]
            for c in out.get("checks", [])]


def run_plan_judge(sections: dict[int, str], which: list[int] | None, force: bool = False) -> dict[str, Any]:
    """Judge the given sections (or every section that changed since last
    judged when which is None). Saves plan_judge.json and returns a summary."""
    path = office_dir() / "plan_judge.json"
    judge = _load(path, {"version": 1, "sections": {}, "cross_checks": []})
    hashes = judge.setdefault("hashes", {})
    targets = which or [n for n in sorted(sections) if force or hashes.get(str(n)) != text_hash(sections[n])]
    judged, errors = [], []
    for n in targets:
        if n not in sections:
            continue
        try:
            judge.setdefault("sections", {})[str(n)] = judge_section(n, sections[n])
            hashes[str(n)] = text_hash(sections[n])
            judged.append(n)
        except JudgeError as error:
            errors.append(f"§{n}: {error}")
            break  # same key / network problem will hit every section
    if judged and not errors:
        try:
            judge["cross_checks"] = cross_check(sections)
        except JudgeError as error:
            errors.append(f"cross-check: {error}")
    if judged:
        judge.update(source="claude-api", model=rubrics().get("model") or DEFAULT_MODEL,
                     run_at=datetime.now().isoformat(timespec="minutes"))
        _save(path, judge)
    return {"judged": judged, "errors": errors}


def stale_sections(sections: dict[int, str]) -> list[int]:
    hashes = _load(office_dir() / "plan_judge.json", {}).get("hashes", {})
    if not hashes:  # judged by hand before build 2a: every section counts as unchecked by the API
        return sorted(sections)
    return [n for n in sorted(sections) if hashes.get(str(n)) != text_hash(sections[n])]


# ---------------------------------------------------------------- evidence
EVIDENCE_SYSTEM = (
    "You read UK drone compliance documents (CAA registrations, certificates, insurance schedules) "
    "and extract facts exactly as printed. Never guess a date or name that isn't visible. Reply with JSON only."
)


def evidence_file(item_id: str) -> Path | None:
    folder = office_dir() / "evidence" / item_id
    if not folder.is_dir():
        return None
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in EVIDENCE_TYPES]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def _owner_name() -> str | None:
    path = office_dir() / "evidence" / "owner.txt"
    return path.read_text(encoding="utf-8").strip() if path.exists() else None


def _name_matches(found: str | None, owner: str) -> bool:
    if not found:
        return False
    a = {t for t in re.split(r"[^a-z]+", found.lower()) if len(t) > 1}
    b = {t for t in re.split(r"[^a-z]+", owner.lower()) if len(t) > 1}
    return len(a & b) >= min(2, len(b))


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year + years, day=28)


def _parse_date(value: Any) -> date | None:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date() if value else None
    except ValueError:
        return None


def verify_evidence(item_id: str) -> dict[str, Any]:
    spec = rubrics().get("evidence", {}).get(item_id)
    if not spec:
        raise JudgeError(f"No evidence rules for {item_id}")
    path = evidence_file(item_id)
    if path is None:
        raise JudgeError(f"No PDF or image in evidence/{item_id}/")
    if path.stat().st_size > MAX_EVIDENCE_BYTES:
        raise JudgeError("File is over 20 MB. Export a smaller PDF or a screenshot.")
    media = EVIDENCE_TYPES[path.suffix.lower()]
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    block = ({"type": "document", "source": {"type": "base64", "media_type": media, "data": data}}
             if media == "application/pdf" else
             {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}})
    prompt = (
        f"Expected document: {spec['doc']}.\n"
        'Return JSON: {"document_type": "<what this actually is>", "matches_expected": true|false, '
        '"holder_name": "<name as printed or null>", "reference": "<ID or policy number or null>", '
        '"issue_date": "YYYY-MM-DD or null", "expiry_date": "YYYY-MM-DD or null", '
        '"commercial_cover": true|false|null, "notes": "<max 25 words>"}'
    )
    out = call_claude([block, {"type": "text", "text": prompt}], EVIDENCE_SYSTEM, max_tokens=800)

    today = date.today()
    issue = _parse_date(out.get("issue_date"))
    expiry = _parse_date(out.get("expiry_date"))
    if expiry is None and issue and spec.get("valid_years"):
        expiry = _add_years(issue, int(spec["valid_years"]))
    reasons = []
    if not out.get("matches_expected"):
        reasons.append(f"Not the expected document (looks like: {out.get('document_type', 'unknown')})")
    if expiry and expiry < today:
        reasons.append(f"Expired on {expiry.isoformat()}")
    if spec.get("require_commercial") and out.get("commercial_cover") is not True:
        reasons.append("Commercial use cover not confirmed")
    owner = _owner_name()
    if owner and not _name_matches(out.get("holder_name"), owner):
        reasons.append("Holder name doesn't match evidence/owner.txt")
    verdict = {
        "item": item_id, "file": path.name, "file_hash": file_hash(path),
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "passed": not reasons, "reasons": reasons,
        "expiry_date": expiry.isoformat() if expiry else None,
        "extracted": out,  # may hold ID numbers: lives in the gitignored vault only
    }
    _save(path.parent / "verdict.json", verdict)
    return verdict


def evidence_state(item_id: str) -> dict[str, Any]:
    """What the READY board should show for an evidence item, re-checked on
    every load so a lapsed certificate re-locks itself."""
    path = evidence_file(item_id)
    if path is None:
        return {"state": "none"}
    verdict = _load(path.parent / "verdict.json", None)
    if not verdict or verdict.get("file_hash") != file_hash(path):
        return {"state": "filed", "file": path.name}
    expiry = _parse_date(verdict.get("expiry_date"))
    if verdict.get("passed") and expiry and expiry < date.today():
        return {"state": "expired", "file": path.name, "expiry": expiry.isoformat()}
    if verdict.get("passed"):
        return {"state": "verified", "file": path.name, "expiry": verdict.get("expiry_date"),
                "doc": verdict.get("extracted", {}).get("document_type", "")}
    return {"state": "rejected", "file": path.name, "reasons": verdict.get("reasons", [])}
