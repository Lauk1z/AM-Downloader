import pytest
from PySide6.QtCore import QEventLoop, QTimer, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QTableWidgetItem

from musicdesk.appearance import create_application
from musicdesk.scrolling import SmoothScrollArea
from musicdesk.widgets import RoundedTable, AlbumRail


def wait(ms):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()


@pytest.fixture(scope="module")
def app(): return QApplication.instance() or create_application([])


def wheel(widget, angle=-120, pixels=0):
    point = widget.rect().center()
    event = QWheelEvent(QPointF(point), QPointF(widget.mapToGlobal(point)), QPoint(0, pixels), QPoint(0, angle), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)
    return event.isAccepted()


@pytest.fixture(params=["page", "table"])
def area(app, request):
    if request.param == "page":
        value = SmoothScrollArea(); body = QWidget(); body.setFixedSize(400, 6000); value.setWidget(body)
    else:
        value = RoundedTable(150, 2); value.verticalHeader().setDefaultSectionSize(56)
        for row in range(150): value.setItem(row, 0, QTableWidgetItem(str(row)))
    value.resize(450, 350); value.show(); wait(100)
    yield value
    value.close(); value.deleteLater(); wait(30)


def test_wheel_has_multiple_intermediate_positions_and_accumulates(area):
    bar = area.verticalScrollBar(); samples = []; bar.valueChanged.connect(samples.append)
    wheel(area.viewport()); target = area.smooth_wheel.target
    assert target > 0 and bar.value() == 0
    wait(40); assert 0 < bar.value() < target
    wheel(area.viewport()); assert area.smooth_wheel.target > target
    wait(450)
    assert len(set(samples)) >= 8
    assert samples == sorted(samples) and bar.value() == round(area.smooth_wheel.target)
    assert not area.smooth_wheel.timer.isActive()


def test_reversal_native_pixels_and_manual_scroll_interrupt_pending_motion(area):
    bar = area.verticalScrollBar(); bar.setValue(500)
    wheel(area.viewport(), -360); wait(45)
    before = bar.value(); wheel(area.viewport(), 120); wait(35)
    assert bar.value() < before
    wheel(area.viewport(), pixels=-17); assert not area.smooth_wheel.timer.isActive()
    position = bar.value(); wait(80); assert bar.value() == position
    wheel(area.viewport()); wait(25); bar.setValue(1234); wait(150)
    assert bar.value() == 1234 and not area.smooth_wheel.timer.isActive()
    bar.setValue(bar.maximum()); assert not wheel(area.viewport())


def test_vertical_wheel_over_album_rail_scrolls_outer_page(app):
    page = SmoothScrollArea(); page.setWidgetResizable(True); page.resize(450, 350)
    body = QWidget(); layout = QVBoxLayout(body)
    rail = AlbumRail(); rail.setFixedHeight(150)
    strip = QWidget(); strip.setFixedSize(2000, 140); rail.setWidget(strip); layout.addWidget(rail)
    lower = QLabel("bottom"); lower.setFixedHeight(2000); layout.addWidget(lower)
    page.setWidget(body); page.show(); wait(150)
    # Real window wheel delivery exercises Qt's propagation from the nested rail.
    from PySide6.QtTest import QTest
    point = rail.viewport().mapTo(page, rail.viewport().rect().center())
    QTest.wheelEvent(page.windowHandle(), point, QPoint(0, -120)); wait(80)
    assert page.verticalScrollBar().value() > 0 and rail.horizontalScrollBar().value() == 0
    page.close(); page.deleteLater(); wait(100)
