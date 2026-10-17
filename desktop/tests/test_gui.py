import time
import statistics
from pathlib import Path
import pytest
from PySide6.QtCore import QEventLoop, QTimer, Qt, QPoint, QSize
from PySide6.QtWidgets import QApplication, QWidget, QPushButton, QLabel, QLineEdit, QComboBox, QPlainTextEdit
from PySide6.QtTest import QTest
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtGui import QImage, QFont, QRawFont, QPainter, QColor, QIcon
from musicdesk.window import MusicWindow
from musicdesk.core import read_config
from musicdesk.core import duration_text
from musicdesk.widgets import FeatureCard, RoundedTable
from musicdesk.appearance import create_application
from musicdesk.icons import icon


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or create_application([])


def wait(ms):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()


def test_normal_launch_schedules_backend_without_blocking_ui(app, tmp_path, monkeypatch):
    import sys
    import MusicDesk as entry
    from musicdesk.client import BackendClient
    commands, windows = [], []
    monkeypatch.setattr(BackendClient, "send", lambda self, command: commands.append(command))
    def window(*args):
        result = MusicWindow(*args); windows.append(result); return result
    monkeypatch.setattr(entry, "MusicWindow", window)
    monkeypatch.setattr(entry, "create_application", lambda *_: app)
    def run_events():
        assert windows[0].isVisible() and not commands
        wait(150)
        assert commands == [{"action": "start"}]
        windows[0].navigate("settings")
        assert windows[0].backend_dot.text() == "●  后端启动中"
        return 0
    monkeypatch.setattr(app, "exec", run_events)
    monkeypatch.setattr(sys, "argv", ["MusicDesk.py", "--backend-root", r"D:\AppleMusicDecrypt-Windows", "--data-dir", str(tmp_path)])
    try:
        assert entry.main() == 0
        windows[0].closing = True
        windows[0].start_backend()
        assert commands == [{"action": "start"}]
    finally:
        for value in windows: value.tray.exit()
        wait(100)


@pytest.fixture
def window(app, tmp_path):
    root = Path(r"D:\AppleMusicDecrypt-Windows")
    value = MusicWindow(root, tmp_path); value.audio.setMuted(True); value.show()
    deadline = time.monotonic() + 10
    while value.scanning or not value.tracks:
        wait(100)
        if time.monotonic() > deadline: break
    yield value
    value.tray.exit(); wait(100)


def test_real_library_metadata_navigation_and_favourites(window):
    assert len(window.tracks) >= 5
    eagle = next(track for track in window.tracks if track.title == "Hotel California")
    assert eagle.codec == "alac" and eagle.bits == 24 and eagle.rate == 192000
    for page in ("songs", "albums", "favourites", "queue", "settings", "search", "recent"):
        window.navigate(page); wait(30)
    window.toggle_favourite(eagle.path)
    window.navigate("favourites")
    assert window.filtered_tracks() == [eagle]
    window.search.setText("nonexistent track zzz"); wait(400)
    assert not window.filtered_tracks()


@pytest.mark.parametrize("page,card_type", [("home", FeatureCard), ("home", "album"), ("recent", "album"), ("albums", "album")])
def test_album_cards_open_main_page_without_nested_dialog(window, monkeypatch, page, card_type):
    from PySide6.QtWidgets import QDialog
    from musicdesk.widgets import AlbumCard
    def unexpected_dialog(*_):
        raise AssertionError("Album navigation must not open a dialog")
    monkeypatch.setattr(QDialog, "exec", unexpected_dialog)
    window.play_tracks(window.tracks[-1:]); wait(250)
    playing = window.current_path
    window.navigate(page); wait(400)
    card = window.library_scroll.findChildren(AlbumCard if card_type == "album" else FeatureCard)[0]
    title = card.title.toolTip() if card_type == "album" else card.toolTip().split("\n")[0]
    QTest.mouseClick(card, Qt.MouseButton.LeftButton)
    assert window.stack.transition.isVisible()
    wait(400)
    assert window.current_page in window.album_pages
    tracks = window.album_pages[window.current_page]
    assert tracks[0].album == title
    assert window.current_path == playing and window.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    assert not any(dialog.isVisible() for dialog in window.findChildren(QDialog))
    assert not any(b.text() == "查看专辑" for b in window.library_scroll.findChildren(QPushButton))
    table = window.library_scroll.findChild(RoundedTable)
    assert [table.item(i, 1).text() for i in range(table.rowCount())] == [t.title for t in tracks]
    if window.current_page in window.nav: assert window.nav[window.current_page].isChecked()
    next(b for b in window.library_scroll.findChildren(QPushButton) if b.text() == "播放").click()
    assert window.playlist == tracks and window.current_path == tracks[0].path
    window.navigate("home"); wait(400)
    assert window.current_page == "home" and not window.stack.transition.isVisible()


def test_album_outside_sidebar_survives_rescan_and_lyrics_reflow(window):
    key = next(key for key in window.album_pages if key not in window.sidebar_albums)
    window.open_album(window.album_pages[key]); wait(400)
    window.scan(); wait(400)
    assert not window.scanning and window.current_page == key
    window.show_lyrics(); wait(400)
    window.resize(1120, 740); wait(500)
    assert window.current_page == key and window.library_scroll.findChild(RoundedTable).rowCount() == len(window.album_pages[key])
    window.show_lyrics(); wait(400)
    assert window.current_page == key


def test_integrated_settings_and_download_destination(app, tmp_path):
    from musicdesk.runtime import prepare_backend
    root = prepare_backend(tmp_path)
    window = MusicWindow(root, tmp_path); window.show()
    try:
        window.navigate("settings"); wait(350)
        assert not hasattr(window, "root_field")
        assert any("内置 AppleMusicDecrypt" in item.text() for item in window.findChildren(QLabel))
        destination = tmp_path / "音乐 with spaces {personal}"
        window.store.set("library", str(destination))
        commands = []; window.client.send = commands.append
        window.enqueue(["https://music.apple.com/cn/song/635770202"], "alac")
        assert commands[0]["output_dir"] == str(destination)
        assert commands[0]["codec"] == "alac"
        window.backend_event({"event": "finished", "job_id": window.active_job, "state": "cancelled"})
        window.save_settings()
        assert read_config(root)["localInstance"]["enable"]
    finally:
        window.tray.exit(); wait(100)


def test_queue_only_dispatches_one_job_and_cancellation(window):
    commands = []; window.client.send = commands.append
    links = ["https://music.apple.com/cn/song/635770202", "https://music.apple.com/cn/song/123456789"]
    window.enqueue(links, "alac")
    assert len(commands) == 1 and commands[0]["action"] == "download"
    active = window.active_job
    window.job_action(active); assert commands[-1] == {"action": "cancel"}
    window.backend_event({"event": "finished", "job_id": active, "state": "cancelled"})
    wait(450)
    assert commands[-1]["url"] == links[1]
    window.backend_event({"event": "finished", "job_id": window.active_job, "state": "DONE", "completed": 1, "total": 1})
    assert window.jobs[0]["state"] == "cancelled" and window.jobs[1]["state"] == "DONE"


