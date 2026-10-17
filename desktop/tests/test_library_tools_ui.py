import time
from pathlib import Path
import wave

import pytest
from PySide6.QtCore import QEventLoop, QTimer, QPoint
from PySide6.QtWidgets import QApplication, QMenu
from musicdesk.appearance import create_application
from musicdesk.audio_settings import AudioSettings
from musicdesk.core import Store, scan_library
from musicdesk.library_tools import AlbumEditor
from musicdesk.widgets import AlbumCard, SettingsComboBox
from musicdesk.window import MusicWindow


def wait(ms=50):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()


def until(check):
    deadline = time.monotonic() + 10
    while not check():
        wait()
        assert time.monotonic() < deadline


@pytest.fixture(scope="module")
def app(): return QApplication.instance() or create_application([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setattr(AudioSettings, "discover", lambda self: None)
    folder = tmp_path / "audio"; folder.mkdir()
    for index in range(3):
        with wave.open(str(folder / f"{index}.wav"), "wb") as out:
            out.setparams((1, 2, 44100, 0, "NONE", "not compressed")); out.writeframes(b"\0\0" * 44100 * 3)
    Store(tmp_path / "profile").set("library", str(folder))
    value = MusicWindow(Path(__file__).resolve().parents[1] / "vendor/backend", tmp_path / "profile")
    value.audio.setMuted(True); value.show(); until(lambda: len(value.tracks) == 3 and not value.scanning)
    yield value
    value.tray.exit(); wait(150)


def test_album_context_editor_saves_and_refreshes_inline_album(window, monkeypatch):
    window.navigate("albums"); wait(400)
    card = window.library_scroll.findChild(AlbumCard)
    def choose(menu, *args):
        next(action for action in menu.actions() if action.text() == "编辑标签与封面").trigger()
    class TestMenu(QMenu):
        def exec(self, *args): choose(self, *args)
    monkeypatch.setattr("musicdesk.window.QMenu", TestMenu)
    card.customContextMenuRequested.emit(QPoint(20, 20)); wait()
    editor = next(dialog for dialog in window.findChildren(AlbumEditor) if dialog.isVisible())
    editor.fields["album"][0].setText("Edited Album")
    editor.fields["album_artist"][0].setText("Album Artist")
    editor.fields["year"][0].setText("2025")
    editor.fields["edition"][0].setText("Original Master")
    editor.table.item(0, 0).setText("Edited Song")
    editor.save.click(); until(lambda: not editor.isVisible() and not window.scanning)
    assert {track.album for track in window.tracks} == {"Edited Album"}
    assert {track.year for track in window.tracks} == {2025}
    assert any(track.title == "Edited Song" for track in window.tracks)
    assert len(window.albums) == 1
    assert len(list(Path(window.tracks[0].path).parent.glob("*.am-tag-backup-*"))) == 3


def test_filters_and_shuffle_use_current_scope(window, monkeypatch):
    window.tracks[0].year = 2020; window.tracks[1].year = window.tracks[2].year = 2021
    window.navigate("songs"); wait(400)
    year = next(combo for combo in window.library_scroll.findChildren(SettingsComboBox) if combo.itemText(0) == "全部年份")
    year.setCurrentIndex(year.findData(2021)); wait()
    selected = window.filtered_tracks(); assert len(selected) == 2
    def select(autoplay=True): window.current_path = window.playlist[window.play_index].path
    monkeypatch.setattr(window, "play_current", select)
    window.shuffle.setChecked(True); window.play_tracks(selected)
    first = window.current_path; window.skip(1); second = window.current_path
    assert first != second
    for _ in range(10):
        last = window.current_path; window.skip(1)
        assert window.current_path != last and window.current_path in {track.path for track in selected}
    window.navigate("home"); assert len(window.filtered_tracks()) == 3


def test_edit_current_track_restores_position_and_updates_player(window):
    from PySide6.QtMultimedia import QMediaPlayer
    track = window.tracks[0]; window.play_tracks([track])
    until(lambda: window.media.isSeekable())
    window.media.pause(); window.media.setPosition(700); wait(100)
    editor = AlbumEditor(window, [track]); editor.show()
    editor.table.item(0, 0).setText("Changed While Paused")
    editor.save.click(); until(lambda: not editor.isVisible() and not window.scanning)
    assert window.play_title.text() == "Changed While Paused"
    assert abs(window.media.position() - 700) < 150
    assert window.media.playbackState() != QMediaPlayer.PlaybackState.PlayingState


def test_cue_import_prepare_seek_and_hide_never_delete_whole_file(window, tmp_path, monkeypatch):
    source = tmp_path / "disc.wav"
    with wave.open(str(source), "wb") as out:
        out.setparams((1, 2, 44100, 0, "NONE", "not compressed")); out.writeframes(b"\0\0" * 44100 * 2)
    cue = tmp_path / "disc.cue"
    cue.write_text('TITLE "Cue Album"\nFILE "disc.wav" WAVE\n TRACK 01 AUDIO\n TITLE "One"\n INDEX 01 00:00:00\n TRACK 02 AUDIO\n TITLE "Two"\n INDEX 01 00:01:00')
    window.import_audio_files([str(cue)]); until(lambda: len(window.tracks) == 5 and not window.scanning)
    assert str(cue) in window.store.get("imported_files")
    assert all("#amtrack=" not in value for value in window.store.get("imported_files"))
    tracks = [track for track in window.tracks if track.container]
    window.playlist = tracks; window.play_index = 1; window.play_current(autoplay=False)
    until(lambda: not window.preparing and window.media.isSeekable())
    assert window.media.duration() == 1000 and "audio-cache" in window.media.source().toLocalFile()
    window.media.setPosition(500); wait(100); assert abs(window.media.position() - 500) < 100
    table = window.track_table(tracks)
    def inspect(menu, *args):
        assert not next(action for action in menu.actions() if action.text() == "删除本地文件").isEnabled()
    class TestMenu(QMenu):
        def exec(self, *args): inspect(self, *args)
    monkeypatch.setattr("musicdesk.window.QMenu", TestMenu)
    window.track_menu(table, tracks, QPoint(10, 10))
    assert window.remove_track(tracks[0]); until(lambda: not window.scanning)
    assert source.exists() and cue.exists()
    reread, _ = scan_library(window.library_folder(), window.store.directory / "covers", window.store.get("imported_files"), window.store.get("removed_files"))
    assert len([track for track in reread if track.container]) == 1
