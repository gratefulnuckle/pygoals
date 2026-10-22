# PyInstaller spec: portable one-folder build -> dist\pygoals\pygoals.exe
# Build with:  .\build.ps1   (or: python -m PyInstaller --noconfirm pygoals.spec)
#
# settings.ini, state.json and logs\ are written next to pygoals.exe (see
# config.app_dir); nothing goes to AppData. The receiver\ web app is not needed
# at runtime (it is served by GitHub Pages) and is not bundled.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [("assets", "assets")]
# imageio-ffmpeg's ffmpeg binary renders the seamless card videos
datas += collect_data_files("imageio_ffmpeg", subdir="binaries")

hiddenimports = []
hiddenimports += collect_submodules("zeroconf")      # cython submodules imported dynamically
hiddenimports += collect_submodules("pychromecast")

excludes = ["tkinter", "pytest", "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets", "PyQt6.Qt3DCore",
            "PyQt6.QtMultimedia", "PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtPdf", "PyQt6.QtDesigner"]

a = Analysis(
    ["pygoals.py"],
    pathex=["."],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
# Trim what a tray app never loads: software OpenGL (~20 MB), Qt PDF, AVIF codec.
_drop = ("opengl32sw.dll", "qt6pdf.dll", "qpdf.dll", "_avif.")
a.binaries = [b for b in a.binaries if not any(d in b[0].lower().replace("\\", "/").rsplit("/", 1)[-1] for d in _drop)]
a.datas = [d for d in a.datas if not any(x in d[0].lower().replace("\\", "/").rsplit("/", 1)[-1] for x in _drop)]

pyz = PYZ(a.pure)

common = dict(
    exclude_binaries=True,
    debug=False,
    strip=False,
    upx=False,
    icon="assets/icon.ico",
)

# Tray app: no console window.
gui = EXE(pyz, a.scripts, [], name="pygoals", console=False, **common)
# Same program with a console; starts in --cli mode (see pygoals.main).
cli = EXE(pyz, a.scripts, [], name="pygoals-cli", console=True, **common)

coll = COLLECT(gui, cli, a.binaries, a.datas, strip=False, upx=False, name="pygoals")