def test_alac_local_playback_and_seek(window):
    track = next(track for track in window.tracks if track.title == "Hotel California")
    errors = []; window.media.errorOccurred.connect(lambda *_: errors.append(window.media.errorString()))
    window.play_tracks([track])
    wait(3500)
    assert not errors
    assert window.media.duration() > 300000
    assert window.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    assert window.media.position() > 500
    window.media.setPosition(60000); wait(600)
    assert window.media.position() >= 60000
    window.toggle_play(); wait(100)
    assert window.media.playbackState() == QMediaPlayer.PlaybackState.PausedState


def test_last_track_restores_without_playing_and_missing_file_is_safe(window):
    from musicdesk.core import Store
    target = window.tracks[1]
    window.play_tracks(window.tracks, 1); wait(200); window.media.pause()
    directory, root = window.store.directory, window.root
    window.tray.exit(); wait(100)
    reopened = MusicWindow(root, directory); reopened.audio.setMuted(True)
    states = []; reopened.media.playbackStateChanged.connect(states.append); reopened.show()
    try:
        deadline = time.monotonic() + 8
        while not reopened.current_path and time.monotonic() < deadline: wait(50)
        assert reopened.current_path == target.path
        assert reopened.play_title.text() == target.title and target.artist in reopened.play_artist.text()
        assert Path(reopened.media.source().toLocalFile()) == Path(target.path)
        assert reopened.media.position() == 0 and QMediaPlayer.PlaybackState.PlayingState not in states
        reopened.toggle_play(); wait(300)
        assert reopened.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    finally:
        reopened.tray.exit(); wait(100)
    # The last song can still be restored after choosing another library folder.
    Store(directory).set("library", str(directory / "another library"))
    outside = MusicWindow(root, directory); outside.audio.setMuted(True); outside.show()
    try:
        deadline = time.monotonic() + 8
        while not outside.current_path and time.monotonic() < deadline: wait(50)
        assert not outside.tracks and outside.current_path == target.path
        assert outside.media.playbackState() != QMediaPlayer.PlaybackState.PlayingState
    finally:
        outside.tray.exit(); wait(100)
    Store(directory).set("library", str(root / "downloads"))
    Store(directory).set("last_track", str(directory / "removed.m4a"))
    Store(directory).set("playback_queue", None)  # Legacy profile has no saved queue to restore.
    missing = MusicWindow(root, directory); missing.show()
    try:
        deadline = time.monotonic() + 8
        while not missing.tracks and time.monotonic() < deadline: wait(50)
        assert not missing.current_path and missing.media.source().isEmpty()
    finally:
        missing.tray.exit(); wait(100)


def test_import_dialog_drag_and_reopen_keep_external_files(app, tmp_path, monkeypatch):
    import wave
    from PySide6.QtWidgets import QFileDialog
    from PySide6.QtCore import QMimeData, QUrl, QPointF
    from PySide6.QtGui import QDropEvent
    from musicdesk.core import Store
    source = tmp_path / "外部 My Song.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setparams((1, 2, 8000, 0, "NONE", "not compressed")); audio.writeframes(b"\0\0" * 16000)
    before = source.read_bytes()
    invalid = tmp_path / "invalid.mp3"; invalid.write_bytes(b"not audio")
    directory = tmp_path / "profile"; Store(directory).set("library", str(tmp_path / "empty library"))
    root = Path(r"D:\AppleMusicDecrypt-Windows")
    value = MusicWindow(root, directory); value.audio.setMuted(True); value.show()
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *_: ([str(source), str(invalid)], ""))
    try:
        value.choose_audio_files()
        deadline = time.monotonic() + 8
        while (value.importing or value.scanning or not value.tracks) and time.monotonic() < deadline: wait(50)
        assert len(value.tracks) == 1 and value.tracks[0].title == "外部 My Song"
        assert value.store.get("imported_files") == [str(source)]
        assert value.client.process.state() == value.client.process.ProcessState.NotRunning
        assert not (tmp_path / "empty library").exists() and source.read_bytes() == before
        mime = QMimeData(); mime.setUrls([QUrl.fromLocalFile(str(source))])
        event = QDropEvent(QPointF(200, 200), Qt.DropAction.CopyAction | Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier)
        value.dropEvent(event)
        deadline = time.monotonic() + 8
        while value.importing and time.monotonic() < deadline: wait(50)
        assert event.isAccepted() and len(value.store.get("imported_files")) == 1
        assert event.dropAction() == Qt.DropAction.CopyAction
        value.play_tracks(value.tracks); wait(100)
    finally:
        value.tray.exit(); wait(100)
    reopened = MusicWindow(root, directory); reopened.audio.setMuted(True); reopened.show()
    try:
        deadline = time.monotonic() + 8
        while not reopened.current_path and time.monotonic() < deadline: wait(50)
        assert len(reopened.tracks) == 1 and reopened.current_path == str(source)
        assert reopened.media.playbackState() != QMediaPlayer.PlaybackState.PlayingState
        assert source.read_bytes() == before
    finally:
        reopened.tray.exit(); wait(100)


def test_folder_import_recursive_deduplicated_and_persisted(app, tmp_path, monkeypatch):
    import threading
    import wave
    from PySide6.QtWidgets import QFileDialog
    from musicdesk.core import Store, path_key
    import musicdesk.window as window_module
    folder = tmp_path / "本地音乐 My Albums"
    nested = folder / "艺人" / "专辑"; nested.mkdir(parents=True)
    paths = [folder / "第一首.wav", nested / "第二首.WAV"]
    for path in paths:
        with wave.open(str(path), "wb") as audio:
            audio.setparams((1, 2, 8000, 0, "NONE", "not compressed")); audio.writeframes(b"\0\0" * 8000)
    (folder / "损坏.mp3").write_bytes(b"not audio")
    (nested / "歌词.lrc").write_text("[00:00.00]歌词", encoding="utf-8")
    original = {path: path.read_bytes() for path in folder.rglob("*") if path.is_file()}
    directory = tmp_path / "profile"
    Store(directory).update({"library": str(tmp_path / "empty library"), "imported_files": [str(paths[0])]})
    threads = []; scan = window_module.scan_library
    def observed_scan(*args):
        if args[0] == str(folder): threads.append(threading.get_ident())
        return scan(*args)
    monkeypatch.setattr(window_module, "scan_library", observed_scan)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_: str(folder))
    value = MusicWindow(Path(r"D:\AppleMusicDecrypt-Windows"), directory); value.show()
    def settled():
        deadline = time.monotonic() + 8
        wait(50)
        while value.importing or value.scanning:
            assert time.monotonic() < deadline
            wait(50)
    try:
        settled()
        # Exercise the actual button in the modal Add Music dialog.
        def choose():
            dialog = QApplication.activeModalWidget()
            next(b for b in dialog.findChildren(QPushButton) if b.text().strip() == "导入文件夹").click()
        QTimer.singleShot(50, choose); value.add_dialog(); settled()
        assert {track.path for track in value.tracks} == set(map(str, paths))
        assert "已导入 1 首" in value.notice.text() and "1 首已在资料库" in value.notice.text()
        assert "跳过 1 个" in value.notice.text()
        value.choose_audio_folder(); settled()
        assert len(value.store.get("imported_files")) == 2 and "2 首已在资料库" in value.notice.text()
        value.remove_track(next(t for t in value.tracks if t.path == str(paths[1]))); settled()
        value.choose_audio_folder(); settled()
        assert path_key(paths[1]) not in value.store.get("removed_files")
        assert len(value.tracks) == len(value.store.get("imported_files")) == 2
        assert threads and all(thread != threading.get_ident() for thread in threads)
        assert value.client.process.state() == value.client.process.ProcessState.NotRunning
        empty = tmp_path / "无音乐"; empty.mkdir(); (empty / "note.txt").write_text("text")
        monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_: str(empty))
        value.choose_audio_folder(); settled()
        assert value.notice.text() == "未找到支持的音频文件"
        monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_: "")
        value.choose_audio_folder()
        assert not value.importing and len(value.store.get("imported_files")) == 2
    finally:
        value.tray.exit(); wait(100)
    value = MusicWindow(Path(r"D:\AppleMusicDecrypt-Windows"), directory); value.show()
    try:
        settled()
        assert {track.path for track in value.tracks} == set(map(str, paths))
        assert all(path.read_bytes() == data for path, data in original.items())
        assert not (tmp_path / "empty library").exists()
    finally:
        value.tray.exit(); wait(100)


