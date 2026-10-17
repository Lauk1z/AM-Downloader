import json
import time
import wave
from dataclasses import replace

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from test_playlists_ui import app, window, wait, until, drop
from musicdesk.output_chain import chain_details
from musicdesk.window import MusicWindow


def quiet_queue(window, monkeypatch, count=4):
    monkeypatch.setattr(window.media, "play", lambda: None)
    window.play_tracks(window.tracks[:count]); wait(40)


def test_natural_end_waits_two_seconds_before_loading_next_file(window):
    tracks = window.tracks[:2]
    ended = []
    window.media.mediaStatusChanged.connect(lambda state: ended.append(time.monotonic()) if state == QMediaPlayer.MediaStatus.EndOfMedia else None)
    window.play_tracks(tracks)
    until(lambda: window.gap_timer.isActive())
    assert window.current_path == tracks[0].path and window.gap_timer.interval() == 2000
    wait(1000)
    assert window.current_path == tracks[0].path
    until(lambda: window.current_path == tracks[1].path)
    assert time.monotonic() - ended[0] >= 1.98
    until(lambda: window.media.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia)
    assert not window.gap_timer.isActive()  # Final song does not loop implicitly.


def test_pause_during_gap_holds_until_explicit_resume(window, monkeypatch):
    quiet_queue(window, monkeypatch)
    first = window.current_path
    window.media_status(QMediaPlayer.MediaStatus.EndOfMedia)
    window.toggle_play(); wait(2150)
    assert window.current_path == first and window.gap_waiting and not window.gap_timer.isActive()
    window.toggle_play(); wait(500)
    assert window.current_path == first
    until(lambda: window.current_path != first)
    assert not window.gap_waiting


@pytest.mark.parametrize("action", ["skip", "replace", "clear", "seek", "lyrics", "exit"])
def test_explicit_actions_cancel_the_old_gap(window, monkeypatch, action):
    quiet_queue(window, monkeypatch)
    window.media_status(QMediaPlayer.MediaStatus.EndOfMedia)
    window.media_status(QMediaPlayer.MediaStatus.EndOfMedia)
    if action == "skip": window.skip(1)
    elif action == "replace": window.play_tracks(window.tracks[2:])
    elif action == "clear": window.clear_playback_queue()
    elif action == "seek": window.seek_to(25)
    elif action == "lyrics":
        monkeypatch.setattr(window.media, "isSeekable", lambda: True)
        window.seek_lyrics(25)
    else: window.tray.exit()
    chosen = window.current_path
    assert not window.gap_waiting and not window.gap_timer.isActive()
    wait(2100)
    assert window.current_path == chosen


@pytest.mark.parametrize("mode", ["normal", "repeat", "shuffle"])
def test_last_track_gap_obeys_repeat_and_shuffle(window, monkeypatch, mode):
    quiet_queue(window, monkeypatch, 1)
    window.repeat.setChecked(mode == "repeat"); window.shuffle.setChecked(mode == "shuffle")
    window.media_status(QMediaPlayer.MediaStatus.EndOfMedia)
    assert window.gap_timer.isActive() == (mode != "normal")


def test_queue_insert_move_remove_and_clear_preserve_audio_files(window, monkeypatch):
    tracks = window.tracks[:]
    before = {track.path: open(track.path, "rb").read() for track in tracks}
    quiet_queue(window, monkeypatch, 2)
    source = window.media.source()
    window.add_to_playback_queue([tracks[3], tracks[2]], next_up=True)
    assert window.playlist == [tracks[0], tracks[3], tracks[2], tracks[1]]
    window.add_to_playback_queue([tracks[3], tracks[3]])
    assert window.playlist == [tracks[0], tracks[2], tracks[1], tracks[3]]
    window.playback_queue.table.rowsMoved.emit([3], 1); wait(20)
    assert window.playlist == [tracks[0], tracks[3], tracks[2], tracks[1]]
    window.remove_from_playback_queue([1])
    assert window.playlist == [tracks[0], tracks[2], tracks[1]] and window.media.source() == source
    assert window.store.get("playback_queue") == [track.path for track in window.playlist]
    window.clear_playback_queue()
    assert not window.playlist and not window.current_path and window.media.source().isEmpty()
    assert window.playback_queue.table.rowCount() == 0
    assert window.store.get("playback_queue") == [] and window.store.get("last_track") == ""
    assert before == {track.path: open(track.path, "rb").read() for track in tracks}


