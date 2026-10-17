import pytest
from PySide6.QtCore import Qt, QPoint, QEventLoop, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget, QStyle, QStyleOptionSlider

from musicdesk.appearance import create_application
from musicdesk.scrolling import SmoothScrollArea, HoverScrollBar
from musicdesk.widgets import STYLE
from test_settings_wheel import window


def wait(ms):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()


@pytest.fixture(scope="module")
def app(): return QApplication.instance() or create_application([])


@pytest.fixture
def area(app):
    value = SmoothScrollArea(); value.setStyleSheet(STYLE)
    body = QWidget(); body.setFixedSize(300, 5000); value.setWidget(body)
    value.resize(450, 400); value.show(); wait(60)
    QTest.mouseMove(value.windowHandle(), QPoint(30, 30)); wait(1100)
    assert isinstance(value.verticalScrollBar(), HoverScrollBar)
    yield value
    value.close(); value.deleteLater(); wait(30)


def part(bar, control):
    option = QStyleOptionSlider(); bar.initStyleOption(option)
    return bar.style().subControlRect(QStyle.ComplexControl.CC_ScrollBar, option, control, bar)


def move(area, widget, point=None):
    QTest.mouseMove(area.windowHandle(), widget.mapTo(area, point or widget.rect().center()))


def test_hover_animates_without_layout_change_then_delays_collapse(area):
    bar = area.verticalScrollBar(); before = area.viewport().geometry()
    samples = []; bar.animation.valueChanged.connect(samples.append)
    collapsed = bar.grab().toImage()
    slider = part(bar, QStyle.SubControl.SC_ScrollBarSlider)
    move(area, bar, slider.center()); wait(250)
    expanded = bar.grab().toImage()
    assert bar.reveal == 1 and len(set(samples)) >= 5
    assert expanded != collapsed and area.viewport().geometry() == before
    y = round(slider.center().y() * expanded.devicePixelRatio())
    bright = lambda image: sum(image.pixelColor(x, y).red() > 95 for x in range(image.width()))
    assert bright(expanded) > bright(collapsed)
    # The rail appears away from the thumb; both endpoint arrows fade in.
    assert expanded.pixelColor(1, expanded.height() // 2) != collapsed.pixelColor(1, collapsed.height() // 2)
    for control in (QStyle.SubControl.SC_ScrollBarSubLine, QStyle.SubControl.SC_ScrollBarAddLine):
        rect = part(bar, control); assert not rect.isEmpty()
        assert expanded.copy(rect.x(), round(rect.y()*expanded.devicePixelRatio()), expanded.width(), round(rect.height()*expanded.devicePixelRatio())) != collapsed.copy(rect.x(), round(rect.y()*collapsed.devicePixelRatio()), collapsed.width(), round(rect.height()*collapsed.devicePixelRatio()))
    move(area, area.viewport()); wait(450); assert bar.reveal == 1
    wait(650); assert bar.reveal == 0 and not bar.animation.state() == bar.animation.State.Running
    assert area.viewport().geometry() == before


def test_native_arrows_repeat_track_click_and_thumb_drag(area):
    bar = area.verticalScrollBar(); bar.setValue(800); step = bar.singleStep()
    down = part(bar, QStyle.SubControl.SC_ScrollBarAddLine).center()
    up = part(bar, QStyle.SubControl.SC_ScrollBarSubLine).center()
    QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=down)
    assert bar.value() == 800 + step
    QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=up); assert bar.value() == 800
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=down); wait(700)
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=down)
    assert bar.value() > 800 + step
    old = bar.value(); thumb = part(bar, QStyle.SubControl.SC_ScrollBarSlider)
    QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=QPoint(6, thumb.bottom()+25))
    assert bar.value() > old
    thumb = part(bar, QStyle.SubControl.SC_ScrollBarSlider); old = bar.value()
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=thumb.center())
    QTest.mouseMove(bar, thumb.center()+QPoint(0, 35)); wait(40)
    assert bar.isSliderDown() and bar.value() > old
    # Leaving while holding the thumb must not collapse it under the pointer.
    move(area, area.viewport()); wait(1050)
    assert bar.reveal == 1 and bar.isSliderDown()
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(-50, thumb.center().y()+35))
    wait(1100); assert bar.reveal == 0 and not bar.isSliderDown()


def test_reenter_cancels_hide_and_hidden_bar_stops_animation(area):
    bar = area.verticalScrollBar(); move(area, bar); wait(220)
    move(area, area.viewport()); wait(500); move(area, bar); wait(450)
    assert bar.reveal == 1 and not bar.hide_delay.isActive()
    area.hide(); wait(30)
    assert bar.reveal == 0 and not bar.hide_delay.isActive()
    assert bar.animation.state() == bar.animation.State.Stopped


def test_frameless_window_keeps_scrollbar_clickable_and_outer_edge_resizable(window):
    import ctypes
    from ctypes import wintypes
    bar = window.settings_page.verticalScrollBar()
    assert isinstance(bar, HoverScrollBar) and bar.isVisible()
    user32 = ctypes.WinDLL("user32")
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    def hit(point):
        screen = wintypes.POINT(round(point.x()*window.devicePixelRatioF()), round(point.y()*window.devicePixelRatioF()))
        user32.ClientToScreen(int(window.winId()), ctypes.byref(screen))
        return user32.SendMessageW(int(window.winId()), 0x0084, 0, (screen.y & 0xffff) << 16 | (screen.x & 0xffff))
    for part_id in (QStyle.SubControl.SC_ScrollBarSlider, QStyle.SubControl.SC_ScrollBarSubLine, QStyle.SubControl.SC_ScrollBarAddLine):
        assert hit(bar.mapTo(window, part(bar, part_id).center())) == 1  # HTCLIENT
    assert hit(QPoint(window.width()-1, window.height()//2)) == 11  # HTRIGHT
