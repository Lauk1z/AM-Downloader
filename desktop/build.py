"""Build an additive Windows desktop package; never copy account or music data."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
from musicdesk import APP_NAME
from build_backend import stage
from build_audio import build as build_audio
from build_sacd import build as build_sacd

ROOT = Path(__file__).resolve().parent


def main():
    audio_host = build_audio()
    sacd_host = build_sacd()
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QImage, QPainter
    from musicdesk.icons import app_icon_renderer, draw_icon
    from PIL import Image
    assets = ROOT / "artwork"; assets.mkdir(exist_ok=True)
    if not app_icon_renderer().isValid(): raise RuntimeError("Missing or invalid application SVG icon")
    image = QImage(1024, 1024, QImage.Format.Format_ARGB32); image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image); draw_icon(painter, "app", "white", QRectF(0, 0, 1024, 1024))
    painter.end(); image.save(str(assets / "musicdesk.png"))
    frames = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        frame = QImage(size, size, QImage.Format.Format_ARGB32); frame.fill(Qt.GlobalColor.transparent)
        painter = QPainter(frame); draw_icon(painter, "app", "white", QRectF(0, 0, size, size)); painter.end()
        rgba = frame.convertToFormat(QImage.Format.Format_RGBA8888)
        frames.append(Image.frombytes("RGBA", (size, size), bytes(rgba.constBits())))
    frames[-1].save(assets / "musicdesk.ico", sizes=[frame.size for frame in frames], append_images=frames[:-1])
    # Resolve Windows DLLs from the OS and this environment, not unrelated tools
    # on the host PATH (for example Poppler's incompatible ICU DLL).
    env = os.environ.copy()
    system = Path(env.get("SYSTEMROOT", r"C:\Windows"))
    env["PATH"] = os.pathsep.join(map(str, [Path(sys.executable).parent, Path(sys.base_prefix), system / "System32", system]))
    env["SYSTEMROOT"] = str(system)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", "--onedir", "--console" if "--console" in sys.argv else "--windowed", "--name", APP_NAME, "--icon", str(assets / "musicdesk.ico"), "--add-data", f"{ROOT / 'musicdesk_worker.py'};.", "--add-data", f"{ROOT / 'musicdesk_backend.py'};.", "--add-data", f"{ROOT / 'musicdesk_boot.py'};.", "--add-data", f"{assets};artwork", "--exclude-module", "PySide6.QtWebEngineCore", "--exclude-module", "PySide6.QtWebEngineWidgets", "--exclude-module", "pytest", str(ROOT / "MusicDesk.py")], cwd=ROOT, env=env, check=True)
    destination = ROOT / "dist" / APP_NAME
    audio_destination = destination / "native" / "bin"; audio_destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(audio_host, audio_destination / audio_host.name)
    shutil.copy2(sacd_host, audio_destination / sacd_host.name)
    stage(destination / "backend", compact=True)
    for name in ("README.md", "LICENSE.txt", "THIRD_PARTY_NOTICES.md", "TEST_REPORT.md"):
        shutil.copy2(ROOT / name, destination / name)
    if (ROOT / "licenses").is_dir(): shutil.copytree(ROOT / "licenses", destination / "licenses", dirs_exist_ok=True)
    source = destination / "source"; source.mkdir(exist_ok=True)
    for name in ("MusicDesk.py", "musicdesk_worker.py", "musicdesk_backend.py", "musicdesk_boot.py", "build.py", "build_backend.py", "backend_patches.py", "package_release.py", "requirements.txt", "requirements-build.txt", "README.md", "LICENSE.txt", "THIRD_PARTY_NOTICES.md", "TEST_REPORT.md"):
        shutil.copy2(ROOT / name, source / name)
    shutil.copytree(ROOT / "musicdesk", source / "musicdesk", ignore=shutil.ignore_patterns("__pycache__"), dirs_exist_ok=True)
    shutil.copytree(ROOT / "tests", source / "tests", ignore=shutil.ignore_patterns("__pycache__"), dirs_exist_ok=True)
    shutil.copytree(ROOT / "licenses", source / "licenses", dirs_exist_ok=True)
    shutil.copytree(assets, source / "artwork", dirs_exist_ok=True)
    shutil.copytree(ROOT / "boot-assets", source / "boot-assets", dirs_exist_ok=True)
    shutil.copy2(ROOT / "build_audio.py", source / "build_audio.py")
    shutil.copy2(ROOT / "build_sacd.py", source / "build_sacd.py")
    shutil.copytree(ROOT / "native", source / "native", ignore=shutil.ignore_patterns("bin"), dirs_exist_ok=True)
    print(f"Built: {destination / (APP_NAME + '.exe')}")


if __name__ == "__main__": main()
