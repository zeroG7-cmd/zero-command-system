"""Local learning event API and receipt feed."""
from __future__ import annotations
import json, os, subprocess, sys, tempfile
from pathlib import Path
from flask import Blueprint, current_app, jsonify, request
learning_events_bp=Blueprint('learning_events',__name__,url_prefix='/api/learning')
def root():
 p=os.getenv('ZERO_GRAVITY_RND_ROOT') or current_app.config.get('ZERO_GRAVITY_RND_ROOT'); return Path(p).expanduser().resolve() if p else Path(current_app.root_path).resolve().parent/'zeroGravity-rnd'
@learning_events_bp.post('/events')
def event():
 data=request.get_json(silent=True) or {}
 if not data:return jsonify({'error':'JSON event required'}),400
 r=root(); script=r/'learning/engine/process_learning_event.py'
 with tempfile.NamedTemporaryFile('w',suffix='.json',delete=False,encoding='utf-8') as f: json.dump(data,f); name=f.name
 try:
  cp=subprocess.run([sys.executable,str(script),name],cwd=r,text=True,capture_output=True,timeout=60)
  if cp.returncode:return jsonify({'error':(cp.stderr or cp.stdout).strip()}),400
  return jsonify(json.loads(cp.stdout))
 finally: Path(name).unlink(missing_ok=True)
@learning_events_bp.get('/receipts/latest')
def latest():
 folder=root()/'learning/operator/receipts'; files=sorted(folder.glob('*.json'),reverse=True) if folder.exists() else []
 return jsonify(json.loads(files[0].read_text(encoding='utf-8')) if files else {})

@learning_events_bp.get('/health')
def health():
 return jsonify({'status':'online','service':'Operator Zero Learning Events','rnd_root':str(root())})
