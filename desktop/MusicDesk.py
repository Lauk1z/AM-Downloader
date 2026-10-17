import argparse
import os
from pathlib import Path
import sys

from PySide6.QtCore import Qt, QTimer, QStandardPaths
from PySide6.QtWidgets import QMessageBox
from musicdesk.appearance import create_application
from musicdesk.core import Store, valid_backend
from musicdesk.window import MusicWindow
from musicdesk.runtime import bundled_backend, prepare_backend
from musicdesk import APP_NAME
from musicdesk.instance import SingleInstance


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-root")
    parser.add_argument("--data-dir")
    parser.add_argument("--screenshot")
    parser.add_argument("--smoke-test")
    parser.add_argument("--ui-smoke-test")
    parser.add_argument("--folder-import-smoke-test")
    parser.add_argument("--startup-smoke-test")
    parser.add_argument("--login-smoke-test")
    parser.add_argument("--audio-smoke-test")
    parser.add_argument("--audio-fixtures")
    parser.add_argument("--motion-smoke-test")
    parser.add_argument("--animation-benchmark")
    parser.add_argument("--lyrics-benchmark")
    args = parser.parse_args()
    if args.login_smoke_test and not args.data_dir: parser.error("--login-smoke-test requires an isolated --data-dir")
    if args.audio_smoke_test and (not args.data_dir or not args.audio_fixtures): parser.error("--audio-smoke-test requires an isolated --data-dir and --audio-fixtures")
    if args.motion_smoke_test and not args.data_dir: parser.error("--motion-smoke-test requires an isolated --data-dir")
    directory = Path(args.data_dir) if args.data_dir else Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MusicDesk"
    app = create_application(sys.argv[:1])
    instance = SingleInstance(directory, app)
    try:
        if not instance.acquire(): return 0
    except RuntimeError as error:
        QMessageBox.critical(None, APP_NAME, str(error)); return 1
    try:
        return run(app, args, directory, instance)
    finally:
        instance.close()


def run(app, args, directory, instance):
    store = Store(directory)
    executable = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    candidates = [args.backend_root, store.get("backend"), executable, executable.parent, r"D:\AppleMusicDecrypt-Windows"]
    root = next((Path(value) for value in candidates if value and valid_backend(value)), Path(args.backend_root or executable))
    if not args.backend_root and bundled_backend():
        if not store.get("library"):
            library = root / "downloads" if valid_backend(root) and (root / "downloads").is_dir() else Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MusicLocation)) / APP_NAME
            store.set("library", str(library))
        root = prepare_backend(directory)
    window = MusicWindow(root, directory); window.show()
    instance.activated.connect(window.tray.restore)
    if instance.pending_activation: window.tray.restore()
    if not any((args.smoke_test, args.ui_smoke_test, args.folder_import_smoke_test, args.login_smoke_test, args.audio_smoke_test, args.motion_smoke_test, args.screenshot, args.animation_benchmark, args.lyrics_benchmark)):
        QTimer.singleShot(0, window.start_backend)
    if args.startup_smoke_test:
        from musicdesk.verification import start_startup
        start_startup(window, args.startup_smoke_test)
    if args.login_smoke_test:
        from musicdesk.verification import start_login_ui
        start_login_ui(window, args.login_smoke_test)
    if args.audio_smoke_test:
        from musicdesk.verification import start_audio
        start_audio(window, args.audio_smoke_test, args.audio_fixtures)
    if args.motion_smoke_test:
        from musicdesk.verification import start_motion
        start_motion(window, args.motion_smoke_test)
    if args.smoke_test:
        from musicdesk.verification import start
        start(window, args.smoke_test)
    elif args.ui_smoke_test:
        from musicdesk.verification import start_ui
        start_ui(window, args.ui_smoke_test)
    elif args.folder_import_smoke_test:
        from musicdesk.verification import start_ui
        start_ui(window, args.folder_import_smoke_test, import_only=True)
    elif args.animation_benchmark:
        from musicdesk.verification import benchmark_animation
        benchmark_animation(window, args.animation_benchmark)
    elif args.lyrics_benchmark:
        from musicdesk.verification import benchmark_lyrics
        benchmark_lyrics(window, args.lyrics_benchmark)
    if args.screenshot:
        def capture():
            path = Path(args.screenshot); path.parent.mkdir(parents=True, exist_ok=True); window.grab().save(str(path)); window.tray.exit()
        QTimer.singleShot(5000, capture)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
