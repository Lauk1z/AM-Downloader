import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from test_playlists_ui import app


ROOT = Path(__file__).resolve().parents[1]
CHILD = r'''
import json, os, sys
from pathlib import Path
from PySide6.QtCore import QCoreApplication, QTimer
from musicdesk.instance import SingleInstance
app = QCoreApplication([])
directory, output, gate = map(Path, sys.argv[1:])
instance = SingleInstance(directory, app)
if not instance.acquire(): raise SystemExit(0)
state = {"pid": os.getpid(), "activations": 0}
def save(): output.write_text(json.dumps(state))
def activate():
    state["activations"] += 1; save()
instance.activated.connect(activate)
save()
timer = QTimer(); timer.timeout.connect(lambda: app.quit() if gate.exists() else None); timer.start(30)
QTimer.singleShot(15000, app.quit)
try: app.exec()
finally: instance.close()
'''


def launch(profile, output, gate):
    return subprocess.Popen([sys.executable, "-c", CHILD, str(profile), str(output), str(gate)], cwd=ROOT)


def until(check, timeout=10):
    deadline = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < deadline
        time.sleep(.04)


def read(path):
    try: return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError): return {}


def stop(processes, gates):
    for gate in gates: gate.touch()
    for process in processes:
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)


def test_repeated_launches_activate_one_primary_and_release_lock_on_exit(tmp_path):
    profile, output, gate = tmp_path / "profile", tmp_path / "primary.json", tmp_path / "stop"
    processes = [launch(profile, output, gate)]
    try:
        until(lambda: bool(read(output)))
        primary = read(output)["pid"]
        for _ in range(3):
            second = launch(profile, tmp_path / "unused.json", gate); processes.append(second)
            assert second.wait(timeout=10) == 0
        until(lambda: read(output).get("activations") == 3)
        assert read(output)["pid"] == primary and processes[0].poll() is None
        assert not (tmp_path / "unused.json").exists()
    finally: stop(processes, [gate])
    assert not (profile / "app-instance.lock").exists()
    gate.unlink()
    restarted = launch(profile, output, gate)
    try:
        until(lambda: bool(read(output)) and read(output).get("pid") != primary)
        assert read(output)["activations"] == 0
    finally: stop([restarted], [gate])


def test_simultaneous_launches_choose_one_primary_without_duplicate_startup(tmp_path):
    gate = tmp_path / "stop"
    outputs = [tmp_path / f"{i}.json" for i in range(5)]
    processes = [launch(tmp_path / "profile", output, gate) for output in outputs]
    try:
        until(lambda: sum(process.poll() is None for process in processes) == 1)
        winners = [path for path in outputs if read(path)]
        assert len(winners) == 1
        until(lambda: read(winners[0]).get("activations") == 4)
        assert all(process.returncode in (None, 0) for process in processes)
    finally: stop(processes, [gate])


def test_dead_process_lock_recovers_and_separate_profiles_can_coexist(tmp_path):
    processes, gates = [], [tmp_path / "stop-a", tmp_path / "stop-b"]
    try:
        first = launch(tmp_path / "a", tmp_path / "a.json", gates[0]); processes.append(first)
        until(lambda: bool(read(tmp_path / "a.json")))
        first.kill(); first.wait(timeout=5)  # Only this test's child; leave its lock behind.
        assert (tmp_path / "a/app-instance.lock").exists()
        replacement = launch(tmp_path / "a", tmp_path / "again.json", gates[0]); processes.append(replacement)
        other = launch(tmp_path / "b", tmp_path / "b.json", gates[1]); processes.append(other)
        until(lambda: bool(read(tmp_path / "again.json")) and bool(read(tmp_path / "b.json")))
        assert replacement.poll() is None and other.poll() is None
        assert read(tmp_path / "again.json")["activations"] == read(tmp_path / "b.json")["activations"] == 0
    finally: stop(processes, gates)


def test_secondary_entry_never_creates_store_window_or_backend(app, tmp_path, monkeypatch):
    import MusicDesk as entry
    profile, output, gate = tmp_path / "profile", tmp_path / "primary.json", tmp_path / "stop"
    primary = launch(profile, output, gate)
    try:
        until(lambda: bool(read(output)))
        monkeypatch.setattr(entry, "create_application", lambda *_: app)
        for name in ("Store", "MusicWindow", "prepare_backend"):
            monkeypatch.setattr(entry, name, lambda *_: pytest.fail("secondary created runtime state"))
        monkeypatch.setattr(sys, "argv", ["MusicDesk.py", "--data-dir", str(profile)])
        assert entry.main() == 0
        until(lambda: read(output).get("activations") == 1)
    finally: stop([primary], [gate])
