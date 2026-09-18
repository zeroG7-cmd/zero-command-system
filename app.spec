# PyInstaller spec for the Zero Command Flask backend.
#
# Build with:  pyinstaller app.spec
# Output lands in dist/zero-command-backend/zero-command-backend.exe
#
# This is a "onedir" build (a folder of files) rather than "onefile"
# (one .exe that self-extracts to a temp dir on every launch). onedir
# starts faster and doesn't re-unpack itself each time you open the app -
# worth it for a backend you're going to spawn every time the desktop
# app opens, at the cost of shipping a folder instead of a single file.

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('templates', 'templates'),
        ('static', 'static'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='zero-command-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Keep a console window for now so Flask/traceback errors are visible
    # while we're still shaking bugs out of the bundled build. Once this
    # is reliable, switch to console=False and log to a file instead.
    console=True,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='zero-command-backend',
)