@pytest.fixture
def removal_window(app, tmp_path):
    import wave
    from musicdesk.core import Store
    folder = tmp_path / "library"; folder.mkdir()
    paths = [folder / "alpha.wav", folder / "beta.wav", tmp_path / "external.wav"]
    for path in paths:
        with wave.open(str(path), "wb") as audio:
            audio.setparams((1, 2, 8000, 0, "NONE", "not compressed")); audio.writeframes(b"\0\0" * 8000 * 30)
        path.with_suffix(".lrc").write_text("[00:00.00]Test lyrics", encoding="utf-8")
    store = Store(tmp_path / "profile")
    store.set("library", str(folder)); store.set("imported_files", [str(paths[-1])])
    value = MusicWindow(Path(r"D:\AppleMusicDecrypt-Windows"), store.directory)
    value.audio.setMuted(True); value.show()
    deadline = time.monotonic() + 5
    while value.scanning or len(value.tracks) != 3:
        wait(50)
        assert time.monotonic() < deadline
    yield value
    value.tray.exit(); wait(100)


def test_context_remove_keeps_file_hidden_on_scan_and_restart(removal_window):
    from musicdesk.core import path_key
    value = removal_window; target = next(t for t in value.tracks if t.title == "alpha")
    original = Path(target.path).read_bytes()
    value.play_tracks([target]); wait(100); value.toggle_favourite(target.path)
    value.navigate("songs"); wait(350)
    table = value.library_scroll.findChild(RoundedTable)
    entries = {}
    def choose():
        menu = QApplication.activePopupWidget()
        actions = {action.text(): action for action in menu.actions()}
        entries.update(actions)
        menu.close()
        if "从列表中删除" in actions: actions["从列表中删除"].trigger()
    row = next(row for row in range(table.rowCount()) if table.item(row, 1).text() == target.title)
    QTimer.singleShot(20, choose)
    table.customContextMenuRequested.emit(table.visualItemRect(table.item(row, 1)).center())
    assert "从列表中删除" in entries and "删除本地文件" in entries
    wait(300)
    assert Path(target.path).read_bytes() == original and Path(target.path).with_suffix(".lrc").is_file()
    assert target.path not in [track.path for track in value.tracks]
    assert path_key(target.path) in value.store.get("removed_files")
    assert target.path not in value.favourites and target.path not in value.recently_played
    assert not value.current_path and value.media.source().isEmpty() and not value.playlist
    assert value.play_title.text() == "AM Dowloader" and not value.lyrics.lines
    value.scan(); wait(300)
    directory, root = value.store.directory, value.root; value.tray.exit(); wait(100)
    reopened = MusicWindow(root, directory); reopened.audio.setMuted(True); reopened.show()
    try:
        wait(400)
        assert target.path not in [track.path for track in reopened.tracks]
        reopened.import_audio_files([target.path]); wait(500)
        assert target.path in [track.path for track in reopened.tracks]
        assert path_key(target.path) not in reopened.store.get("removed_files")
        assert Path(target.path).read_bytes() == original
    finally:
        reopened.tray.exit(); wait(100)


def test_remove_other_song_keeps_playback_and_empty_album_navigates(removal_window):
    value = removal_window
    target = next(t for t in value.tracks if t.title == "external")
    keep = next(t for t in value.tracks if t.title == "beta")
    value.play_tracks([target, keep], 1); wait(200)
    album_key = next(key for key, tracks in value.sidebar_albums.items() if tracks == [target])
    value.navigate(album_key); wait(350)
    assert value.remove_track(target)
    wait(300)
    assert value.current_page == "songs"
    assert value.current_path == keep.path and value.playlist == [keep] and value.play_index == 0
    assert value.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    assert target.path not in value.store.get("imported_files") and Path(target.path).is_file()


def test_open_album_keeps_identity_when_first_song_removed(removal_window):
    value = removal_window
    tracks = next(tracks for tracks in value.albums.values() if len(tracks) == 2)
    original = {t.path: Path(t.path).read_bytes() for t in tracks}
    value.open_album(tracks); wait(400); key = value.current_page
    assert value.remove_track(tracks[0]); wait(400)
    assert value.current_page == key and len(value.album_pages[key]) == 1
    remaining = value.album_pages[key][0]
    assert value.library_scroll.findChild(RoundedTable).item(0, 1).text() == remaining.title
    assert value.remove_track(remaining); wait(400)
    assert value.current_page == "songs" and key not in value.album_pages
    assert all(Path(path).read_bytes() == data for path, data in original.items())


@pytest.mark.parametrize("playing", (False, True))
def test_failed_file_removal_preserves_library_and_player(removal_window, monkeypatch, playing):
    import musicdesk.window as module
    value = removal_window; track = value.tracks[0]
    value.play_tracks([track]); wait(200); value.media.pause(); value.media.setPosition(3000)
    if playing: value.media.play()
    def blocked(path): raise OSError("Test file is locked")
    monkeypatch.setattr(module, "trash_audio", blocked)
    assert not value.remove_track(track, delete_file=True)
    wait(150)
    assert track in value.tracks and Path(track.path).is_file() and value.current_path == track.path
    assert 3000 <= value.media.position() < 4000
    assert value.media.playbackState() == (QMediaPlayer.PlaybackState.PlayingState if playing else QMediaPlayer.PlaybackState.PausedState)
    assert "Test file is locked" in value.notice.toolTip()
    assert not value.store.get("removed_files", [])


def test_loaded_settings_do_not_silently_reduce_quality(window):
    config = read_config(window.root)
    assert window.rate_combo.currentData() == int(config["download"]["maxSampleRate"])
    assert window.bits_combo.currentData() == int(config["download"]["maxBitDepth"])


def test_song_finished_does_not_finish_parent_album_early(window):
    window.client.send = lambda command: None
    window.enqueue(["https://music.apple.com/cn/album/635770200"], "alac")
    window.backend_event({"event": "stage", "job_id": window.active_job, "stage": "DONE", "completed": 0, "total": 9})
    assert window.jobs[-1]["state"] != "DONE"
    window.clear_completed()
    assert len(window.jobs) == 1


