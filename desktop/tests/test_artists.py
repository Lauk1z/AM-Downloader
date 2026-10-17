import pytest
from PySide6.QtCore import QEventLoop, QPoint, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from musicdesk.appearance import create_application
from musicdesk.artists import ArtistBrowser
from musicdesk.audio_settings import AudioSettings
from musicdesk.core import Track
from musicdesk.window import MusicWindow


def wait(ms):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or create_application([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setattr(AudioSettings, "discover", lambda self: None)
    monkeypatch.setattr(MusicWindow, "scan", lambda self: None)
    value = MusicWindow(tmp_path / "backend", tmp_path / "profile")
    tracks = [Track(str(tmp_path / f"alpha-{album}-{number}.wav"), f"Track {number}", "Alpha Artist", f"Album {album}", 120,
                    codec="pcm", rate=48000, bits=24, number=number) for album in range(8) for number in (2, 1)]
    tracks += [Track(str(tmp_path / f"other-{i}.wav"), f"Other song {i}", f"Artist {i:02}", "Other album", 90) for i in range(30)]
    value.scan_finished((tracks, [], None)); value.show(); value.navigate("artists"); wait(400)
    yield value
    value.tray.exit(); wait(100)


def browser(window):
    return window.library_scroll.findChild(ArtistBrowser)


def heading_geometry(window):
    layout = window.library_scroll.widget().layout()
    heading = layout.itemAt(0).layout().itemAt(0).widget(); subtitle = layout.itemAt(1).widget()
    return (heading.mapTo(window, QPoint()).toTuple(), heading.height(), heading.font().toString(),
            subtitle.mapTo(window, QPoint()).toTuple(), subtitle.height(), subtitle.font().toString(), subtitle.text())


def test_artists_keeps_library_heading_and_uses_inline_album_list(window):
    artists_geometry = heading_geometry(window)
    view = browser(window)
    assert list(view.artist_buttons) == sorted(view.artists, key=str.casefold)
    assert len(view.album_tables) == 8 and all(table.rowCount() == 2 for table in view.album_tables)
    assert view.album_tables[0].item(0, 1).data(Qt.ItemDataRole.AccessibleTextRole) == "Track 1 · Alpha Artist"
    assert view.album_tables[0].item(1, 1).data(Qt.ItemDataRole.AccessibleTextRole) == "Track 2 · Alpha Artist"
    assert window.library_scroll.verticalScrollBar().maximum() == 0
    assert not any(dialog.isVisible() for dialog in window.findChildren(QDialog))
    window.navigate("songs"); wait(400)
    assert heading_geometry(window) == artists_geometry


def test_artist_selection_animates_and_playback_uses_selected_artist(window, monkeypatch):
    calls = []; monkeypatch.setattr(window, "play_tracks", lambda tracks, index=0: calls.append((list(tracks), index)))
    view = browser(window)
    view.artist_buttons["Artist 00"].click()
    assert view.details.transition.isVisible()
    view.artist_buttons["Artist 01"].click(); view.artist_buttons["Artist 00"].click()
    wait(400)
    assert window.artist_state["selected"] == "Artist 00" and len(view.album_tables) == 1
    assert sum(item.isChecked() for item in view.artist_buttons.values()) == 1
    for caption in ("播放此艺人", "随机播放此艺人", "播放专辑：Other album"):
        next(item for item in view.detail_scroll.findChildren(QPushButton) if item.toolTip() == caption).click()
        assert len(calls[-1][0]) == 1 and calls[-1][0][0].artist == "Artist 00"
    view.select_artist("Alpha Artist"); wait(400)
    next(item for item in view.detail_scroll.findChildren(QPushButton) if item.toolTip() == "随机播放此艺人").click()
    assert {track.path for track in calls[-1][0]} == {track.path for track in view.artists["Alpha Artist"]}
    table = view.album_tables[0]
    point = table.visualItemRect(table.item(1, 1)).center()
    QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert calls[-1][1] == 1 and calls[-1][0][1].number == 2
    menus = []; monkeypatch.setattr(window, "track_menu", lambda *args: menus.append(args))
    table.cellWidget(1, 6).findChild(QPushButton).click()
    assert menus[-1][0] == table and menus[-1][1][1].number == 2
    assert table.rowAt(menus[-1][2].y()) == 1


def test_artist_selection_and_independent_scroll_survive_refresh_and_navigation(window):
    view = browser(window)
    view.artist_list.verticalScrollBar().setValue(150)
    view.detail_scroll.verticalScrollBar().setValue(300)
    expected = dict(window.artist_state)
    assert expected["list_scroll"] == 150 and expected["detail_scroll"] == 300
    for refresh in (lambda: window.render_library(), lambda: window.scan_finished((window.tracks, [], None)),
                    lambda: (window.navigate("songs"), window.navigate("artists"))):
        refresh(); wait(400)
        view = browser(window)
        assert window.artist_state == expected
        assert view.artist_list.verticalScrollBar().value() == 150
        assert view.detail_scroll.verticalScrollBar().value() == 300


def test_artist_search_empty_results_and_removal_choose_valid_selection(window):
    window.search.setText("Artist 12"); wait(450)
    view = browser(window)
    assert list(view.artist_buttons) == ["Artist 12"] and len(view.album_tables) == 1
    window.search.setText("no such musician"); wait(450)
    assert browser(window) is None
    window.search.clear(); wait(450)
    assert window.artist_state["selected"] in browser(window).artists
    tracks = [track for track in window.tracks if track.artist != window.artist_state["selected"]]
    window.scan_finished((tracks, [], None)); wait(400)
    assert window.artist_state["selected"] in browser(window).artists
    window.scan_finished(([], [], None)); wait(400)
    assert browser(window) is None and window.current_page == "artists"


@pytest.mark.parametrize("lyrics", [False, True])
def test_small_artist_page_has_no_clipped_columns_and_keeps_selection(window, lyrics):
    window.resize(1100, 720); wait(400)
    if lyrics: window.show_lyrics(); wait(600)
    view = browser(window)
    assert window.artist_state["selected"] == "Alpha Artist"
    assert view.artist_list.width() >= 145 and view.details.width() >= 250
    assert window.library_scroll.horizontalScrollBar().maximum() == 0
    assert view.detail_scroll.horizontalScrollBar().maximum() == 0
    table = view.album_tables[0]
    assert table.columnWidth(1) > 100
    assert table.columnViewportPosition(6) + table.columnWidth(6) <= table.viewport().width()
    if lyrics: assert view.album_rows[0][0].direction() == view.album_rows[0][0].Direction.TopToBottom
