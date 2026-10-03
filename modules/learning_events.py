"""Local learning event API and receipt feed."""
from __future__ import annotations
import io, json, os, runpy, subprocess, sys, tempfile, traceback
from pathlib import Path
from flask import Blueprint, current_app, jsonify, request
learning_events_bp=Blueprint('learning_events',__name__,url_prefix='/api/learning')
def root():
 p=os.getenv('ZERO_GRAVITY_RND_ROOT') or current_app.config.get('ZERO_GRAVITY_RND_ROOT'); return Path(p).expanduser().resolve() if p else Path(current_app.root_path).resolve().parent/'zeroGravity-rnd'

def _run_in_process(script: Path, args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Frozen-build fallback, same root cause and fix as operator_learning.py's
    _run_in_process(): once packaged, sys.executable is this app's own bundled
    .exe, not a real Python interpreter, so subprocess.run([sys.executable,
    script, ...]) tries to launch a second copy of the whole backend instead
    of running the script - it fights the running instance for port 5000 and
    never returns a usable response. This is why the live Boot.dev bridge's
    POST to /api/learning/events was hanging/failing (extension shows a red
    "sync queued" status) even though the extension and detection were fine.
    Runs the script in-process via runpy instead, with the same argv/stdout
    contract a real subprocess would give it, so behaviour doesn't change in
    dev mode (where this branch is never used)."""
    old_argv = sys.argv
    old_cwd = os.getcwd()
    old_stdin, old_stdout, old_stderr = sys.stdin, sys.stdout, sys.stderr
    old_path = list(sys.path)
    stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
    returncode = 0
    try:
        os.chdir(cwd)
        sys.argv = [str(script), *args]
        sys.stdin = io.StringIO("")
        sys.stdout = stdout_buf
        sys.stderr = stderr_buf
        sys.path.insert(0, str(script.parent))
        try:
            runpy.run_path(str(script), run_name="__main__")
        except SystemExit as exc:
            returncode = 0 if exc.code in (None, 0) else 1
        except Exception:
            traceback.print_exc(file=stderr_buf)
            returncode = 1
    finally:
        sys.argv = old_argv
        os.chdir(old_cwd)
        sys.stdin, sys.stdout, sys.stderr = old_stdin, old_stdout, old_stderr
        sys.path[:] = old_path
    return subprocess.CompletedProcess(
        args=[str(script), *args], returncode=returncode,
        stdout=stdout_buf.getvalue(), stderr=stderr_buf.getvalue(),
    )

def _run_event_script(script: Path, args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    if getattr(sys, "frozen", False):
        return _run_in_process(script, args, cwd)
    return subprocess.run([sys.executable, str(script), *args], cwd=str(cwd), text=True, capture_output=True, timeout=60)

@learning_events_bp.post('/events')
def event():
 data=request.get_json(silent=True) or {}
 if not data:return jsonify({'error':'JSON event required'}),400
 r=root(); script=r/'learning/engine/process_learning_event.py'
 with tempfile.NamedTemporaryFile('w',suffix='.json',delete=False,encoding='utf-8') as f: json.dump(data,f); name=f.name
 try:
  cp=_run_event_script(script,[name],r)
  if cp.returncode:return jsonify({'error':(cp.stderr or cp.stdout).strip()}),400
  return jsonify(json.loads(cp.stdout))
 finally: Path(name).unlink(missing_ok=True)
@learning_events_bp.get('/receipts/latest')
def latest():
 folder=root()/'operator_core/events/receipts'; files=sorted(folder.glob('*.json'),reverse=True) if folder.exists() else []
 return jsonify(json.loads(files[0].read_text(encoding='utf-8')) if files else {})

@learning_events_bp.get('/health')
def health():
 return jsonify({'status':'online','service':'Operator Zero Learning Events','rnd_root':str(root())})