def test_relocated_player_controls_work_with_mouse(window):
    QTest.mouseClick(window.play_button, Qt.MouseButton.LeftButton); wait(800)
    assert window.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    first = window.current_path
    assert window.like_button.icon().name() == "player_star"
    QTest.mouseClick(window.like_button, Qt.MouseButton.LeftButton)
    assert first in window.favourites
    assert window.like_button.toolTip() == "取消喜爱"
    QTest.mouseClick(window.like_button, Qt.MouseButton.LeftButton)
    assert first not in window.favourites and window.like_button.toolTip() == "加入喜爱"
    next_button = next(button for button in window.findChildren(QPushButton) if button.toolTip() == "下一首")
    QTest.mouseClick(next_button, Qt.MouseButton.LeftButton); wait(500)
    assert window.current_path != first
    assert window.sidebar.source == window.playlist[window.play_index].cover
    assert not window.now_playing.backdrop.isNull()
    QTest.mouseClick(window.repeat, Qt.MouseButton.LeftButton)
    assert window.repeat.isChecked()
    QTest.mouseClick(window.play_button, Qt.MouseButton.LeftButton); wait(100)
    assert window.media.playbackState() == QMediaPlayer.PlaybackState.PausedState


def test_player_hover_seek_volume_popup_and_long_titles(window):
    window.play_tracks(window.tracks[:1]); wait(800); window.media.pause()
    window.media.setPosition(10000); wait(80)
    area = window.now_playing.geometry()
    QTest.mouseMove(window.windowHandle(), QPoint(40, 200)); wait(30)
    assert not window.elapsed.isVisible() and not window.remaining.isVisible()
    QTest.mouseMove(window.windowHandle(), window.play_cover.mapTo(window, QPoint(20, 20))); wait(30)
    assert window.elapsed.isVisible() and window.remaining.isVisible()
    assert window.elapsed.text() == "0:10"
    assert window.remaining.text() == "-" + duration_text((window.media.duration() - 10000) / 1000)
    assert window.now_playing.geometry() == area
    assert window.seek.mapTo(window.now_playing, QPoint(0, 0)).x() == window.play_cover.width()
    target = window.seek.mapTo(window, QPoint(window.seek.width() // 2, 4))
    QTest.mouseClick(window.windowHandle(), Qt.MouseButton.LeftButton, pos=target); wait(100)
    assert abs(window.media.position() - window.media.duration() / 2) < 600
    volume_point = window.volume_button.mapTo(window, window.volume_button.rect().center())
    QTest.mouseMove(window.windowHandle(), volume_point)
    QTest.mouseClick(window.windowHandle(), Qt.MouseButton.LeftButton, pos=volume_point); wait(60)
    assert window.volume_popup.isVisible() and QApplication.activePopupWidget() == window.volume_popup
    QTest.keyClick(window.volume, Qt.Key.Key_Home); assert window.audio.volume() == 0
    QTest.keyClick(window.volume, Qt.Key.Key_End); assert window.audio.volume() == 1
    position = window.volume.mapTo(window.volume_popup, QPoint(window.volume.width() // 3, window.volume.height() // 2))
    QTest.mouseClick(window.volume_popup.windowHandle(), Qt.MouseButton.LeftButton, pos=position)
    assert .2 < window.audio.volume() < .4
    QTest.keyClick(window.volume, Qt.Key.Key_Escape); wait(30); assert not window.volume_popup.isVisible()
    QTest.mouseMove(window.windowHandle(), QPoint(40, 200)); wait(30)
    assert not window.elapsed.isVisible() and not window.remaining.isVisible()
    def select_favourite():
        menu = QApplication.activePopupWidget()
        assert menu is not None and menu.actions()[0].text() == "加入喜爱"
        menu.actions()[0].trigger(); menu.close()
    QTimer.singleShot(60, select_favourite); window.more_button.click()
    assert window.current_path in window.favourites
    full_title = "很长的歌曲标题 Long Track Name " * 12
    window.play_title.setText(full_title); window.play_artist.setText(full_title)
    window.resize(1100, 720); wait(120)
    assert window.play_title.text().endswith("…") and window.play_title.full_text == full_title
    assert window.play_title.fontMetrics().horizontalAdvance(window.play_title.text()) <= window.play_title.contentsRect().width()
    assert window.play_artist.fontMetrics().horizontalAdvance(window.play_artist.text()) <= window.play_artist.contentsRect().width()
    before = window.play_title.width(); window.resize(1800, 1000); wait(120)
    assert window.play_title.width() > before
    assert window.play_title.fontMetrics().horizontalAdvance(window.play_title.text()) <= window.play_title.contentsRect().width()


def test_vector_icons_render_at_fractional_dpi_and_retain_states(app):
    names = ("app", "note", "songs", "home", "library", "recent", "artist", "album", "playlist", "favourites", "star", "star_fill", "shuffle", "prev", "play", "pause", "next", "repeat", "volume", "lyrics", "queue", "search", "plus", "back", "forward", "download", "refresh", "settings", "folder", "close", "grid")
    names += tuple("player_" + name for name in ("shuffle", "prev", "play", "pause", "next", "repeat", "volume", "volume_low", "volume_medium", "volume_high", "lyrics", "queue", "star", "more", "lossless"))
    for dpr in (1, 1.25, 1.5, 1.75, 2, 2.5, 3):
        for name in names:
            glyph = icon(name, "#ffffff")
            pixmap = glyph.pixmap(QSize(24, 24), dpr)
            assert pixmap.width() == round(24 * dpr) and pixmap.devicePixelRatio() == dpr
            image = pixmap.toImage()
            alphas = [image.pixelColor(x, y).alpha() for y in range(image.height()) for x in range(image.width())]
            assert max(alphas) > 150 and any(0 < a < 255 for a in alphas), name
            assert all(image.pixelColor(x, y).alpha() == 0 for x, y in ((0, 0), (0, image.height() - 1), (image.width() - 1, 0), (image.width() - 1, image.height() - 1))), name
    glyph = icon("repeat", "#ffffff")
    disabled = glyph.pixmap(QSize(24, 24), 2, QIcon.Mode.Disabled).toImage()
    assert max(disabled.pixelColor(x, y).alpha() for x in range(48) for y in range(48)) < 100
    checked = glyph.pixmap(QSize(24, 24), 2, QIcon.Mode.Normal, QIcon.State.On).toImage()
    assert any(checked.pixelColor(x, y).name() == "#fa4164" for x in range(48) for y in range(48))


def test_volume_flyout_pixels_live_value_and_hover_animation(window):
    window.volume.setValue(50); window.show_volume(); wait(50)
    popup, slider = window.volume_popup, window.volume
    image = popup.grab().toImage(); dpr = image.devicePixelRatio()
    for x, y in ((0, 0), (image.width() - 1, 0), (0, image.height() - 1), (image.width() - 1, image.height() - 1)):
        assert image.pixelColor(x, y).alpha() == 0
    assert image.pixelColor(round(image.width() / 2), round(6 * dpr)).name() == window.player_bar.base
    assert abs(popup.geometry().center().y() - window.volume_button.mapToGlobal(window.volume_button.rect().center()).y()) <= 1
    pixels = slider.grab().toImage(); scale = pixels.devicePixelRatio()
    assert pixels.pixelColor(round((slider.contentsRect().left() + 6) * scale), round(slider.height() * scale / 2)).name() == "#fa3558"
    assert pixels.pixelColor(round((slider.contentsRect().right() - 6) * scale), round(slider.height() * scale / 2)).name() == "#a0a0a3"
    point = slider.mapTo(popup, slider.thumb_center().toPoint())
    QTest.mouseMove(popup.windowHandle(), point); wait(40)
    assert 0 < slider.highlight < 1
    wait(200); assert slider.highlight == 1 and slider.animation.state() == slider.animation.State.Stopped
    assert slider.value_tip.isVisible() and slider.value_tip.text() == "50%"
    assert QApplication.activePopupWidget() == popup
    initial_x = slider.value_tip.x()
    QTest.mousePress(popup.windowHandle(), Qt.MouseButton.LeftButton, pos=point); wait(220)
    assert slider.highlight < -.5 and slider.isSliderDown()
    target = slider.mapTo(popup, QPoint(slider.contentsRect().right() - 4, slider.height() // 2))
    QTest.mouseMove(popup.windowHandle(), target); wait(30)
    assert slider.value() > 90 and slider.value_tip.text() == f"{slider.value()}%"
    assert slider.value_tip.x() > initial_x and window.volume_button.icon().name() == "player_volume_high"
    outside = QPoint(popup.width() + 20, popup.height() // 2)
    QTest.mouseMove(popup.windowHandle(), outside); wait(500)
    assert popup.isVisible() and slider.isSliderDown()
    QTest.mouseRelease(popup.windowHandle(), Qt.MouseButton.LeftButton, pos=outside); wait(550)
    assert not popup.isVisible() and not slider.value_tip.isVisible()
    window.volume.setValue(0); assert window.volume_button.icon().name() == "player_volume"
    window.volume.setValue(25); assert window.volume_button.icon().name() == "player_volume_low"
    window.show_volume(); wait(40)
    QTest.mouseMove(popup.windowHandle(), slider.mapTo(popup, slider.thumb_center().toPoint())); wait(220)
    assert slider.highlight == 1 and slider.value_tip.text() == "25%"
    popup.hide(); assert not slider.value_tip.isVisible()


def test_sidebar_navigation_transition_and_rapid_clicks(window):
    assert {"recent", "artists", "albums", "songs"}.issubset(window.nav)
    assert "search" not in window.nav
    assert any(item.text() == "资料库" for item in window.sidebar.findChildren(QLabel))
    assert all("新发现" not in item.text() for item in window.sidebar.findChildren(QPushButton))
    player_geometry = window.player_bar.geometry()
    window.play_tracks(window.tracks[:1]); wait(500)
    for page in ("recent", "artists", "albums", "songs", "settings", "queue", "favourites", "home"):
        QTest.mouseClick(window.nav[page], Qt.MouseButton.LeftButton)
        assert window.stack.transition.isVisible()
        wait(45)
    album_page = next(iter(window.sidebar_albums))
    QTest.mouseClick(window.nav[album_page], Qt.MouseButton.LeftButton)
    wait(380)
    assert window.current_page == album_page and window.nav[album_page].isChecked()
    assert not window.stack.transition.isVisible()
    assert window.stack.transition.before.isNull() and window.stack.transition.after.isNull()
    assert window.stack.currentWidget() == window.library_scroll
    assert any(item.text() == window.sidebar_albums[album_page][0].album for item in window.library_scroll.findChildren(QLabel))
    assert window.player_bar.geometry() == player_geometry
    assert window.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    QTest.mouseClick(window.nav["settings"], Qt.MouseButton.LeftButton); wait(40)
    window.resize(1100, 720); wait(100)
    assert window.stack.transition.isVisible() and window.stack.transition.mode == "reflow"
    wait(400)
    assert not window.stack.transition.isVisible()
    assert window.root_field.isVisible()
    commands = []; window.client.send = commands.append
    window.search.setText("Eagles"); window.search.actions()[0].trigger()
    assert window.current_page == "search" and commands[-1]["term"] == "Eagles"


def test_transition_keeps_up_with_display_and_releases_gpu_work(window):
    window.showMaximized(); wait(350)
    if not window.stack.transition.isValid(): pytest.skip("OpenGL display required")
    frames = []
    transition = window.stack.transition
    transition.frameSwapped.connect(lambda: frames.append(time.perf_counter()) if transition.clock.isValid() else None)
    window.navigate("settings"); wait(370)
    intervals = [(b - a) * 1000 for a, b in zip(frames, frames[1:])]
    refresh = window.screen().refreshRate() or 60
    assert len(frames) >= max(8, int(refresh * .30 * .60))
    assert statistics.median(intervals) < max(12, 2000 / refresh)
    assert not transition.clock.isValid() and not transition.isVisible()
    completed = len(frames); wait(120)
    assert len(frames) == completed


def test_interrupted_transition_preserves_the_visible_gpu_frame(window):
    from PIL import Image, ImageChops
    from PySide6.QtGui import QPixmap
    window.navigate("settings")
    transition = window.stack.transition
    if not transition.isValid(): pytest.skip("OpenGL display required")
    transition.clock.invalidate(); transition.progress = .5; transition.repaint()
    expected = transition.grabFramebuffer().convertToFormat(QImage.Format.Format_RGBA8888)
    captured = window.stack.capture_page()
    assert captured.devicePixelRatioF() == window.devicePixelRatioF()
    assert not transition.isVisible()
    # The interruption cache now contains foreground only. Recompose it over
    # the stationary background and compare with the previously visible frame.
    transition.start(captured, QPixmap(), mode="reflow"); transition.clock.invalidate()
    actual = transition.grabFramebuffer().convertToFormat(QImage.Format.Format_RGBA8888)
    images = [Image.frombytes("RGBA", (image.width(), image.height()), bytes(image.constBits())) for image in (actual, expected)]
    error = ImageChops.difference(*images)
    assert max(high for _, high in error.getextrema()) <= 3
    transition.clear()


def test_search_results_use_page_animation_and_ignore_stale_responses(window):
    commands = []; window.client.send = commands.append
    window.navigate("songs"); wait(350)
    player_geometry = window.player_bar.geometry()
    window.search.setText("Eagles"); wait(310)
    assert window.stack.transition.isVisible()
    assert len(window.filtered_tracks()) == 1
    window.search.clear(); QTest.keyClick(window.search, Qt.Key.Key_Return)
    assert window.stack.transition.isVisible()
    wait(350); assert not window.stack.transition.isVisible()
    assert len(window.filtered_tracks()) >= 5
    window.open_catalog_search(); window.search.setText("first")
    QTest.keyClick(window.search, Qt.Key.Key_Return); serial = window.search_serial
    assert commands[-1]["term"] == "first" and window.stack.transition.isVisible()
    wait(350); assert window.search_serial == serial  # Return consumes the pending debounce.
    window.search.setText("second"); QTest.keyClick(window.search, Qt.Key.Key_Return)
    window.backend_event({"event": "catalog", "serial": serial, "results": [{"trackName": "stale"}]})
    assert not window.search_cards
    window.backend_event({"event": "catalog", "serial": window.search_serial, "results": [{"trackName": "current"}]})
    assert len(window.search_cards) == 1 and window.stack.transition.isVisible()
    window.navigate("songs"); wait(350)
    window.backend_event({"event": "catalog", "serial": window.search_serial, "results": []})
    assert window.current_page == "songs" and not window.stack.transition.isVisible()
    assert window.player_bar.geometry() == player_geometry


def test_lyrics_drawer_nonmodal_reversible_and_tracks_current_song(window, tmp_path):
    from dataclasses import replace
    from PySide6.QtWidgets import QDialog
    sample = tmp_path / "lyrics.m4a"
    sample.with_suffix(".lrc").write_text("[00:00.00]First line\n[00:01.00]Second line\n[00:02.00]Third line", encoding="utf-8")
    track = replace(window.tracks[0], path=str(sample))
    # Read isolated lyric fixtures without changing the user's files or playing an invalid source.
    window.media.setSource = lambda *_: None; window.media.play = lambda: None
    window.play_tracks([track]); window.navigate("songs"); wait(350)
    original = window.stack.width(); player_geometry = window.player_bar.geometry()
    QTest.mouseClick(window.lyric_button, Qt.MouseButton.LeftButton)
    assert window.body.opened and window.lyrics.isVisible() and window.body.transition.isVisible()
    assert window.lyric_button.isChecked() and window.stack.width() < original
    assert not any(dialog.isVisible() for dialog in window.findChildren(QDialog))
    wait(70); assert 0 < window.body.transition.visible_width() < window.lyrics.width()
    QTest.mouseClick(window.lyric_button, Qt.MouseButton.LeftButton); wait(50)
    QTest.mouseClick(window.lyric_button, Qt.MouseButton.LeftButton); wait(360)
    assert window.body.opened and window.lyrics.isVisible() and not window.body.transition.isVisible()
    assert window.body.transition.panel.isNull()
    window.position_changed(1200); assert window.lyrics.active == 1
    window.position_changed(100); assert window.lyrics.active == 0
    window.navigate("albums"); wait(350)
    assert window.lyrics.isVisible() and window.player_bar.geometry() == player_geometry
    window.resize(1100, 720); wait(250)
    origin = window.lyrics.mapTo(window.body, QPoint())
    assert origin.x() + window.lyrics.width() <= window.body.width()
    assert window.stack.geometry().right() < origin.x()
    window.play_tracks([replace(track, path=str(tmp_path / "no-lyrics.m4a"))])
    assert not window.lyrics.lines and any(item.text() == "这首歌暂无歌词" for item in window.lyrics.findChildren(QLabel))
    QTest.mouseClick(window.lyric_button, Qt.MouseButton.LeftButton); wait(350)
    assert not window.body.opened and not window.lyrics.isVisible() and not window.lyric_button.isChecked()
    assert window.stack.width() == window.body.width()


def test_click_lyrics_seeks_and_preserves_playback(window, tmp_path):
    import wave
    from musicdesk.core import scan_library
    sample = tmp_path / "点击歌词.wav"
    with wave.open(str(sample), "wb") as audio:
        audio.setparams((1, 2, 8000, 0, "NONE", "not compressed")); audio.writeframes(b"\0\0" * 8000 * 90)
    source = sample.with_suffix(".lrc")
    source.write_text("[offset:+250]\n" + "\n".join(f"[00:{i * 2:02}.00]第 {i + 1} 句" for i in range(25)) + "\n[00:04.00]同一句翻译", encoding="utf-8")
    tracks, _ = scan_library(None, tmp_path / "covers", [sample])
    window.play_tracks(tracks)
    deadline = time.monotonic() + 5
    while not window.media.isSeekable() and time.monotonic() < deadline: wait(50)
    assert window.media.isSeekable()
    window.media.pause(); window.media.setPosition(0)
    window.lyric_button.click(); wait(400)
    panel = window.lyrics
    assert panel.lines[2].text() == "第 3 句\n同一句翻译"
    assert panel.lines[2].cursor().shape() == Qt.CursorShape.PointingHandCursor
    QTest.mouseClick(panel.lines[2], Qt.MouseButton.LeftButton); wait(60)
    assert window.media.position() == 4250 and panel.active == 2
    assert window.seek.value() == 4250 and window.elapsed.text() == "0:04"
    assert window.media.playbackState() == QMediaPlayer.PlaybackState.PausedState
    QTest.mouseClick(panel.lines[0], Qt.MouseButton.RightButton)
    QTest.mousePress(panel.lines[0], Qt.MouseButton.LeftButton)
    QTest.mouseRelease(panel.lines[0], Qt.MouseButton.LeftButton, pos=QPoint(-2, -2))
    assert window.media.position() == 4250
    window.media.play(); wait(60)
    QTest.mouseClick(panel.lines[4], Qt.MouseButton.LeftButton); wait(60)
    assert 8250 <= window.media.position() < 9000 and panel.active == 4
    assert window.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    window.media.pause(); wait(400)
    # Clicking the current line again returns to its start, including after manual scrolling.
    bar = panel.scroll.verticalScrollBar(); bar.setValue(0)
    QTest.mouseClick(panel.lines[4], Qt.MouseButton.LeftButton); wait(400)
    assert window.media.position() == 8250
    assert bar.value() == max(0, min(bar.maximum(), panel.lines[4].y() - panel.scroll.viewport().height() // 3))
    bar.setValue(0)
    QTest.mouseClick(panel.lines[0], Qt.MouseButton.LeftButton); wait(400)
    assert window.media.position() == 250 and panel.active == 0 and bar.value() == 0
    source.write_text("没有时间轴的歌词\n另一句", encoding="utf-8")
    panel.set_track(str(sample)); wait(60)
    QTest.mouseClick(panel.lines[0], Qt.MouseButton.LeftButton)
    assert window.media.position() == 250 and not panel.times
    assert panel.lines[0].cursor().shape() != Qt.CursorShape.PointingHandCursor


def test_lrc_display_handles_offsets_translations_and_plain_text():
    from musicdesk.lyrics import lyric_lines
    assert lyric_lines("[ar:Artist]\n[offset:-100]\n[00:01.20][00:03.00]Line\n[00:01.20]Translation\n[00:05.00]") == [
        (1100, "Line\nTranslation"), (2900, "Line"), (4900, "•••")]
    assert lyric_lines("[ar:Artist]\nPlain text\n\nAnother line") == [(None, "Plain text"), (None, "Another line")]
    assert lyric_lines("[ar:Artist]\n") == []


def test_lyrics_scroll_reuses_background_and_invalidates_on_resize_or_cover(app, tmp_path, monkeypatch):
    import musicdesk.lyrics as lyrics
    from musicdesk.widgets import STYLE
    rendered = []
    draw = lyrics.draw_cover
    def counted(*args):
        rendered.append(True); return draw(*args)
    monkeypatch.setattr(lyrics, "draw_cover", counted)
    sample = tmp_path / "cached.m4a"
    sample.with_suffix(".lrc").write_text("\n".join(f"[00:{i:02}.00]滚动第 {i} 句" for i in range(35)), encoding="utf-8")
    cover = tmp_path / "cover.png"
    pixels = QImage(60, 60, QImage.Format.Format_RGB32); pixels.fill(QColor("#803060")); pixels.save(str(cover))
    panel = lyrics.LyricsPanel(); panel.setStyleSheet(STYLE); panel.resize(320, 600)
    panel.set_track(str(sample), str(cover)); panel.show(); wait(80)
    try:
        count = len(rendered); background = panel.background.cacheKey()
        positions = []; panel.scroll.verticalScrollBar().valueChanged.connect(positions.append)
        panel.set_position(18000); wait(450)
        assert len(set(positions)) > 15
        assert len(rendered) == count and panel.background.cacheKey() == background
        assert panel.background.devicePixelRatioF() == panel.devicePixelRatioF()
        panel.resize(360, 640); wait(80)
        assert len(rendered) > count and panel.background.cacheKey() != background
        assert panel.background.size() == panel.size() * panel.devicePixelRatioF()
        old_color = panel.background.toImage().pixelColor(50, 50)
        count = len(rendered); panel.set_source(""); wait(80)
        assert len(rendered) > count
        assert panel.background.toImage().pixelColor(50, 50) != old_color
        assert panel.background.toImage().pixelColor(50, 50).name() == panel.base
    finally:
        panel.close()


def test_lyrics_gpu_frames_fractional_positions_and_native_handoff(app, tmp_path):
    from musicdesk.lyrics import LyricsPanel
    from musicdesk.widgets import STYLE
    sample = tmp_path / "gpu.m4a"
    sample.with_suffix(".lrc").write_text("\n".join(f"[{i // 60:02}:{i % 60:02}.00]第 {i} 行\n[{i // 60:02}:{i % 60:02}.00]Translation with wrapped words" for i in range(600)), encoding="utf-8")
    panel = LyricsPanel(); panel.setStyleSheet(STYLE); panel.resize(320, 640)
    panel.set_track(str(sample)); panel.show(); wait(150)
    frames = []
    panel.surface.frameSwapped.connect(lambda: frames.append(panel.surface.painted_offset) if panel.is_scrolling() else None)
    try:
        assert panel.surface.isValid()
        panel.set_position(30000); wait(100)
        assert panel.is_scrolling() and panel.surface.isVisible()
        assert not panel.scroll_timer.isActive()  # The GPU, not a timer, paces this path.
        assert panel.scroll.viewport().updatesEnabled()
        assert 0 < len(panel.surface.rows) < 15  # Never rasterize the entire song.
        for pixels in panel.surface.rows.values():
            assert pixels.devicePixelRatioF() == panel.devicePixelRatioF()
            assert pixels.toImage().pixelColor(0, 0).alpha() == 0
        requested = []; panel.seek_requested.connect(requested.append)
        index = sorted(key[0] for key in panel.surface.rows)[1]
        line = panel.lines[index]
        QTest.mouseClick(panel.windowHandle(), Qt.MouseButton.LeftButton, pos=line.mapTo(panel, line.rect().center()))
        assert requested == [index * 1000]
        assert not panel.is_scrolling()
        panel.set_position(30000, force=True); wait(450)
        assert len(set(frames)) > 10 and any(abs(value - round(value)) > .01 for value in frames)
        assert not panel.surface.isVisible() and panel.scroll.viewport().updatesEnabled()
        assert panel.scroll.verticalScrollBar().value() == panel.scroll_target
        panel.set_position(31000); wait(80)
        panel.resize(360, 600); wait(80)
        assert not panel.is_scrolling() and panel.scroll.viewport().updatesEnabled()
        panel.set_position(590000); wait(450)
        assert panel.active == 590 and not panel.is_scrolling()
        assert panel.scroll.verticalScrollBar().value() == panel.scroll_target
    finally:
        panel.close()


def test_lyrics_replaced_while_open_keeps_new_scroll_running(app, tmp_path):
    from musicdesk.lyrics import LyricsPanel
    sample = tmp_path / "replacement.m4a"
    sample.with_suffix(".lrc").write_text("\n".join(f"[00:{i:02}.00]第 {i} 句 多行歌词自动滚动 Long wrapped translation" for i in range(40)), encoding="utf-8")
    panel = LyricsPanel(); panel.resize(300, 480); panel.show(); wait(100)
    try:
        panel.set_track(str(sample)); panel.set_position(18000)
        wait(100)
        assert panel.is_scrolling() and panel.scroll.verticalScrollBar().value() > 0
        pixels = panel.surface.grabFramebuffer().convertToFormat(QImage.Format.Format_RGBA8888)
        data = bytes(pixels.constBits())
        assert data[0::4] == data[1::4]  # Neutral glyph textures must not contain colored noise.
        wait(400)
        target = min(panel.scroll.verticalScrollBar().maximum(), panel.lines[18].y() - panel.scroll.viewport().height() // 3)
        assert not panel.is_scrolling() and panel.scroll.verticalScrollBar().value() == target
    finally:
        panel.close()


def test_lyrics_gpu_unavailable_keeps_scroll_and_cleanup(app, tmp_path, monkeypatch):
    from musicdesk.lyrics import LyricsPanel
    sample = tmp_path / "fallback.m4a"
    sample.with_suffix(".lrc").write_text("\n".join(f"[00:{i:02}.00]第 {i} 句" for i in range(40)), encoding="utf-8")
    panel = LyricsPanel(); panel.resize(300, 480); panel.set_track(str(sample)); panel.show(); wait(100)
    monkeypatch.setattr(panel.surface, "isValid", lambda: False)
    try:
        panel.set_position(18000); wait(80)
        assert panel.scroll_timer.isActive() and not panel.surface.isVisible()
        assert panel.scroll.verticalScrollBar().value() > 0
        wait(400)
        assert not panel.is_scrolling() and panel.scroll.verticalScrollBar().value() == panel.scroll_target
        assert panel.scroll.viewport().updatesEnabled()
    finally:
        panel.close()


def test_lyrics_scroll_moves_smoothly_and_retargets_without_jumping(app, tmp_path):
    from musicdesk.lyrics import LyricsPanel
    from PySide6.QtWidgets import QAbstractSlider
    sample = tmp_path / "scroll.m4a"
    sample.with_suffix(".lrc").write_text("\n".join(f"[00:{i + 1:02}.00]歌词第 {i + 1} 行" for i in range(35)), encoding="utf-8")
    panel = LyricsPanel(); panel.resize(300, 480); panel.set_track(str(sample)); panel.show(); wait(80)
    bar = panel.scroll.verticalScrollBar()
    try:
        panel.set_position(12000)
        assert panel.active == 11 and bar.value() == 0
        target = min(bar.maximum(), panel.lines[11].y() - panel.scroll.viewport().height() // 3)
        wait(100)
        assert 0 < bar.value() < target
        midway = bar.value()
        panel.set_position(5000)
        assert bar.value() == midway  # A seek reverses from the visible position.
        wait(450)
        assert bar.value() == max(0, panel.lines[4].y() - panel.scroll.viewport().height() // 3)
        assert not panel.is_scrolling()
        panel.set_position(18000); wait(60)
        bar.triggerAction(QAbstractSlider.SliderAction.SliderSingleStepSub)
        manual = bar.value(); wait(60)
        assert bar.value() == manual and not panel.is_scrolling()
        panel.set_position(22000); wait(50); panel.hide()
        assert not panel.is_scrolling()
        panel.show(); panel.set_position(22000, follow=True)
        assert not panel.is_scrolling()
        panel.set_position(0); wait(450)
        assert panel.active == -1 and bar.value() == 0
        panel.set_position(12000); wait(40); panel.set_track("")
        assert not panel.is_scrolling() and bar.value() == 0
    finally:
        panel.close()


@pytest.mark.parametrize("width", (184, 205, 240))
def test_feature_cover_retains_diagonal_detail_at_display_resolution(app, tmp_path, width):
    from PIL import Image, ImageDraw, ImageChops, ImageStat
    source = Image.new("RGB", (640, 640), "black")
    draw = ImageDraw.Draw(source)
    for offset in range(-640, 640, 24):
        draw.polygon([(offset, 0), (offset + 8, 0), (offset + 648, 640), (offset + 640, 640)], fill="white")
    path = tmp_path / "diagonal.png"; source.save(path)
    card = FeatureCard("Test", "Artist", str(path), width=width)
    card.show(); wait(40)
    try:
        card.hovered = False  # Keep the hover tint out of the pixel comparison.
        capture = card.grab(); capture.save(str(tmp_path / "rendered.png"))
        dpr = card.devicePixelRatioF()
        # Compare visible detail against independently resampled source pixels,
        # away from the rounded border, labels, and lower blur/fade region.
        bounds = tuple(round(value * width * dpr) for value in (.08, .23, .92, .54))
        actual = Image.open(tmp_path / "rendered.png").convert("RGB").crop(bounds)
        expected = source.resize((capture.width(), capture.width()), Image.Resampling.LANCZOS).crop(bounds)
        pixels = expected.load()
        for y in range(expected.height):
            shade = 1 - (16 / 255) * max(0, 1 - (y + bounds[1] + .5) / (card.height() * dpr * .45))
            for x in range(expected.width):
                pixels[x, y] = tuple(round(channel * shade) for channel in pixels[x, y])
        error = sum(ImageStat.Stat(ImageChops.difference(actual, expected)).mean) / 3
        assert error < 6, f"Cover lost diagonal detail at {dpr}x scale: mean pixel error {error:.2f}"
    finally:
        card.close()


def test_text_rendering_survives_stylesheets_and_uses_real_bold_faces(window):
    controls = (QLabel, QPushButton, QLineEdit, QComboBox, QPlainTextEdit)
    checked = set()
    for page in ("home", "songs", "settings"):
        window.navigate(page); wait(350)
        for widget in window.findChildren(QWidget):
            if not isinstance(widget, controls): continue
            font = widget.font()
            assert font.styleStrategy() & QFont.StyleStrategy.PreferAntialias
            assert font.styleStrategy() & QFont.StyleStrategy.NoSubpixelAntialias
            assert font.hintingPreference() == QFont.HintingPreference.PreferNoHinting
            raw = QRawFont.fromFont(font)
            if raw.familyName() == "Microsoft YaHei UI":
                assert raw.supportsCharacter("音") and raw.supportsCharacter("A")
                weight = int.from_bytes(raw.fontTable("OS/2").data()[4:6])
                assert weight == (700 if font.weight() >= QFont.Weight.DemiBold else 400)
            checked.update(control for control in controls if isinstance(widget, control))
    assert set(controls).issubset(checked)


@pytest.mark.parametrize("dpr", (1, 1.25, 1.5, 1.75, 2, 2.5, 3))
def test_text_edges_have_smooth_neutral_coverage(app, dpr):
    from PySide6.QtCore import QRectF
    image = QImage(round(200 * dpr), round(48 * dpr), QImage.Format.Format_RGBA8888)
    image.setDevicePixelRatio(dpr); image.fill(QColor("black"))
    painter = QPainter(image); painter.setFont(app.font()); painter.setPen(QColor("white"))
    painter.drawText(QRectF(4, 4, 192, 40), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "音乐 Music 09 デイライト")
    painter.end()
    data = bytes(image.constBits())
    colors = {tuple(data[index:index + 3]) for index in range(0, len(data), 4)}
    edges = {r for r, g, b in colors if 0 < r < 255 and r == g == b}
    assert len(edges) > 32, "Text edges lost their antialiasing coverage"
    assert all(r == g == b for r, g, b in colors), "Subpixel color fringes leaked into text"


def test_rounded_list_rows_keep_continuous_backgrounds_and_selection(window, tmp_path):
    window.navigate("songs"); wait(380)
    table = window.library_scroll.findChild(RoundedTable)
    assert table is not None and isinstance(window.queue_table, RoundedTable)
    QTest.mouseMove(window.windowHandle(), window.nav["songs"].mapTo(window, window.nav["songs"].rect().center())); wait(50)

    def check_row(row, color, name):
        image = table.viewport().grab().toImage(); dpr = image.devicePixelRatio()
        image.save(str(tmp_path / f"{name}.png"))
        top = table.rowViewportPosition(row)
        def sample(x, y): return image.pixelColor(round(x * dpr), round(y * dpr)).name()
        assert sample(3, top + 3) == "#202022"
        assert sample(table.viewport().width() - 4, top + 3) == "#202022"
        assert sample(12, top + 3) == color
        assert sample(table.viewport().width() - 13, top + 3) == color
        for column in range(1, table.columnCount()):
            boundary = table.columnViewportPosition(column)
            assert sample(boundary - 1, top + 10) == sample(boundary + 1, top + 10) == color

    check_row(0, "#262629", "alternating")
    point = QPoint(table.columnViewportPosition(2) + 20, table.rowViewportPosition(1) + 28)
    QTest.mouseMove(window.windowHandle(), table.viewport().mapTo(window, point)); wait(50)
    assert table.hover_row == 1, f"Hover row {table.hover_row}, active={window.isActiveWindow()}"
    check_row(1, "#333337", "hover")
    QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=point); wait(50)
    check_row(1, "#4b343f", "selected")
    QTest.keyClick(table, Qt.Key.Key_Down); wait(50)
    assert table.selectionModel().selectedRows()[0].row() == 2
    check_row(2, "#4b343f", "keyboard")
    point.setY(table.rowViewportPosition(2) + 28)
    point = table.viewport().mapTo(window, point)
    QTest.mouseClick(window.windowHandle(), Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseDClick(window.windowHandle(), Qt.MouseButton.LeftButton, pos=point); wait(100)
    assert window.current_path == window.tracks[2].path


def test_rounded_queue_hover_and_inset_action_button(window, tmp_path):
    window.queue_paused = True
    window.jobs = [{"id": "rounded-test", "url": "https://music.apple.com/cn/song/635770202", "codec": "alac", "state": "queued", "title": "Hotel California"}]
    window.refresh_queue(); window.navigate("queue"); wait(380)
    table = window.queue_table
    cell = table.cellWidget(0, 4); action = cell.findChild(QPushButton)
    assert action.geometry().top() > 0 and action.geometry().bottom() < cell.height() - 1
    QTest.mouseMove(window.windowHandle(), action.mapTo(window, action.rect().center())); wait(60)
    assert table.hover_row == 0
    table.viewport().grab().save(str(tmp_path / "queue-hover.png"))
    QTest.mouseClick(action, Qt.MouseButton.LeftButton); wait(50)
    assert window.jobs[0]["state"] == "cancelled"
    assert table.cellWidget(0, 4).findChild(QPushButton).text() == "重试"
