import pytest
import subprocess
import sys
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from test_playlists_ui import app, window, wait
from musicdesk.core import Store
from musicdesk.instance import SingleInstance
from musicdesk.library_tools import AlbumEditor
from musicdesk.window import MusicWindow


def test_close_asks_once_and_escape_preserves_playback(window, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    calls = []
    monkeypatch.setattr(window.media, "shutdown", lambda: calls.append(True))
    window.close_button.click(); wait(40)
    dialog = window.tray.close_dialog
    assert dialog.isVisible() and window.isVisible() and not calls
    assert not dialog.remember.isChecked() and window.close_action.currentData() == "ask"
    window.close(); window.tray.restore()
    assert window.tray.close_dialog is dialog
    dialog.remember.setChecked(True)
    QTest.keyClick(dialog, Qt.Key.Key_Escape); wait(40)
    assert window.tray.close_dialog is None and window.isVisible() and not calls
    assert Store(window.store.directory).get("close_action", "ask") == "ask"
    monkeypatch.undo()


def test_tray_choice_without_remembering_asks_again(window, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    window.showMaximized(); wait(60)
    window.close_button.click()
    window.tray.close_dialog.tray_button.click(); wait(40)
    assert not window.isVisible() and window.tray.icon.isVisible() and not window.closing
    assert Store(window.store.directory).get("close_action", "ask") == "ask"
    window.tray.restore(); wait(40)
    assert window.isVisible() and window.isMaximized()
    window.close_button.click()
    assert window.tray.close_dialog and window.tray.close_dialog.isVisible()


@pytest.mark.parametrize("action", ["tray", "exit"])
@pytest.mark.parametrize("remember", [False, True])
def test_choices_persist_only_when_checked_and_survive_restart(window, monkeypatch, action, remember):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    quit_calls = []
    monkeypatch.setattr(QApplication.instance(), "quit", lambda: quit_calls.append(True))
    window.close_button.click()
    dialog = window.tray.close_dialog; dialog.remember.setChecked(remember)
    (dialog.tray_button if action == "tray" else dialog.exit_button).click(); wait(40)
    assert Store(window.store.directory).get("close_action", "ask") == (action if remember else "ask")
    assert window.close_action.currentData() == (action if remember else "ask")
    if action == "tray":
        assert not window.isVisible() and not window.closing and not quit_calls
        window.tray.exit(); wait(40)
    else:
        assert window.closing and quit_calls and not window.tray.icon.isVisible()
    restored = MusicWindow(window.root, window.store.directory); restored.audio.setMuted(True); restored.show(); wait(80)
    try:
        restored.close_button.click(); wait(40)
        if not remember:
            assert restored.tray.close_dialog and restored.tray.close_dialog.isVisible() and not restored.closing
        elif action == "tray":
            assert not restored.isVisible() and not restored.closing and restored.tray.close_dialog is None
        else:
            assert restored.closing and restored.tray.close_dialog is None
    finally: restored.tray.exit(); wait(100)


def test_settings_can_reset_remembered_choice_and_tray_exit_bypasses_prompt(window, monkeypatch):
    quit_calls = []
    monkeypatch.setattr(QApplication.instance(), "quit", lambda: quit_calls.append(True))
    window.close_button.click()
    dialog = window.tray.close_dialog; dialog.remember.setChecked(True); dialog.tray_button.click(); wait(30)
    window.tray.restore()
    combo = window.close_action; combo.setCurrentIndex(combo.findData("ask")); combo.activated.emit(combo.currentIndex())
    assert Store(window.store.directory).get("close_action") == "ask"
    window.close_button.click(); assert window.tray.close_dialog.isVisible()
    next(action for action in window.tray.menu.actions() if action.text() == "退出").trigger(); wait(40)
    assert window.tray.close_dialog is None and window.closing and quit_calls


def test_exit_choice_waits_for_backend(window, monkeypatch):
    process = window.client.process; state = [process.ProcessState.Running]
    calls, quits = [], []
    monkeypatch.setattr(process, "state", lambda: state[0])
    monkeypatch.setattr(window.client, "shutdown", lambda: calls.append(True))
    monkeypatch.setattr(QApplication.instance(), "quit", lambda: quits.append(True))
    window.close_button.click(); window.tray.close_dialog.exit_button.click(); wait(40)
    assert window.closing and calls == [True] and not quits and window.tray.icon.isVisible()
    state[0] = process.ProcessState.NotRunning
    window.backend_event({"event": "disconnected"}); wait(40)
    assert quits == [True] and not window.tray.icon.isVisible()


def test_saving_tags_blocks_explicit_exit_without_stopping_audio(window, monkeypatch):
    editor = AlbumEditor(window, window.tracks[:1]); editor.saving = True
    shutdown = []
    monkeypatch.setattr(window.media, "shutdown", lambda: shutdown.append(True))
    try:
        window.close_button.click(); window.tray.close_dialog.exit_button.click(); wait(40)
        assert window.isVisible() and not window.closing and not window.tray.exiting and not shutdown
    finally:
        editor.saving = False; editor.reject(); editor.deleteLater(); monkeypatch.undo()


def test_second_process_restores_hidden_maximized_player_without_replacing_audio(window, app, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    monkeypatch.setattr(window.media, "play", lambda: None)
    window.play_tracks(window.tracks[:2]); wait(40)
    current, media, backend = window.current_path, window.media, window.client.process
    instance = SingleInstance(window.store.directory, app)
    assert instance.acquire()
    instance.activated.connect(window.tray.restore)
    window.showMaximized(); wait(50); window.tray.minimize()
    child = subprocess.Popen([sys.executable, "-c",
        "import sys; from PySide6.QtCore import QCoreApplication; from musicdesk.instance import SingleInstance; "
        "app=QCoreApplication([]); instance=SingleInstance(sys.argv[1]); "
        "primary=instance.acquire(); instance.close(); sys.exit(2 if primary else 0)", str(window.store.directory)])
    try:
        for _ in range(100):
            wait(30)
            if child.poll() is not None and window.isVisible(): break
        assert child.wait(timeout=3) == 0
        assert window.isVisible() and window.isMaximized()
        assert window.current_path == current and window.media is media and window.client.process is backend
        assert not window.closing and not window.tray.exiting
    finally:
        instance.close()
        if child.poll() is None: child.kill(); child.wait(timeout=3)