def test_removing_current_track_keeps_paused_state_and_reindexes(window, monkeypatch):
    quiet_queue(window, monkeypatch)
    window.play_index = 2; window.play_current(autoplay=False)
    kept = window.playlist[3]
    window.remove_from_playback_queue([0, 2])
    assert window.current_path == kept.path and window.play_index == 1
    assert window.media.playbackState() != QMediaPlayer.PlaybackState.PlayingState


def test_queue_drag_from_library_and_explicit_order_overrides_shuffle(window, monkeypatch):
    quiet_queue(window, monkeypatch, 1)
    window.navigate("songs"); wait(350)
    window.show_now_playing(); wait(400)
    table = window.library_scroll.findChild(type(window.playback_queue.table)); table.selectRow(2)
    window.shuffle.setChecked(True)
    drop(window.playback_queue.table.viewport(), table.track_mime(), QPoint(20, window.playback_queue.table.viewport().height() - 4))
    assert window.playlist == [window.tracks[0], window.tracks[2]] and not window.shuffle.isChecked()
    assert window.body.opened and window.playback_queue.isVisible() and not window.lyrics.isVisible()
    assert window.current_page == "songs" and window.queue_page is not window.stack.currentWidget()
    width = window.stack.width()
    window.show_lyrics(); wait(400)
    assert window.lyrics.isVisible() and not window.playback_queue.isVisible()
    assert window.stack.width() == width and not window.now_queue_button.isChecked()
    window.show_now_playing(); wait(400)
    window.grab().save(str(window.store.directory / "now-playing.png"))
    window.show_now_playing(); wait(400)
    assert not window.body.opened and window.stack.width() > width


def test_shuffle_queue_preview_matches_actual_next_without_repeats(window, monkeypatch):
    quiet_queue(window, monkeypatch)
    window.shuffle.setChecked(True)
    visited = [window.current_path]
    for _ in range(3):
        window.playback_queue.refresh(); shown = window.playback_queue.table.track_paths
        expected = shown[shown.index(window.current_path) + 1]
        window.playback_queue.refresh()  # Looking at the queue must not advance it.
        window.skip(1)
        assert window.current_path == expected
        visited.append(window.current_path)
    assert len(set(visited)) == 4


def test_queue_restores_order_and_last_track_without_autoplay(window, monkeypatch):
    quiet_queue(window, monkeypatch)
    window.playback_queue.move([3], 0); wait(20)
    expected = [track.path for track in window.playlist]; current = window.current_path
    directory, root = window.store.directory, window.root
    window.tray.exit(); wait(100)
    restored = MusicWindow(root, directory); restored.audio.setMuted(True); restored.show()
    try:
        until(lambda: not restored.scanning and bool(restored.current_path))
        assert [track.path for track in restored.playlist] == expected and restored.current_path == current
        assert restored.playlist[restored.play_index].path == current
        assert restored.media.playbackState() != QMediaPlayer.PlaybackState.PlayingState
        assert not restored.gap_timer.isActive()
    finally: restored.tray.exit(); wait(100)


def test_removing_current_shuffled_song_keeps_round_and_remaining_order(window, monkeypatch):
    quiet_queue(window, monkeypatch)
    window.shuffle.setChecked(True)
    visited = [window.current_path]
    window.skip(1); visited.append(window.current_path)
    expected = window.shuffle_order.upcoming([track.path for track in window.playlist], window.current_path)
    assert len(expected) == 2
    window.remove_from_playback_queue([window.play_index])
    assert window.current_path == expected[0] and visited[0] in window.shuffle_order.visited
    visited.append(window.current_path)
    window.skip(1); visited.append(window.current_path)
    assert window.current_path == expected[1] and len(set(visited)) == 4


def test_cleared_queue_stays_empty_after_restart_despite_play_history(window, monkeypatch):
    quiet_queue(window, monkeypatch)
    assert window.store.get("recently_played")
    window.clear_playback_queue(); window.tray.exit(); wait(100)
    restored = MusicWindow(window.root, window.store.directory); restored.audio.setMuted(True); restored.show()
    try:
        until(lambda: not restored.scanning and bool(restored.tracks))
        assert not restored.current_path and not restored.playlist and restored.media.source().isEmpty()
    finally: restored.tray.exit(); wait(100)


