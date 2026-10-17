import pytest
from PySide6.QtCore import QPoint, QTimer

from test_artists import app, window, browser, wait
from musicdesk.widgets import PageTransition, capture_layout


def artist_geometry(window):
    view = browser(window)
    widgets = [view, view.artist_list, view.details]
    widgets += [cover for _, cover in view.album_rows] + view.album_tables
    return ([(*item.mapTo(window.stack, QPoint()).toTuple(), item.width(), item.height()) for item in widgets],
            view.artist_list.verticalScrollBar().value(), view.detail_scroll.verticalScrollBar().value())


def item_geometry(items):
    return {key: (rect, clip) for key, (rect, clip, _) in items.items()}


@pytest.mark.parametrize("width", [1100, 1440])
@pytest.mark.parametrize("restore", [False, True])
def test_artist_incoming_snapshot_matches_settled_layout(window, monkeypatch, width, restore):
    window.resize(width, 900); wait(450)
    if restore:
        view = browser(window)
        view.artist_list.verticalScrollBar().setValue(150)
        view.detail_scroll.verticalScrollBar().setValue(300)
    window.navigate("home"); wait(400)
    captured = []
    original = PageTransition.start

    def start(self, *args, **kwargs):
        if self is window.stack.transition: captured.append(artist_geometry(window))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(PageTransition, "start", start)
    pending = []; QTimer.singleShot(0, lambda: pending.append(True))
    window.navigate("artists")
    assert not pending  # Snapshot preparation must not pump timers or user input.
    assert window.stack.transition.isVisible()
    wait(450)
    assert captured[0] == artist_geometry(window)
    if restore: assert captured[0][1:] == (150, 300)


@pytest.mark.parametrize("page", ["home", "recent", "artists"])
@pytest.mark.parametrize("width", [1100, 1440])
def test_lyrics_snapshot_rects_and_clips_match_live_page(window, page, width):
    window.resize(width, 900); wait(450)
    window.navigate(page); wait(400)
    for _ in range(2):
        window.show_lyrics()
        transition = window.body.transition
        assert transition.isVisible() and transition.reflow
        expected = item_geometry(transition.reflow[1])
        wait(450)
        actual = item_geometry(capture_layout(window.stack.currentWidget()))
        assert expected == actual
        # Off-screen card edges must not be included only in the cached frame.
        assert {key for key, (rect, clip) in expected.items() if rect.intersects(clip)} == {
            key for key, (rect, clip) in actual.items() if rect.intersects(clip)}

