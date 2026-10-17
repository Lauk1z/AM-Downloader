import cProfile
import pstats

import pytest
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication

from musicdesk.appearance import create_application
from musicdesk.widgets import BlurPanel, Cover, draw_cover


@pytest.fixture(scope="module")
def app(): return QApplication.instance() or create_application([])


def picture(color):
    image = QPixmap(81, 47); image.fill(QColor(color))
    painter = QPainter(image); painter.fillRect(0, 0, 27, 47, QColor("#147ac2")); painter.end()
    return image


@pytest.mark.parametrize("radius", [0, 9])
def test_panel_cache_preserves_background_and_rounded_corners(app, radius):
    class OriginalPanel(BlurPanel):
        def paintEvent(self, event):
            painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            path = QPainterPath(); path.addRoundedRect(QRectF(self.rect()), self.radius, self.radius)
            painter.setClipPath(path); painter.fillRect(self.rect(), QColor(self.base))
            painter.setOpacity(self.tint); draw_cover(painter, self.backdrop, QRectF(self.rect())); painter.end()

    panel = BlurPanel(radius=radius); original = OriginalPanel(radius=radius)
    for widget in (panel, original):
        widget.resize(240, 130); widget.backdrop = picture("#f05078")
    actual, expected = panel.grab().toImage(), original.grab().toImage()
    # Offscreen alpha composition rounds edge coverage by at most one level.
    # Exclude the last fractional device pixel of an opaque widget: the cache
    # deliberately fills that pixel instead of leaving unpainted backing memory.
    height = int(panel.height() * panel.devicePixelRatioF())
    for y in range(height):
        for x in range(actual.width()):
            a, b = actual.pixelColor(x, y), expected.pixelColor(x, y)
            assert max(abs(a.red()-b.red()), abs(a.green()-b.green()), abs(a.blue()-b.blue())) <= 1
    if radius == 0:
        assert panel.panel_cache.toImage().pixelColor(0, actual.height()-1).alpha() == 255
    assert panel.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent) == (radius == 0)


@pytest.mark.parametrize("kind", ["panel", "cover"])
def test_warm_repaints_do_not_rescale_and_cover_resize_invalidates(app, kind):
    widget = BlurPanel() if kind == "panel" else Cover(size=180)
    if kind == "panel": widget.backdrop = picture("#f05078")
    else: widget.pixmap = picture("#f05078")
    first = widget.grab().toImage()
    profile = cProfile.Profile()
    profile.enable()
    for _ in range(12): assert widget.grab().toImage() == first
    profile.disable()
    assert not any("QPixmap.scaled" in key[2] for key in pstats.Stats(profile).stats)
    if kind == "panel": widget.backdrop = picture("#2fc854")
    else: widget.pixmap = picture("#2fc854")
    assert widget.grab().toImage() != first
    widget.setFixedSize(220, 160); widget.grab()
    if kind == "panel":
        assert widget.panel_cache.size() == widget.size() * widget.devicePixelRatioF()
    else:
        assert widget.scaled_key[1:3] == (220, 160)


def test_panel_cache_rebuilds_at_new_scale_and_tint(app):
    class Panel(BlurPanel):
        ratio = 1.0
        def devicePixelRatioF(self): return self.ratio
    widget = Panel(); widget.resize(240, 130); widget.backdrop = picture("#f05078")
    widget.grab(); first = widget.panel_cache.toImage()
    widget.tint = .6; widget.grab(); assert widget.panel_cache.toImage() != first
    widget.ratio = 1.75; widget.grab()
    assert widget.panel_cache.devicePixelRatioF() == 1.75
    assert widget.panel_cache.size() == widget.size() * 1.75
