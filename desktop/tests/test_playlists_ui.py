import hashlib
import time
import wave
from pathlib import Path

import pytest
from PySide6.QtCore import QEventLoop, QTimer, Qt, QPoint, QPointF, QMimeData, QUrl, QItemSelectionModel
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QMenu, QInputDialog, QFileDialog

from musicdesk.appearance import create_application
from musicdesk.audio_settings import AudioSettings
from musicdesk.core import Store
from musicdesk.playlists import Playlists, entry, read_m3u, write_m3u
from musicdesk.playlist_ui import TrackTable
from musicdesk.window import MusicWindow


def wait(ms=50):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()


def until(check):
    deadline = time.monotonic() + 12
    while not check():
        wait(); assert time.monotonic() < deadline


@pytest.fixture(scope="module")
def app(): return QApplication.instance() or create_application([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setattr(AudioSettings, "discover", lambda self: None)
    folder = tmp_path / "audio"; folder.mkdir()
    for index in range(4):
        with wave.open(str(folder / f"{index}.wav"), "wb") as out:
            out.setparams((1, 2, 44100, 0, "NONE", "not compressed")); out.writeframes(b"\0\0" * 4410)
    Store(tmp_path / "profile").set("library", str(folder))
    value = MusicWindow(Path(__file__).resolve().parents[1] / "vendor/backend", tmp_path / "profile")
    value.audio.setMuted(True); value.show(); until(lambda: len(value.tracks) == 4 and not value.scanning)
    yield value
    value.tray.exit(); wait(100)


def drop(target, mime, point=QPoint(20, 20)):
    enter = QDragEnterEvent(point, Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(target, enter); assert enter.isAccepted()
    event = QDropEvent(QPointF(point), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(target, event); assert event.isAccepted()


def test_sidebar_create_multi_song_drag_reorder_rename_and_remove_keep_files(window, monkeypatch):
    ui = window.custom_playlists
    class Names(QInputDialog):
        @staticmethod
        def getText(*args, **kwargs): return ("夜晚歌单" if args[1] == "新建歌单" else "慢慢听"), True
    monkeypatch.setattr("musicdesk.playlist_ui.QInputDialog", Names)
    class CreateMenu(QMenu):
        def exec(self, *args): next(action for action in self.actions() if action.text() == "新建歌单").trigger()
    monkeypatch.setattr("musicdesk.playlist_ui.QMenu", CreateMenu)
    ui.creation_menu(window.nav["songs"]); key = ui.data.items[0]["id"]
    assert window.current_page == key and key in window.nav
    hashes = {track.path: hashlib.sha256(Path(track.path).read_bytes()).hexdigest() for track in window.tracks}
    window.navigate("songs"); wait(400)
    table = window.library_scroll.findChild(TrackTable)
    selection = table.selectionModel()
    for row in (0, 2): selection.select(table.model().index(row, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    mime = table.track_mime(); drop(ui.buttons[key], mime)
    assert [value["path"] for value in ui.data.get(key)["entries"]] == [window.tracks[row].path for row in (0, 2)]
    window.navigate(key); wait(400)
    ui.move(key, [0], 2); wait(100)
    assert ui.data.get(key)["entries"][0]["path"] == window.tracks[2].path
    ui.rename(key); assert ui.data.get(key)["name"] == "慢慢听"
    # Context removal is deliberately different from library/file removal.
    def select(menu, *args): next(action for action in menu.actions() if action.text() == "从歌单移除").trigger()
    class RemoveMenu(QMenu):
        def exec(self, *args): select(self, *args)
    monkeypatch.setattr("musicdesk.playlist_ui.QMenu", RemoveMenu)
    table = window.library_scroll.findChild(TrackTable)
    ui.song_menu(key, table, QPoint(10, 10)); wait(100)
    assert len(ui.data.get(key)["entries"]) == 1
    assert len(window.tracks) == 4 and not window.removed_files
    assert Playlists(Store(window.store.directory)).get(key) == ui.data.get(key)
    ui.delete(key); assert key not in window.nav and window.current_page == "songs"
    assert all(Path(path).is_file() and hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest for path, digest in hashes.items())


def test_drop_local_files_into_empty_playlist_and_import_export_missing_refs(window, tmp_path):
    ui = window.custom_playlists; item = ui.data.create("测试"); ui.refresh_sidebar(); window.navigate(item["id"]); wait(400)
    outside = tmp_path / "outside.wav"
    outside.write_bytes(Path(window.tracks[0].path).read_bytes())
    mime = QMimeData(); mime.setUrls([QUrl.fromLocalFile(str(outside))])
    drop(window.library_scroll.findChild(TrackTable).viewport(), mime)
    until(lambda: not ui.busy and not window.scanning and len(window.tracks) == 5)
    assert item["entries"][0]["path"] == str(outside)
    missing = tmp_path / "missing.wav"
    values = [entry(window.tracks[0]), {"path": str(missing), "title": "以后找回", "duration": 10}, entry(window.tracks[0])]
    filename = tmp_path / "ordered.m3u8"; write_m3u(filename, "导入测试", values)
    ui.import_file(filename); until(lambda: not ui.busy and not window.scanning and len(ui.data.items) == 2)
    imported = ui.data.items[-1]; assert [e["path"] for e in imported["entries"]] == [e["path"] for e in values]
    table = window.library_scroll.findChild(TrackTable); assert table.item(1, 4).text() == "文件不可用"
    ui.play(imported["id"], 1); assert window.current_path == ""
    # A missing external reference is retained for the next library scan.
    missing.write_bytes(outside.read_bytes()); window.scan(); until(lambda: not window.scanning)
    assert all(track is not None for track in ui.resolved(imported["id"]))
    output = tmp_path / "again.m3u"; write_m3u(output, imported["name"], imported["entries"])
    assert [e["path"] for e in read_m3u(output)[1]] == [e["path"] for e in values]


def test_import_cue_playlist_preserves_selected_virtual_track(window, tmp_path):
    source = tmp_path / "disc.wav"; source.write_bytes(Path(window.tracks[0].path).read_bytes())
    cue = tmp_path / "disc.cue"
    cue.write_text('TITLE "Disc"\nFILE "disc.wav" WAVE\n TRACK 01 AUDIO\n TITLE "One"\n INDEX 01 00:00:00\n TRACK 02 AUDIO\n TITLE "Two"\n INDEX 01 00:00:04')
    file = tmp_path / "cue.m3u8"; write_m3u(file, "Cue", [{"path": str(cue) + "#amtrack=2", "title": "Two", "duration": 0}])
    ui = window.custom_playlists; ui.import_file(file); until(lambda: not ui.busy and not window.scanning)
    item = ui.data.items[0]
    assert len(item["entries"]) == 1 and ui.resolved(item["id"])[0].title == "Two"


def test_playlist_play_scope_follows_manual_order_and_shuffle_has_no_repeats(window, monkeypatch):
    ui = window.custom_playlists
    tracks = [window.tracks[index] for index in (2, 0, 3, 1)]
    item = ui.data.create("顺序", [entry(track) for track in tracks])
    def current(autoplay=True): window.current_path = window.playlist[window.play_index].path
    monkeypatch.setattr(window, "play_current", current)
    ui.play(item["id"])
    assert [track.path for track in window.playlist] == [track.path for track in tracks]
    window.skip(1); assert window.current_path == tracks[1].path
    window.shuffle.setChecked(True); ui.play(item["id"])
    played = [window.current_path]
    for _ in range(3): window.skip(1); played.append(window.current_path)
    assert len(set(played)) == 4


def test_internal_drop_multiple_rows_and_edge_scroll(window):
    ui = window.custom_playlists
    values = [entry(track) for track in window.tracks] * 25
    item = ui.data.create("长歌单", values); ui.refresh_sidebar(); window.navigate(item["id"]); wait(400)
    table = window.library_scroll.findChild(TrackTable)
    table.drag_rows = [0, 2]
    for row in table.drag_rows:
        table.selectionModel().select(table.model().index(row, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    mime = table.track_mime()
    edge = QPoint(60, table.viewport().height() - 5)
    enter = QDragEnterEvent(edge, Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(table.viewport(), enter)
    movement = QDragMoveEvent(edge, Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(table.viewport(), movement); wait(100)
    assert table.verticalScrollBar().value() > 0
    table.drop_scroll.stop(); table.verticalScrollBar().setValue(0)
    class InternalDrop(QDropEvent):
        def source(self): return table
    event = InternalDrop(QPointF(60, table.rowViewportPosition(3) + 50), Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    table.dropEvent(event); wait(100)
    assert event.isAccepted() and item["entries"][:4] == [values[i] for i in (1, 3, 0, 2)]
    assert len(item["entries"]) == 100
    table = window.library_scroll.findChild(TrackTable)
    assert table.selected_rows() == [2, 3]
    window.resize(1100, 720); window.show_lyrics(); wait(500)
    assert window.library_scroll.horizontalScrollBar().maximum() == 0


def test_import_and_export_dialog_commands(window, tmp_path, monkeypatch):
    file = tmp_path / "入口测试.m3u8"; output = tmp_path / "导出测试.m3u"
    write_m3u(file, "入口测试", [entry(window.tracks[2]), entry(window.tracks[0])])
    class Dialog(QFileDialog):
        @staticmethod
        def getOpenFileName(*args): return str(file), "M3U 歌单 (*.m3u *.m3u8)"
        @staticmethod
        def getSaveFileName(*args): return str(output), "M3U 歌单 (*.m3u)"
    monkeypatch.setattr("musicdesk.playlist_ui.QFileDialog", Dialog)
    ui = window.custom_playlists; ui.choose_import(); until(lambda: not ui.busy and not window.scanning)
    item = ui.data.items[0]; ui.choose_export(item["id"])
    assert [e["path"] for e in read_m3u(output)[1]] == [e["path"] for e in read_m3u(file)[1]]
