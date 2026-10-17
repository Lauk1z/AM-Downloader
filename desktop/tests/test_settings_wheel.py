import pytest
from PySide6.QtCore import QEventLoop, QPoint, QPointF, QTimer, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from musicdesk.appearance import create_application
from musicdesk.audio_settings import AudioSettings
from musicdesk.window import MusicWindow


def wait(ms):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()


def wheel(widget, delta):
    window = widget.window()
    point = widget.mapTo(window, widget.rect().center())
    QTest.mouseMove(window.windowHandle(), point)
    QTest.wheelEvent(window.windowHandle(), point, QPoint(0, delta))
    wait(30)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or create_application([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setattr(AudioSettings, "discover", lambda self: None)
    value = MusicWindow(tmp_path / "backend", tmp_path / "profile")
    value.client.send = lambda command: pytest.fail("Settings wheel test must not start the backend")
    value.audio_settings.devices = [{"kind": "asio", "name": f"Test DAC {i:02}", "id": str(i)} for i in range(50)]
    value.audio_settings.mode.setCurrentIndex(value.audio_settings.mode.findData("asio"))
    value.resize(1100, 720); value.show(); value.navigate("settings"); wait(400)
    yield value
    value.tray.exit(); wait(100)


def controls(window):
    return {"codec": window.default_codec, "language": window.language_combo, "rate": window.rate_combo,
            "bits": window.bits_combo, "mode": window.audio_settings.mode,
            "device": window.audio_settings.device, "dsd": window.audio_settings.dsd}


@pytest.mark.parametrize("name", ["codec", "language", "rate", "bits", "mode", "device", "dsd"])
@pytest.mark.parametrize("focused", [False, True])
def test_closed_settings_option_does_not_change_and_page_scrolls(window, name, focused):
    fields = controls(window); combo = fields[name]
    if name != "mode": combo.setCurrentIndex(1)
    window.settings_page.ensureWidgetVisible(combo); wait(50)
    if focused: combo.setFocus()
    else: window.search.setFocus()
    before = {key: field.currentData() for key, field in fields.items()}
    scrollbar = window.settings_page.verticalScrollBar(); position = scrollbar.value()
    assert scrollbar.maximum() > 0 and combo.isEnabled()
    wheel(combo, 120 if position > scrollbar.maximum() / 2 else -120)
    assert {key: field.currentData() for key, field in fields.items()} == before
    assert scrollbar.value() != position


def test_settings_dropdown_still_opens_scrolls_and_selects_with_mouse(window):
    combo = window.audio_settings.device
    combo.view().setMaximumHeight(180)
    window.settings_page.ensureWidgetVisible(combo); wait(50)
    page_position = window.settings_page.verticalScrollBar().value()
    QTest.mouseClick(combo, Qt.MouseButton.LeftButton); wait(500)
    view = combo.view(); assert view.isVisible()
    scrollbar = view.verticalScrollBar(); assert scrollbar.maximum() > 0
    position = scrollbar.value(); point = view.viewport().rect().center()
    event = QWheelEvent(QPointF(point), QPointF(view.viewport().mapToGlobal(point)), QPoint(), QPoint(0, -120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(view.viewport(), event)
    assert scrollbar.value() > position
    assert window.settings_page.verticalScrollBar().value() == page_position
    target = view.indexAt(view.viewport().rect().center()); assert target.isValid()
    QTest.mouseMove(view.viewport(), view.visualRect(target).center()); wait(30)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.visualRect(target).center())
    assert combo.currentIndex() == target.row() and not view.isVisible()


def test_settings_keyboard_selection_still_works(window):
    combo = window.language_combo; combo.setCurrentIndex(0)
    window.settings_page.ensureWidgetVisible(combo); combo.setFocus()
    QTest.keyClick(combo, Qt.Key.Key_Down)
    assert combo.currentIndex() == 1
    QTest.keyClick(combo, Qt.Key.Key_Up)
    assert combo.currentIndex() == 0
