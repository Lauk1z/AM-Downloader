import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QEventLoop, QPoint, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from musicdesk.appearance import create_application
from musicdesk.widgets import blurred_cover
from musicdesk.window import MusicWindow

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows caption integration")


def wait(ms):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or create_application([])


@pytest.fixture
def window(app, tmp_path):
    value = MusicWindow(Path(r"D:\AppleMusicDecrypt-Windows"), tmp_path)
    value.audio.setMuted(True); value.resize(1150, 760); value.show(); wait(1000)
    yield value
    value.tray.exit(); wait(100)


def native(window, message, wparam=0, lparam=0):
    user = ctypes.WinDLL("user32")
    user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.SendMessageW.restype = ctypes.c_ssize_t
    return user.SendMessageW(int(window.winId()), message, wparam, lparam)


def coordinates(window, point):
    user = ctypes.WinDLL("user32")
    user.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    scale = window.devicePixelRatioF()
    location = wintypes.POINT(round(point.x() * scale), round(point.y() * scale))
    user.ClientToScreen(int(window.winId()), ctypes.byref(location))
    return (location.x & 0xffff) | ((location.y & 0xffff) << 16)


def test_controls_share_player_background_without_separate_titlebar(window, tmp_path):
    assert window.menuWidget() is None and not hasattr(window, "titlebar")
    assert window.centralWidget().y() == window.player_bar.y() == window.sidebar.y() == 0
    assert window.player_bar.height() == 64
    assert window.window_controls.parentWidget() is window.player_bar
    pixels = []
    for name, color in (("warm", "#ffad73"), ("cool", "#659dff")):
        source = tmp_path / (name + ".png")
        image = QImage(200, 200, QImage.Format.Format_RGB32); image.fill(QColor(color)); image.save(str(source))
        window.set_backdrop(str(source)); wait(30)
        assert window.player_bar.source == window.sidebar.source == str(source)
        assert window.player_bar.backdrop.cacheKey() == window.sidebar.backdrop.cacheKey()
        player = window.player_bar.grab().toImage()
        scale = window.devicePixelRatioF()
        pixels.append(player.pixelColor(round((window.player_bar.width() - 54) * scale), round(50 * scale)).name())
        misses = blurred_cover.cache_info().misses
        window.resize(window.width() + 20, window.height()); wait(120)
        assert blurred_cover.cache_info().misses == misses
        assert window.window_controls.geometry().right() == window.player_bar.width() - 1
        assert window.window_controls.y() == 0
        for control in (window.now_playing, window.play_button, window.volume_button, window.lyric_button):
            rect = control.rect().translated(control.mapTo(window.player_bar, QPoint()))
            assert not rect.intersects(window.window_controls.geometry())
    assert pixels[0] != pixels[1]
    window.set_backdrop(""); wait(30)
    assert window.player_bar.backdrop.isNull()
    empty = window.player_bar.grab().toImage()
    assert empty.pixelColor(round((window.player_bar.width() - 54) * scale), round(50 * scale)).name() == window.player_bar.base


def test_native_caption_edges_system_menu_and_buttons(window):
    for point, expected in ((QPoint(0, 0), 13), (QPoint(window.width() - 1, 0), 14),
                            (QPoint(0, window.height() - 1), 16), (QPoint(window.width() - 1, window.height() - 1), 17),
                            (QPoint(0, 100), 10), (QPoint(window.width() - 1, 100), 11),
                            (QPoint(500, 0), 12), (QPoint(500, window.height() - 1), 15),
                            (QPoint(window.width() - 54, 50), 2)):
        assert native(window, 0x0084, 0, coordinates(window, point)) == expected
    point = window.caption_icon.mapTo(window, window.caption_icon.rect().center())
    assert native(window, 0x0084, 0, coordinates(window, point)) == 3
    for control in (window.minimize_button, window.maximize_button, window.close_button):
        point = control.mapTo(window, control.rect().center())
        assert native(window, 0x0084, 0, coordinates(window, point)) == 1
    original = window.geometry()
    native(window, 0x00A3, 2, coordinates(window, QPoint(window.width() - 54, 50))); wait(550)
    assert window.isMaximized()
    assert abs(window.geometry().height() - window.screen().availableGeometry().height()) <= 2
    QTest.mouseClick(window.maximize_button, Qt.MouseButton.LeftButton); wait(550)
    assert not window.isMaximized() and window.geometry() == original
    QTest.mouseClick(window.minimize_button, Qt.MouseButton.LeftButton); wait(100)
    assert not window.isVisible() and window.tray.icon.isVisible()
    window.tray.restore(); wait(400)
    QTest.mouseClick(window.close_button, Qt.MouseButton.LeftButton); wait(100)
    dialog = window.tray.close_dialog
    assert dialog and dialog.isVisible() and window.isVisible()
    QTest.mouseClick(dialog.tray_button, Qt.MouseButton.LeftButton); wait(100)
    assert not window.isVisible() and window.tray.icon.isVisible()
    assert not window.closing and not window.tray.exiting


def test_fullscreen_restores_controls_and_exact_window_geometry(window):
    original = window.geometry()
    for _ in range(2):
        window.showMaximized(); wait(500)
        for control in (window.minimize_button, window.maximize_button, window.close_button):
            point = control.mapTo(window, control.rect().center())
            assert native(window, 0x0084, 0, coordinates(window, point)) == 1
        window.showFullScreen(); wait(900)
        assert window.window_controls.isHidden() and window.centralWidget().y() == 0
        assert window.geometry() == window.screen().geometry()
        assert not window.stack.transition.isVisible() and not window.stack.transition.clock.isValid()
        window.showNormal(); wait(900)
        assert window.window_controls.isVisible() and window.centralWidget().y() == 0
        assert window.geometry() == original
        assert not window.stack.transition.isVisible() and not window.stack.transition.clock.isValid()


def test_player_hover_seek_buttons_and_search_are_not_drag_regions(window):
    for control in (window.now_playing, window.play_title, window.seek, window.play_button,
                    window.shuffle, window.repeat, window.volume_button, window.lyric_button,
                    window.like_button, window.more_button, window.search):
        point = control.mapTo(window, QPoint(control.width() // 2, min(10, control.height() // 2)))
        assert native(window, 0x0084, 0, coordinates(window, point)) == 1
    window.search.setFocus(); QTest.keyClicks(window.search, "Eagles")
    assert window.search.text() == "Eagles"
    QTest.mouseClick(window.shuffle, Qt.MouseButton.LeftButton)
    assert window.shuffle.isChecked() and not window.isMaximized()
