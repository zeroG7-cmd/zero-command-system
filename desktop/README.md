# zero-command-desktop

## Milestone 2 — bundle the Flask backend, spawn it from Electron

Electron now starts the Flask backend itself (as a bundled .exe) instead of
you running `python app.py` by hand, waits until it's actually answering
requests, then opens the window — and kills the backend when you close it.

### One-time setup

From the `zero-command-system` repo root (one level up from this folder):

```
pip install -r requirements.txt
pip install pyinstaller
pyinstaller app.spec
```

That produces `dist/zero-command-backend/zero-command-backend.exe`. Rerun
`pyinstaller app.spec` any time you change `app.py`, `modules/`,
`templates/`, or `static/` — it's not auto-rebuilt.

Then, in this `desktop/` folder:

```
npm install
```

### Running it

```
npm start
```

You should see a console window pop up first (that's the bundled Flask
backend logging startup, kept visible on purpose for now — see `app.spec`),
then the Electron window opens once it's actually ready. Closing the window
kills the backend too — check Task Manager if you want to confirm nothing's
left running on port 5000.

### What changed from Milestone 1

- `app.py` — Flask's `template_folder`/`static_folder` are now resolved
  explicitly (`_resource_base_path()`), because the default (relative to
  `__file__`) breaks once this file is unpacked inside a PyInstaller
  bundle. `debug=True` is now conditional — it stays on for normal
  `python app.py` dev, and switches off automatically in the frozen build,
  because Werkzeug's reloader can't re-exec a frozen .exe the way it
  re-execs a Python script.
- `requirements.txt` — just `flask`; everything else the app imports is
  stdlib.
- `app.spec` — PyInstaller build config. Onedir (a folder), not onefile
  (a single self-extracting .exe) — onedir starts faster since it isn't
  re-unpacking itself on every launch, which matters since Electron will
  spawn it every time you open the app.
- `main.js` — spawns the bundled .exe with `ZERO_GRAVITY_RND_ROOT` and
  `ZEROGRAVITY_ROOT` set explicitly. `config.py` computes those by walking
  up from its own file location by default, which also breaks once frozen
  (same root cause as the template/static path issue) — but it already
  supported overriding both via env vars, so no changes were needed there.
  Polls the backend over HTTP until it responds rather than guessing with a
  fixed delay, and kills the whole process tree on quit (`taskkill /T` on
  Windows — a plain `.kill()` only signals the immediate PID and can leave
  the real Flask process running).

### Not yet handled

- No error screen if the backend fails to start (check the console output).
- No packaging of the whole app into an installer — that's a later step,
  once the electron-builder/electron-forge choice gets made deliberately
  rather than defaulted into.
- Next milestone after this one: Three.js for the 3D rooms, per the vision
  doc.