def test_restored_queue_skips_missing_files_and_selects_available_track_without_playing(window, monkeypatch):
    quiet_queue(window, monkeypatch)
    missing = str(window.store.directory / "removed.wav")
    expected = [window.tracks[3].path, window.tracks[1].path]
    window.store.update({"playback_queue": [missing, *expected], "last_track": missing})
    window.tray.exit(); wait(100)
    restored = MusicWindow(window.root, window.store.directory); restored.audio.setMuted(True); restored.show()
    try:
        until(lambda: not restored.scanning and bool(restored.tracks))
        assert [track.path for track in restored.playlist] == expected and restored.current_path == expected[0]
        assert restored.media.playbackState() != QMediaPlayer.PlaybackState.PlayingState
    finally: restored.tray.exit(); wait(100)


def test_track_and_album_menus_offer_play_next_and_last(window, monkeypatch):
    quiet_queue(window, monkeypatch, 1)
    seen = []
    class Menu(QMenu):
        def exec(self, point):
            actions = {action.text(): action for action in self.actions()}; seen.append(actions)
            assert "下一首播放" in actions and "最后播放" in actions
            actions["下一首播放"].trigger()
    monkeypatch.setattr("musicdesk.window.QMenu", Menu)
    window.navigate("songs"); wait(350)
    table = window.library_scroll.findChild(type(window.playback_queue.table))
    window.track_menu(table, window.tracks, table.visualItemRect(table.item(2, 1)).center())
    assert window.playlist[1] == window.tracks[2]
    window.album_menu(table, [window.tracks[3]], table.rect().center())
    assert window.playlist[1] == window.tracks[3] and len(seen) == 2


@pytest.mark.parametrize("fmt,rate,bits", [("pcm", 96000, 24), ("dop", 352800, 24), ("dsd", 22579200, 1)])
def test_chain_uses_confirmed_driver_output_and_clears_it_on_stop(window, monkeypatch, fmt, rate, bits):
    engine = window.media
    track = replace(window.tracks[0], codec="pcm" if fmt == "pcm" else "dsd", rate=96000 if fmt == "pcm" else 5644800 if fmt == "dop" else rate, bits=24 if fmt == "pcm" else 1)
    engine.config = {"mode": "asio", "device": "test-driver", "device_name": "Chosen DAC", "dsd": "native" if fmt == "dsd" else "dop"}
    assert "尚未建立输出" in dict(chain_details(engine, track))["输出接口"]
    engine._intent = engine.PlaybackState.PlayingState; engine._source_info = {"rate": track.rate}
    ready = {"event": "ready", "mode": "asio", "format": fmt, "device": "Confirmed DAC", "rate": rate, "bits": bits}
    class Process:
        def readAllStandardOutput(self): return (json.dumps(ready) + "\n").encode()
    engine._read(Process(), engine._generation)
    details = dict(chain_details(engine, track))
    assert "驱动已确认" in details["输出接口"] and details["输出设备"] == "Confirmed DAC"
    assert "软件音量旁路" in details["音频处理"]
    if fmt == "dop": assert "DoP 传输帧" in details["输出接口"] and "DSD128" in details["输出接口"]
    if fmt == "dsd": assert "DSD512" in details["输出接口"] and "22.5792" in details["输出接口"]
    engine.stop()
    assert engine.negotiated_output is None and "驱动已确认" not in dict(chain_details(engine, track))["输出接口"]
    engine._read(Process(), engine._generation - 1)
    assert engine.negotiated_output is None


def test_shared_and_container_chain_do_not_claim_unmeasured_output(window, monkeypatch):
    quiet_queue(window, monkeypatch)
    track = replace(window.tracks[0], codec="dsd", rate=2822400, bits=1)
    details = dict(chain_details(window.media, track))
    assert "未直接测得" in details["输出接口"] and "DSD 已解码为 PCM" in details["音频处理"]
    cue = replace(track, container="disc.cue", area="")
    assert "CUE 分轨缓存" in dict(chain_details(window.media, cue))["解码与传输"]
    assert "正在准备" in dict(chain_details(window.media, cue, True))["当前状态"]
    window.show_output_chain(); wait(80)
    dialog = window.output_dialog
    window.show_output_chain()
    assert window.output_dialog is dialog and dialog.isVisible()
    window.audio.setMuted(False); window.set_volume(31)
    assert "31%" in dialog.fields[4].text()
    dialog.grab().save(str(window.store.directory / "output-chain.png"))
    dialog.close()


