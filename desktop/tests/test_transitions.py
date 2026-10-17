import time
from pathlib import Path
import pytest
from PySide6.QtCore import Qt, QEventLoop, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from musicdesk.appearance import create_application
from musicdesk.window import MusicWindow
from musicdesk.widgets import AlbumRail


def wait(ms):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or create_application([])


@pytest.fixture
def window(app, tmp_path):
    value = MusicWindow(Path(r'D:\AppleMusicDecrypt-Windows'), tmp_path)
    value.audio.setMuted(True); value.show(); wait(1200)
    yield value
    value.tray.exit(); wait(150)


def test_album_arrows_animate_reverse_and_stop_at_bounds(window):
    rail = window.library_scroll.findChildren(AlbumRail)[0]
    assert rail.horizontalScrollBar().maximum() > 0
    frames = []
    rail.transition.frameSwapped.connect(lambda: frames.append(time.perf_counter()) if rail.transition.clock.isValid() else None)
    arrow = next(b for b in window.library_scroll.findChildren(type(window.play_button)) if b.toolTip() == '向右滚动')
    QTest.mouseClick(arrow, Qt.MouseButton.LeftButton, delay=0)
    assert rail.transition.clock.isValid()
    wait(65)
    offset = rail.transition.offset()
    assert 0 < offset < rail.transition.to_offset
    pixels = rail.transition.grabFramebuffer()
    assert not pixels.isNull()
    rail.scroll_page(-1)
    assert abs(rail.transition.from_offset - offset) < 20
    wait(400)
    assert rail.horizontalScrollBar().value() == round(rail.transition.to_offset)
    assert rail.transition.before.isNull() and not rail.transition.isVisible()
    rail.horizontalScrollBar().setValue(rail.horizontalScrollBar().maximum())
    rail.scroll_page(1)
    assert not rail.transition.clock.isValid()
    assert len(frames) >= 5


def test_lyrics_main_page_moves_with_panel_and_reverses(window):
    old_width = window.stack.width()
    QTest.mouseClick(window.lyric_button, Qt.MouseButton.LeftButton, delay=0)
    t = window.body.transition
    assert t.clock.isValid() and t.reflow
    before, after = t.reflow
    assert before.keys() == after.keys()
    assert any(before[key][0] != after[key][0] for key in before)
    wait(75)
    visible = t.visible_width()
    assert 0 < visible < window.lyrics.width()
    assert window.stack.width() < window.body.width() - visible < old_width
    frame = t.grabFramebuffer()
    assert not frame.isNull()
    visible = t.visible_width()
    QTest.mouseClick(window.lyric_button, Qt.MouseButton.LeftButton, delay=0)
    assert visible <= t.from_width < window.lyrics.width()
    wait(400)
    assert not window.body.opened and window.stack.width() == old_width
    assert not t.isVisible() and t.before.isNull() and t.after.isNull()


def test_window_size_change_animates_reflow_and_navigation_can_interrupt(window):
    window.resize(1150, 720); wait(500)
    rail = window.library_scroll.findChildren(AlbumRail)[0]
    rail.horizontalScrollBar().setValue(200)
    old_step = rail.widget().layout().itemAt(0).widget().width() + 16
    window.showMaximized(); wait(250)
    t = window.stack.transition
    assert t.isVisible() and t.mode == 'reflow'
    assert not t.before.isNull() and t.reflow
    wait(420)
    assert not t.isVisible() and window.stack.resize_before.isNull()
    new_rail = window.library_scroll.findChildren(AlbumRail)[0]
    assert new_rail.horizontalScrollBar().value() == min(new_rail.horizontalScrollBar().maximum(), round(200 / old_step * (new_rail.widget().layout().itemAt(0).widget().width() + 16)))
    window.showNormal(); wait(250)
    assert t.isVisible() and t.mode == 'reflow'
    window.navigate('songs'); wait(450)
    assert window.current_page == 'songs' and not t.isVisible() and window.stack.resize_before.isNull()
    window.showFullScreen(); wait(250)
    assert t.isVisible() and t.mode == 'reflow'
    wait(420)
    window.showNormal(); wait(500)
    assert not t.isVisible()


def test_display_interruption_does_not_skip_remaining_motion(window):
    rail = window.library_scroll.findChildren(AlbumRail)[0]
    rail.scroll_page(1); wait(40)
    t = rail.transition; previous = t.progress
    time.sleep(.25)  # Simulate the OS suspending presentation during a state change.
    t.advance()
    assert previous < t.progress <= previous + .12
    assert t.isVisible()
    wait(400)
    assert not t.isVisible() and rail.horizontalScrollBar().value() == round(t.to_offset)
