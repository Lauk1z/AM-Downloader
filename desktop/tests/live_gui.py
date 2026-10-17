"""Opt-in native GUI, catalog search and real JSON worker integration check."""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from musicdesk.window import MusicWindow


def wait_until(check, timeout=30):
    deadline = time.monotonic() + timeout
    while not check():
        loop = QEventLoop(); QTimer.singleShot(100, loop.quit); loop.exec()
        if time.monotonic() > deadline: raise TimeoutError("GUI operation timed out")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--root", required=True); parser.add_argument("--output", required=True)
    args = parser.parse_args(); output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=True)
    app = QApplication([]); app.setQuitOnLastWindowClosed(False)
    window = MusicWindow(Path(args.root), output / "data"); window.audio.setMuted(True); window.show()
    events = []; window.client.event.connect(events.append)
    try:
        wait_until(lambda: bool(window.tracks))
        window.play_tracks(window.tracks[:1]); wait_until(lambda: window.media.position() > 700)
        window.grab().save(str(output / "playing.png"))
        window.media.pause()
        window.navigate("songs"); window.grab().save(str(output / "songs.png"))
        window.navigate("settings"); window.grab().save(str(output / "settings.png"))
        window.navigate("search"); window.search.setText("Eagles Hotel California"); window.search_changed()
        wait_until(lambda: len(getattr(window, "search_cards", [])) > 0, 35)
        wait_until(lambda: bool(window.art_cache), 20)
        window.grab().save(str(output / "search.png"))
        print(json.dumps({"catalog_results": len(window.search_cards), "artwork_cached": len(window.art_cache)}), flush=True)
        window.enqueue(["https://music.apple.com/cn/song/hotel-california/635770202"], "alac")
        wait_until(lambda: any(event["event"] in {"finished", "fatal"} for event in events), 180)
        result = next(event for event in reversed(events) if event["event"] in {"finished", "fatal"})
        assert result.get("state") == "DONE", result
        window.grab().save(str(output / "queue.png"))
        print(json.dumps(result), flush=True)
        window.search.clear(); window.navigate("recent"); window.resize(1040, 700)
        loop = QEventLoop(); QTimer.singleShot(400, loop.quit); loop.exec()
        window.grab().save(str(output / "minimum.png"))
    finally:
        window.tray.exit()
        wait_until(lambda: not window.isVisible(), 35)