def test_tray_hide_restore_and_controls_keep_playback_available(window, monkeypatch):
    quiet_queue(window, monkeypatch)
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    window.showMaximized(); wait(100)
    window.tray.minimize()
    assert not window.isVisible() and window.tray.icon.isVisible()
    current = window.current_path
    window.tray.next.trigger()
    assert window.current_path != current
    window.tray.activate(QSystemTrayIcon.ActivationReason.Trigger); wait(100)
    assert window.isVisible() and window.isMaximized()
    window.tray.show_queue(); wait(350)
    assert window.playback_queue.isVisible()
    window.media_status(QMediaPlayer.MediaStatus.EndOfMedia); window.tray.refresh()
    assert window.tray.play.text() == "暂停"
    window.tray.play.trigger()
    assert not window.gap_timer.isActive() and window.tray.play.text() == "播放"
    window.tray.menu.grab().save(str(window.store.directory / "tray-menu.png"))


@pytest.mark.parametrize("caption", [False, True])
def test_close_hides_without_stopping_playback_or_backend(window, monkeypatch, caption):
    window.store.set("close_action", "tray")
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    track = window.tracks[0]
    with wave.open(track.path, "wb") as stream:
        stream.setparams((1, 2, 44100, 0, "NONE", "not compressed"))
        stream.writeframes(b"\0\0" * 44100 * 5)
    window.play_tracks([replace(track, duration=5)])
    until(lambda: window.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
    process = window.client.process
    monkeypatch.setattr(process, "state", lambda: process.ProcessState.Running)
    shutdown = []
    monkeypatch.setattr(window.client, "shutdown", lambda: shutdown.append("backend"))
    monkeypatch.setattr(window.media, "shutdown", lambda: shutdown.append("playback"))
    monkeypatch.setattr(window.audio_settings, "shutdown", lambda: shutdown.append("audio"))
    window.active_job = {"id": "downloading", "state": "DOWNLOADING"}
    window.queue_paused = False
    position = window.media.position()
    if caption: window.close_button.click()
    else: assert not window.close()
    wait(300)
    assert not window.isVisible() and window.tray.icon.isVisible()
    assert not window.closing and not window.tray.exiting and not shutdown
    assert not window.queue_paused and window.active_job["state"] == "DOWNLOADING"
    assert window.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    assert window.media.position() > position
    window.close(); wait(30)  # Repeated close requests must stay hidden and keep playing.
    assert not window.closing and not shutdown
    window.tray.restore(); wait(50)
    assert window.isVisible() and window.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    window.active_job = None
    monkeypatch.undo()


def test_close_keeps_pending_track_gap_and_advances_while_hidden(window, monkeypatch):
    window.store.set("close_action", "tray")
    quiet_queue(window, monkeypatch)
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    first = window.current_path
    window.media_status(QMediaPlayer.MediaStatus.EndOfMedia)
    window.close_button.click()
    assert window.gap_waiting and window.gap_timer.isActive() and not window.closing
    until(lambda: window.current_path != first)
    assert not window.isVisible() and window.tray.icon.isVisible()
    assert window.current_path == window.playlist[1].path


def test_tray_unavailable_falls_back_and_hidden_exit_waits_for_close(window, monkeypatch):
    window.store.set("close_action", "tray")
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    window.close_button.click(); wait(40)
    assert window.isVisible() and window.isMinimized()
    assert not window.closing and not window.tray.exiting
    window.tray.restore(); wait(40)
    requested = []
    from PySide6.QtWidgets import QApplication
    monkeypatch.setattr(QApplication.instance(), "quit", lambda: requested.append(True))
    window.hide(); window.tray.exit(); wait(50)
    assert not window.tray.icon.isVisible() and requested


@pytest.mark.parametrize("hidden", [False, True])
def test_tray_exit_waits_for_backend_shutdown_before_quitting(window, monkeypatch, hidden):
    from PySide6.QtWidgets import QApplication
    process = window.client.process
    state = [process.ProcessState.Running]
    shutdown, quit_calls = [], []
    monkeypatch.setattr(process, "state", lambda: state[0])
    monkeypatch.setattr(window.client, "shutdown", lambda: shutdown.append(True))
    monkeypatch.setattr(QApplication.instance(), "quit", lambda: quit_calls.append(True))
    if hidden: window.hide()
    window.tray.exit()
    wait(50)
    assert shutdown == [True] and not quit_calls and window.closing
    assert window.tray.icon.isVisible()
    state[0] = process.ProcessState.NotRunning
    window.backend_event({"event": "disconnected"}); wait(50)
    assert quit_calls == [True] and not window.tray.icon.isVisible()
