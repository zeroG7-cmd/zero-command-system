// main.js — the Electron "main process".
//
// This is a Node.js process (not a browser environment) that owns the app's
// lifecycle and creates OS-level windows. It has full access to Node and the
// OS, but no DOM. Each window it opens loads a web page into a separate
// "renderer process" — that's the one with the DOM, and it runs the actual
// Flask-served HTML/JS/CSS. The two processes are isolated from each other
// by default; contextIsolation below keeps it that way until we deliberately
// bridge them later (e.g. for native file access, tray icons, etc).
//
// Milestone 2: instead of you starting Flask by hand, this spawns the
// PyInstaller-bundled backend as a child process, waits for it to actually
// be answering requests, then opens the window. On quit, it kills that
// child process — Flask never keeps running in the background after you
// close the app.

const { app, BrowserWindow } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const http = require('http');

const FLASK_URL = 'http://127.0.0.1:5000';

// dist/zero-command-backend/zero-command-backend[.exe], built by running
// `pyinstaller app.spec` from the zero-command-system repo root (one level
// up from this desktop/ folder). PyInstaller only appends .exe on Windows -
// the Linux build produces an extension-less ELF binary - so this has to be
// platform-aware or the spawn below silently can't find it on Ubuntu.
const BACKEND_EXE_NAME = process.platform === 'win32'
  ? 'zero-command-backend.exe'
  : 'zero-command-backend';
const BACKEND_EXE = path.join(
  __dirname, '..', 'dist', 'zero-command-backend', BACKEND_EXE_NAME
);

// The "zero Gravity" folder that holds zero-command-system, zeroGravity-rnd
// and zeroGravity as siblings. config.py computes this itself by walking up
// from its own file location — which breaks once app.py is bundled and
// running from inside the PyInstaller dist folder instead of the repo. So
// we compute it here (where the folder layout is known and stable) and
// hand it to the backend explicitly via env vars, which config.py already
// supports as an override.
const WORKSPACE_ROOT = path.join(__dirname, '..', '..');

let backendProcess = null;
let mainWindow = null;

function startBackend() {
  return new Promise((resolve, reject) => {
    backendProcess = spawn(BACKEND_EXE, [], {
      cwd: path.dirname(BACKEND_EXE),
      env: {
        ...process.env,
        ZERO_GRAVITY_RND_ROOT: path.join(WORKSPACE_ROOT, 'zeroGravity-rnd'),
        ZEROGRAVITY_ROOT: path.join(WORKSPACE_ROOT, 'zeroGravity'),
      },
    });

    backendProcess.stdout.on('data', (data) => process.stdout.write(`[flask] ${data}`));
    backendProcess.stderr.on('data', (data) => process.stderr.write(`[flask] ${data}`));

    backendProcess.on('error', (err) => {
      // Most likely cause: the .exe doesn't exist yet because
      // `pyinstaller app.spec` hasn't been run.
      reject(err);
    });

    backendProcess.on('exit', (code) => {
      console.log(`Flask backend exited with code ${code}`);
      backendProcess = null;
    });

    waitForServer(resolve, reject);
  });
}

// Spawning the process doesn't mean Flask is ready yet — poll until it
// actually answers a request instead of guessing with a fixed delay.
function waitForServer(resolve, reject, attempt = 0) {
  const MAX_ATTEMPTS = 40; // ~20s at 500ms intervals
  const request = http.get(FLASK_URL, () => resolve());
  request.on('error', () => {
    if (attempt >= MAX_ATTEMPTS) {
      reject(new Error('Flask backend did not respond within 20s'));
      return;
    }
    setTimeout(() => waitForServer(resolve, reject, attempt + 1), 500);
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    title: 'Zero Command',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadURL(FLASK_URL);
}

app.whenReady().then(async () => {
  try {
    await startBackend();
  } catch (err) {
    // Milestone-2 scope: fail loudly rather than silently showing a blank
    // window. A proper error screen can come later.
    console.error('Failed to start the Flask backend:', err.message);
    console.error(`Looked for it at: ${BACKEND_EXE}`);
    console.error('Have you run "pyinstaller app.spec" in zero-command-system yet?');
  }

  createWindow();

  // macOS convention: clicking the dock icon with no windows open should
  // reopen one, rather than relaunching the app.
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

function killBackend() {
  if (!backendProcess) return;

  if (process.platform === 'win32') {
    // On Windows, backendProcess.kill() only signals the immediate PID.
    // PyInstaller's bootloader can leave the real Flask process as a
    // child of that PID, which survives the kill and keeps port 5000
    // held open. taskkill /T kills the whole process tree.
    spawn('taskkill', ['/pid', backendProcess.pid, '/f', '/t']);
  } else {
    backendProcess.kill();
  }
  backendProcess = null;
}

// On Windows/Linux, closing the last window should quit the app.
// On macOS, apps conventionally stay running in the dock until Cmd+Q —
// either way, the backend must not outlive the window.
app.on('window-all-closed', () => {
  killBackend();
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', killBackend);
