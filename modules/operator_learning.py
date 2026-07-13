from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path
from typing import Any
from flask import Blueprint, current_app, redirect, render_template, request, url_for
operator_learning_bp=Blueprint("operator_learning",__name__,url_prefix="/operator/learning")
def _rnd_root()->Path:
    env=os.getenv("ZERO_GRAVITY_RND_ROOT")
    if env:return Path(env).expanduser().resolve()
    configured=current_app.config.get("ZERO_GRAVITY_RND_ROOT")
    if configured:return Path(configured).expanduser().resolve()
    return Path(current_app.root_path).resolve().parent/"zeroGravity-rnd"
def _load_json(path:Path)->dict[str,Any]:
    if not path.exists():raise FileNotFoundError(f"Required learning file not found: {path}")
    data=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data,dict):raise ValueError(f"Expected JSON object: {path}")
    return data
def _meaningful_text(path:Path)->bool:
    if not path.exists() or not path.is_file() or path.stat().st_size==0:return False
    try:text=path.read_text(encoding="utf-8")
    except UnicodeDecodeError:return path.stat().st_size>0
    for raw in text.splitlines():
        line=raw.strip()
        if not line or line.startswith("#") or line in {"...","TODO","TBD","[ ]","- [ ]"} or line.startswith("- [ ]"):continue
        return True
    return False
def _knowledge(metadata):
    return " > ".join(str(x) for x in [metadata.get("stat","Unknown"),*metadata.get("hierarchy",[])] if x)
def _track_paths():
    root=_rnd_root()/"learning"/"tracks"
    if not root.exists():return []
    return sorted(p.parent for p in root.rglob("metadata.json") if (p.parent/"progress.json").exists())
def _evidence(track,metadata,progress):
    units=metadata.get("units",[]); reqs=metadata.get("evidence_requirements",[])
    if not units:return {"current_unit":None,"items":[],"passed_count":0,"required_count":0,"complete":False}
    idx=max(0,min(int(progress.get("current_unit_index",0)),len(units)-1)); unit=units[idx]; unit_path=track/unit["path"]
    items=[]
    for req in reqs:
        p=unit_path/req["path"]; items.append({"name":req["name"],"relative_path":req["path"],"absolute_path":str(p),"passed":_meaningful_text(p)})
    passed=sum(1 for i in items if i["passed"])
    return {"current_unit":unit,"unit_path":str(unit_path),"items":items,"passed_count":passed,"required_count":len(items),"complete":bool(items) and passed==len(items)}
def _card(track):
    m=_load_json(track/"metadata.json"); p=_load_json(track/"progress.json"); units=m.get("units",[]); completed=len(p.get("completed_units",[])); total=len(units) or int(m.get("unit_count",0)); ev=_evidence(track,m,p)
    return {"id":m.get("id",track.name),"title":m.get("title",track.name),"provider":m.get("provider","Unknown"),"instructor":m.get("instructor",""),"difficulty":m.get("difficulty","Unknown"),"knowledge_path":_knowledge(m),"skill":m.get("skill",""),"source_url":m.get("source_url",""),"track_path":str(track),"completed_count":completed,"unit_count":total,"percentage":round((completed/total)*100,1) if total else 0.0,"total_xp":int(p.get("total_xp",0)),"status":p.get("status","In Progress"),"current_unit":ev["current_unit"],"evidence":ev}
def get_learning_hub_data():
    cards=[_card(p) for p in _track_paths()]; total=sum(c["unit_count"] for c in cards); done=sum(c["completed_count"] for c in cards)
    return {"tracks":cards,"track_count":len(cards),"total_units":total,"completed_units":done,"total_track_xp":sum(c["total_xp"] for c in cards),"overall_percentage":round((done/total)*100,1) if total else 0.0,"rnd_root":str(_rnd_root())}
def _selection(track_id):
    for i,p in enumerate(_track_paths(),1):
        if _load_json(p/"metadata.json").get("id",p.name)==track_id:return i
    raise ValueError(f"Learning track not found: {track_id}")
def _run(script_name,stdin):
    root=_rnd_root(); script=root/"learning"/"engine"/script_name
    if not script.exists():raise FileNotFoundError(f"Learning engine script not found: {script}")
    return subprocess.run([sys.executable,str(script)],input=stdin,text=True,capture_output=True,cwd=str(root),timeout=120,check=False)
@operator_learning_bp.route("/")
def dashboard():
    try:return render_template("workspaces/operator/learning.html",hub=get_learning_hub_data(),learning_error=None,action_output=request.args.get("output"))
    except Exception as e:return render_template("workspaces/operator/learning.html",hub=None,learning_error=str(e),action_output=None),500
@operator_learning_bp.post("/tracks/<track_id>/complete")
def complete_current_unit(track_id):
    try:r=_run("tracker.py",f"{_selection(track_id)}\n"); out=(r.stdout+"\n"+r.stderr).strip()
    except Exception as e:out=f"LEARNING ENGINE ERROR\n{e}"
    return redirect(url_for("operator_learning.dashboard",output=out[-5000:]))
@operator_learning_bp.post("/import")
def import_manifest():
    manifest=request.form.get("manifest_path","").strip()
    if not manifest:return redirect(url_for("operator_learning.dashboard",output="IMPORT ERROR\nEnter a manifest file or resource directory."))
    try:r=_run("import_manifest.py",f"{manifest}\ny\ny\n"); out=(r.stdout+"\n"+r.stderr).strip()
    except Exception as e:out=f"IMPORT ERROR\n{e}"
    return redirect(url_for("operator_learning.dashboard",output=out[-5000:]))
