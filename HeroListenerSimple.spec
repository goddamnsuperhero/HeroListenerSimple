# PyInstaller spec for HeroListenerSimple — build with:  pyinstaller HeroListenerSimple.spec
# Produces a single windowed dist/HeroListenerSimple.exe.
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
# collect_all pulls each package's submodules, data files AND native binaries.
# sounddevice ships the PortAudio DLL; webrtcvad is a C extension; openai has data files.
for pkg in ("sounddevice", "webrtcvad", "openai"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=["pyinstaller_hooks"],   # local hook shadows the broken contrib webrtcvad hook
    runtime_hooks=[],
    excludes=["numpy", "matplotlib", "pandas", "scipy", "PIL"],  # keep the exe lean
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="HeroListenerSimple",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=False,          # windowed GUI app — no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
