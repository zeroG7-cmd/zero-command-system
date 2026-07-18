"""Operator Execution Hub routes."""
from __future__ import annotations
import json, os, sys
from pathlib import Path
from flask import Blueprint, current_app, jsonify, render_template, request
bp=Blueprint("operator_execution",__name__,url_prefix="/operator/execution")
def root():
 p=os.getenv("ZERO_GRAVITY_RND_ROOT") or current_app.config.get("ZERO_GRAVITY_RND_ROOT")
 return Path(p).expanduser().resolve() if p else Path(current_app.root_path).resolve().parent/"zeroGravity-rnd"
def service():
 r=root(); sys.path.insert(0,str(r)) if str(r) not in sys.path else None
 from operator_core.execution.service import create_execution, execution_summary, list_executions
 return create_execution, execution_summary, list_executions
@bp.get("/")
def dashboard():
 _,summary,listing=service(); return render_template("workspaces/operator/execution.html",summary=summary(),records=listing(30),error=None)
@bp.post("/api")
def create():
 create_execution,_,_=service()
 try: return jsonify(create_execution(request.get_json(silent=True) or {})),201
 except ValueError as e: return jsonify({"error":str(e)}),400
