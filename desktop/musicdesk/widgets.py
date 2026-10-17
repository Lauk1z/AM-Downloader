from pathlib import Path
from functools import lru_cache
from PySide6.QtCore import Qt, QSize, QRect, QRectF, QPoint, QPointF, Signal, QElapsedTimer, QTimer, QEvent, QCoreApplication, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QColor, QFont, QImage, QImageReader, QPainter, QPainterPath, QPen, QPixmap, QLinearGradient, QBrush, QPalette, QCursor, QRegion
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QWidget, QStackedWidget, QTableWidget, QStyledItemDelegate, QStyleOptionViewItem, QStyle, QSlider, QScrollArea, QComboBox
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from .icons import IconLabel, icon
from . import APP_NAME
from .scrolling import SmoothWheel

RED = "#fa4164"
TEXT = "#f2f2f5"
MUTED = "#a0a0a8"


class SettingsComboBox(QComboBox):
    def wheelEvent(self, event):
        if self.view().isVisible(): super().wheelEvent(event)
        else: event.ignore()


class MusicButton(QPushButton):
    def paintEvent(self, event):
        super().paintEvent(event)
        if self.property("nav") and self.isChecked():
            p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(RED))
            x = 22 if self.property("indented") else 2
            p.drawRoundedRect(QRectF(x, (self.height() - 16) / 2, 3, 16), 1.5, 1.5); p.end()


def button(text="", symbol=None, primary=False, compact=False):
    value = MusicButton(text)
    value.setCursor(Qt.CursorShape.PointingHandCursor)
    value.setMinimumHeight(36 if compact else 40)
    if symbol:
        value.setIcon(icon(symbol, "white" if primary else "#c6c6cd", 18))
        value.setIconSize(QSize(18, 18))
    value.setProperty("primary", primary)
    value.setProperty("compact", compact)
    return value


def label(text="", size=12, bold=False, color=None):
    value = QLabel(text)
    value.setTextFormat(Qt.TextFormat.PlainText)
    font = value.font(); font.setPointSize(size); font.setBold(bold); value.setFont(font)
    value.setStyleSheet(f"font-size:{size}pt;font-weight:{700 if bold else 400};color:{color or TEXT};background:transparent;")
    return value


class PlayerLabel(QLabel):
    """Keep the full track name while eliding to the live player width."""
    def __init__(self, text, bold=False, color=TEXT):
        super().__init__()
        self.full_text = text; self.setMinimumWidth(0)
        self.setTextFormat(Qt.TextFormat.PlainText); self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = self.font(); font.setPointSize(10); font.setBold(bold); self.setFont(font)
        self.setStyleSheet(f"font-size:10pt;font-weight:{700 if bold else 400};color:{color};background:transparent;")
        self.setText(text)

    def setText(self, text):
        self.full_text = text
        super().setText(self.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, self.contentsRect().width()))

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.full_text) + 2, self.fontMetrics().height())

    def resizeEvent(self, event):
        super().resizeEvent(event); self.setText(self.full_text)


class PlaybackSlider(QSlider):
    """Seek from anywhere on the thin track without a visible thumb."""
    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Match the player's right corner; the left end joins the album cover.
        outline = QPainterPath(); outline.addRoundedRect(QRectF(-4, -4, self.width() + 4, self.height() + 4), 4, 4)
        track = QPainterPath(); track.addRect(QRectF(0, self.height() - 2, self.width(), 2))
        track = track.intersected(outline); painter.fillPath(track, QColor("#69696b"))
        progress = (self.value() - self.minimum()) / max(1, self.maximum() - self.minimum())
        filled = QPainterPath(); filled.addRect(QRectF(0, 0, self.width() * progress, self.height()))
        painter.fillPath(track.intersected(filled), QColor("#dedee0")); painter.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton: return super().mousePressEvent(event)
        self.setSliderDown(True); self.mouseMoveEvent(event)

    def mouseMoveEvent(self, event):
        if not self.isSliderDown(): return super().mouseMoveEvent(event)
        area = self.contentsRect()
        self.setSliderPosition(QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), round(event.position().x()) - area.left(), max(1, area.width() - 1)))
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton: return super().mouseReleaseEvent(event)
        self.mouseMoveEvent(event); self.setSliderDown(False); event.accept()


class VolumeSlider(PlaybackSlider):
    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setContentsMargins(10, 0, 10, 0); self.setMinimumHeight(28); self.setMouseTracking(True)
        self.highlight = 0.0
        self.animation = QVariantAnimation(self); self.animation.setDuration(180); self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self.animate_thumb)
        self.value_tip = VolumeValueTip(self)
        self.valueChanged.connect(self.refresh_value_tip)

    def thumb_center(self):
        area = self.contentsRect()
        x = area.left() + (area.width() - 1) * (self.value() - self.minimum()) / max(1, self.maximum() - self.minimum())
        return QPointF(x, self.height() / 2)

    def animate_thumb(self, value):
        self.highlight = value; self.update()

    def set_hover(self, position):
        target = -.6 if self.isSliderDown() else (1.0 if (position - self.thumb_center()).manhattanLength() < 14 else 0.0)
        if self.animation.endValue() == target and (self.animation.state() == QVariantAnimation.State.Running or self.highlight == target): return
        self.animation.stop(); self.animation.setStartValue(self.highlight); self.animation.setEndValue(target); self.animation.start()

    def refresh_value_tip(self):
        if not self.isVisible() or not (self.value_tip.isVisible() or self.underMouse() or self.isSliderDown()): return
        self.value_tip.setText(f"{self.value()}%")
        anchor = self.mapToGlobal(QPoint(round(self.thumb_center().x()), 0))
        screen = self.screen().availableGeometry()
        x = max(screen.left(), min(anchor.x() - self.value_tip.width() // 2, screen.right() - self.value_tip.width()))
        self.value_tip.move(x, max(screen.top(), anchor.y() - self.value_tip.height() - 5)); self.value_tip.show()

    def enterEvent(self, event):
        super().enterEvent(event); self.set_hover(event.position()); self.refresh_value_tip()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if not self.isSliderDown(): self.set_hover(QPointF(-100, -100)); self.value_tip.hide()

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event); self.set_hover(event.position()); self.refresh_value_tip()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event); self.set_hover(event.position())
        if not self.rect().contains(event.position().toPoint()): self.value_tip.hide()

    def keyPressEvent(self, event):
        super().keyPressEvent(event)
        if event.key() != Qt.Key.Key_Escape and self.isVisible():
            self.value_tip.show(); self.refresh_value_tip()

    def hideEvent(self, event):
        self.value_tip.hide(); self.animation.stop(); self.highlight = 0.0; super().hideEvent(event)

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self.contentsRect(); x, y = self.thumb_center().x(), self.thumb_center().y()
        p.setPen(QPen(QColor("#a0a0a3"), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
        if self.value() > self.minimum():
            p.setPen(QPen(QColor("#fa3558"), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)); p.drawLine(QPointF(area.left(), y), QPointF(x, y))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor("#4a4a4d")); p.drawEllipse(QPointF(x, y), 10, 10)
        radius = 5.5 + 1.8 * self.highlight
        p.setBrush(QColor("#fa3558")); p.drawEllipse(QPointF(x, y), radius, radius); p.end()


class VolumeValueTip(QLabel):
    def __init__(self, parent):
        super().__init__(parent, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(44, 25)
        font = self.font(); font.setPointSize(9); self.setFont(font)

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("#69696d"), 1)); p.setBrush(QColor("#303033"))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 5, 5)
        p.setPen(QColor("#eeeeef")); p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text()); p.end()


class VolumePopup(QFrame):
    def __init__(self, parent):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False); self.setFixedSize(220, 50)
        self.background = QColor("#252527")
        self.leave_timer = QTimer(self); self.leave_timer.setSingleShot(True); self.leave_timer.setInterval(450)
        self.leave_timer.timeout.connect(self.dismiss_if_outside)

    def dismiss_if_outside(self):
        slider = self.findChild(VolumeSlider)
        if not self.underMouse() and not slider.isSliderDown(): self.hide()

    def enterEvent(self, event):
        self.leave_timer.stop(); super().enterEvent(event)

    def leaveEvent(self, event):
        self.leave_timer.start(); super().leaveEvent(event)

    def hideEvent(self, event):
        self.leave_timer.stop()
        slider = self.findChild(VolumeSlider)
        if slider is not None: slider.value_tip.hide()
        super().hideEvent(event)

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("#7b7b7e"), 1)); p.setBrush(self.background)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 10, 10); p.end()


@lru_cache(maxsize=48)
def blurred_cover(source, stamp=0):
    """Cache a real Gaussian blur; only render buffers are changed, never files."""
    from PIL import Image, ImageFilter, ImageOps
    try:
        with Image.open(source) as original:
            pixels = ImageOps.fit(original.convert("RGB"), (240, 240)).filter(ImageFilter.GaussianBlur(22)).convert("RGBA")
        raw = pixels.tobytes()
        return QPixmap.fromImage(QImage(raw, 240, 240, 960, QImage.Format.Format_RGBA8888).copy())
    except (OSError, ValueError):
        return QPixmap()


@lru_cache(maxsize=64)
def cached_cover(source, stamp):
    reader = QImageReader(source); reader.setAutoTransform(True)
    size = reader.size()
    if size.width() > 640 or size.height() > 640:
        reader.setScaledSize(size.scaled(640, 640, Qt.AspectRatioMode.KeepAspectRatio))
    return QPixmap.fromImage(reader.read())


def load_cover(source):
    path = Path(source) if source else None
    return cached_cover(str(path), path.stat().st_mtime_ns) if path and path.is_file() else QPixmap()


def draw_cover(painter, pixmap, rect):
    if pixmap.isNull(): return
    scaled = pixmap.scaled(int(rect.width()), int(rect.height()), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    painter.drawPixmap(rect, scaled, QRectF((scaled.width() - rect.width()) / 2, (scaled.height() - rect.height()) / 2, rect.width(), rect.height()))


class BlurPanel(QFrame):
    def __init__(self, base="#202022", tint=0.18, radius=0, parent=None):
        super().__init__(parent)
        self.base, self.tint, self.radius = base, tint, radius
        self.backdrop = QPixmap()
        self.source = ""
        self.panel_cache = QPixmap()
        self.panel_cache_key = None
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, radius == 0 and QColor(base).alpha() == 255)

    def set_source(self, source):
        if source == self.source: return
        self.source = source
        self.backdrop = blurred_cover(source, Path(source).stat().st_mtime if source and Path(source).is_file() else 0) if source else QPixmap()
        self.update()

    def prepare_background(self):
        # Transparent scrolling children repaint their backdrop every frame.
        # Cache the final physical pixels, including tint, instead of repeatedly
        # scaling and blending a window-sized album image.
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), dpr, self.backdrop.cacheKey(), self.base, self.tint, self.radius)
        if self.panel_cache_key != key:
            self.panel_cache = QPixmap(self.size() * dpr); self.panel_cache.setDevicePixelRatio(dpr)
            self.panel_cache.fill(QColor(self.base) if self.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent) else Qt.GlobalColor.transparent)
            layer = QPainter(self.panel_cache); layer.setRenderHint(QPainter.RenderHint.Antialiasing)
            path = QPainterPath(); path.addRoundedRect(QRectF(self.rect()), self.radius, self.radius); layer.setClipPath(path)
            layer.fillRect(self.rect(), QColor(self.base))
            layer.setOpacity(self.tint); draw_cover(layer, self.backdrop, QRectF(self.rect())); layer.end()
            self.panel_cache_key = key

    def paintEvent(self, event):
        self.prepare_background()
        painter = QPainter(self); painter.drawPixmap(0, 0, self.panel_cache)
        painter.end()


def capture_content(widget, rect=None):
    """Capture foreground pixels without Qt's default solid window background."""
    rect = widget.rect() if rect is None else rect
    frame = QPixmap(rect.size() * widget.devicePixelRatioF())
    frame.setDevicePixelRatio(widget.devicePixelRatioF()); frame.fill(Qt.GlobalColor.transparent)
    widget.render(frame, QPoint(), QRegion(rect), QWidget.RenderFlag.DrawChildren)
    return frame


def paint_background(painter, widget):
    panel = widget.parentWidget()
    while panel is not None and not isinstance(panel, BlurPanel): panel = panel.parentWidget()
    if panel is None:
        painter.fillRect(widget.rect(), QColor("#202022")); return
    panel.prepare_background()
    position = widget.mapTo(panel, QPoint())
    painter.drawPixmap(-position, panel.panel_cache)


def settle_layout(root):
    """Resolve child sizing and scrollbars before caching an animation frame."""
    if root.layout(): root.layout().activate()
    for child in root.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
        if child.isVisibleTo(root): settle_layout(child)
    QCoreApplication.sendPostedEvents(root, QEvent.Type.LayoutRequest)
    if root.layout(): root.layout().activate()


def capture_layout(root):
    """Cache visible layout items once, keeping stable layout paths across reflow."""
    settle_layout(root)
    items = {}

    def visit(widget, key, clip):
        if not widget.isVisibleTo(root): return
        rect = QRectF(widget.mapTo(root, QPoint()), widget.size())
        if isinstance(widget, QScrollArea):
            viewport = QRectF(widget.viewport().mapTo(root, QPoint()), widget.viewport().size())
            if widget.widget(): visit(widget.widget(), key, clip.intersected(viewport))
        elif widget.layout() and not isinstance(widget, (FeatureCard, AlbumCard, BlurPanel)):
            walk(widget.layout(), key, clip)
        else:
            items[key] = (rect, clip, capture_content(widget) if rect.intersects(clip) else QPixmap())

    def walk(layout, key, clip):
        for index in range(layout.count()):
            item = layout.itemAt(index); path = key + (index,)
            if item.widget(): visit(item.widget(), path, clip)
            elif item.layout(): walk(item.layout(), path, clip)

    visit(root, (), QRectF(root.rect()))
    return items


def reflow_items(before, after, amount):
    """One image per item: moving text never crossfades with a second copy."""
    result = {}
    for key, (end, end_clip, image) in after.items():
        start, start_clip, previous = before.get(key, (end, end_clip, image))
        if image.isNull(): image = previous
        rect = QRectF(*(a + (b - a) * amount for a, b in zip(start.getRect(), end.getRect())))
        clip = QRectF(*(a + (b - a) * amount for a, b in zip(start_clip.getRect(), end_clip.getRect())))
        result[key] = (rect, clip, image)
    return result


def paint_reflow(painter, items):
    for rect, clip, image in items.values():
        painter.save(); painter.setClipRect(clip, Qt.ClipOperation.IntersectClip)
        painter.drawPixmap(rect, image, QRectF(image.rect())); painter.restore()


class PageTransition(QOpenGLWidget):
    """Composite two cached pages on the GPU, paced by completed display frames."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.before, self.after = QPixmap(), QPixmap()
        self.progress = 0.0
        self.last_tick = 0
        self.mode = "page"
        self.reflow = None
        self.capturing_content = False
        self.clock = QElapsedTimer()
        self.frameSwapped.connect(self.advance)
        self.hide()

    def advance(self):
        if not self.isVisible() or not self.clock.isValid(): return
        elapsed = self.clock.nsecsElapsed()
        # A native fullscreen switch may suspend presentation. Resume the
        # remaining motion instead of consuming it while the window is hidden.
        self.progress = min(1.0, self.progress + min(elapsed - self.last_tick, 33_333_333) / 300_000_000)
        self.last_tick = elapsed
        if self.progress >= 1.0: self.clear()
        else: self.update()

    def clear(self):
        self.clock.invalidate(); self.hide()
        self.before, self.after = QPixmap(), QPixmap()
        self.reflow = None

    def start(self, before, after, mode="page", reflow=None):
        self.mode = mode
        self.reflow = reflow
        self.before, self.after = before, after
        self.setGeometry(self.parentWidget().rect())
        self.progress = 0.0; self.last_tick = 0; self.show(); self.raise_(); self.repaint()
        if self.isValid(): self.clock.start(); self.update()
        else: self.clear()

    def hold(self, frame):
        self.clock.invalidate(); self.before, self.after = frame, QPixmap()
        self.mode = "reflow"; self.progress = 0.0
        self.setGeometry(self.parentWidget().rect()); self.show(); self.raise_(); self.update()

    def paintGL(self):
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self.capturing_content:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        else: paint_background(painter, self)
        self.paint_content(painter); painter.end()

    def capture_content(self):
        # Use the same GPU sampling when a second navigation interrupts motion.
        # The caller hides this overlay before the next window presentation.
        self.capturing_content = True
        try: frame = QPixmap.fromImage(self.grabFramebuffer())
        finally: self.capturing_content = False
        frame.setDevicePixelRatio(self.devicePixelRatioF())
        return frame

    def paint_content(self, painter):
        if self.mode == "reflow":
            eased = 1 - (1 - self.progress) ** 3
            if self.reflow: paint_reflow(painter, reflow_items(*self.reflow, eased))
            else: painter.drawPixmap(0, 0, self.before)
            return
        painter.setOpacity(max(0.0, 1 - self.progress / .30)); painter.drawPixmap(0, 0, self.before)
        incoming = max(0.0, (self.progress - .12) / .88)
        eased = 1 - (1 - incoming) ** 3
        painter.setOpacity(eased); painter.drawPixmap(QPointF(0, 24 * (1 - eased)), self.after)


class AnimatedPageStack(QStackedWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.transition = PageTransition(self)
        self.resize_before = QPixmap()
        self.resize_items = {}

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.prepare_transition)

    def prepare_transition(self):
        if self.transition.clock.isValid(): return
        if not self.transition.isValid():
            # Create the GPU surface during startup, before the first navigation.
            self.transition.setGeometry(self.rect())
            self.transition.show(); self.transition.lower()
            self.transition.grabFramebuffer(); self.transition.hide()

    def capture_page(self):
        # Keep the current visual frame if another click interrupts the animation.
        if self.transition.isVisible() and self.transition.isValid():
            frame = self.transition.capture_content()
        else:
            settle_layout(self)
            frame = capture_content(self) if self.isVisible() else QPixmap()
        self.transition.clear()
        self.resize_before = QPixmap()
        self.resize_items = {}
        return frame

    def capture_items(self):
        if self.transition.isVisible() and self.transition.reflow:
            return reflow_items(*self.transition.reflow, 1 - (1 - self.transition.progress) ** 3)
        return capture_layout(self.currentWidget())

    def reveal_page(self, before):
        if not before.isNull() and self.isVisible():
            settle_layout(self)
            self.transition.start(before, capture_content(self))

    def begin_resize(self):
        if self.resize_before.isNull() and self.isVisible():
            items = self.capture_items()
            self.resize_before = self.capture_page()
            self.resize_items = items
            if not self.resize_before.isNull(): self.transition.hold(self.resize_before)

    def finish_resize(self):
        before, self.resize_before = self.resize_before, QPixmap()
        items, self.resize_items = self.resize_items, {}
        if before.isNull(): return
        self.transition.clear()
        if self.isVisible(): self.transition.start(before, QPixmap(), mode="reflow", reflow=(items, self.capture_items()))

    def resizeEvent(self, event):
        if self.resize_before.isNull(): self.transition.clear()
        else: self.transition.setGeometry(self.rect())
        super().resizeEvent(event)


class RailTransition(PageTransition):
    """Move a bounded cached album strip at fractional pixel positions."""
    def __init__(self, rail):
        super().__init__(rail)
        self.rail = rail
        self.from_offset = self.to_offset = self.strip_left = 0
        # Prevent clicks on an underlying card whose visual position is moving.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

    def offset(self):
        return self.from_offset + (self.to_offset - self.from_offset) * (1 - (1 - self.progress) ** 3)

    def clear(self):
        if self.clock.isValid(): self.rail.horizontalScrollBar().setValue(round(self.offset()))
        super().clear()

    def mousePressEvent(self, event):
        self.clear(); event.accept()

    def wheelEvent(self, event):
        self.clear(); event.ignore()

    def paint_content(self, painter):
        painter.drawPixmap(QPointF(self.strip_left - self.offset(), 0), self.before)


class AlbumRail(QScrollArea):
    def __init__(self):
        super().__init__()
        self.transition = RailTransition(self)
        self.horizontalScrollBar().actionTriggered.connect(lambda *_: self.transition.clear())

    def wheelEvent(self, event):
        self.transition.clear()
        if not event.angleDelta().x() and not event.pixelDelta().x() and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            event.ignore(); return
        super().wheelEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.prepare_transition)

    def prepare_transition(self):
        if self.transition.clock.isValid(): return
        if not self.transition.isValid():
            self.transition.setGeometry(self.rect()); self.transition.show(); self.transition.lower()
            self.transition.grabFramebuffer(); self.transition.hide()

    def scroll_page(self, direction):
        bar = self.horizontalScrollBar(); transition = self.transition
        current = transition.offset() if transition.clock.isValid() else bar.value()
        target = max(bar.minimum(), min(bar.maximum(), current + direction * self.viewport().width() * .8))
        transition.clear()
        if abs(target - current) < .5: return
        left = int(min(current, target)); right = min(self.widget().width(), int(max(current, target) + self.viewport().width() + 1))
        strip = capture_content(self.widget(), QRect(left, 0, right - left, self.widget().height()))
        transition.from_offset, transition.to_offset, transition.strip_left = current, target, left
        transition.start(strip, QPixmap())
        if not transition.clock.isValid(): bar.setValue(round(target))

    def resizeEvent(self, event):
        self.transition.clear(); super().resizeEvent(event)

    def hideEvent(self, event):
        self.transition.clear(); super().hideEvent(event)


class RoundedRowDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        table = self.parent()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        color = "#4b343f" if selected else "#333337" if index.row() == table.hover_row else "#262629" if index.row() % 2 == 0 else "#202022"
        painter.save()
        painter.setClipRect(option.rect, Qt.ClipOperation.IntersectClip)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(color))
        # Each cell clips the same row shape, so internal column joins stay flat.
        rect = QRectF(0, option.rect.y(), table.viewport().width(), option.rect.height()).adjusted(2, 2, -2, -2)
        painter.drawRoundedRect(rect, 6, 6)
        painter.restore()
        content = QStyleOptionViewItem(option); self.initStyleOption(content, index)
        content.state &= ~(QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver | QStyle.StateFlag.State_HasFocus)
        content.features &= ~QStyleOptionViewItem.ViewItemFeature.Alternate
        content.backgroundBrush = QBrush(Qt.BrushStyle.NoBrush)
        if selected: content.palette.setColor(QPalette.ColorRole.Text, QColor("white"))
        table.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, content, painter, table)


class TableSurface(QTableWidget):
    """Clip the whole table, including headers, scrollbars and cell widgets."""
    def resizeEvent(self, event):
        super().resizeEvent(event)
        outline = QPainterPath(); outline.addRoundedRect(QRectF(self.rect()), 10, 10)
        self.setMask(QRegion(outline.toFillPolygon().toPolygon()))


class RoundedTable(TableSurface):
    def __init__(self, rows, columns, parent=None):
        super().__init__(rows, columns, parent)
        self.smooth_wheel = SmoothWheel(self)
        self.hover_row = -1
        self.setItemDelegate(RoundedRowDelegate(self))
        self.setMouseTracking(True)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover)

    def set_hover_row(self, row):
        if row == self.hover_row: return
        previous, self.hover_row = self.hover_row, row
        for changed in (previous, row):
            if 0 <= changed < self.rowCount():
                self.viewport().update(0, self.rowViewportPosition(changed), self.viewport().width(), self.rowHeight(changed))

    def viewportEvent(self, event):
        if event.type() in (QEvent.Type.MouseMove, QEvent.Type.HoverMove):
            self.set_hover_row(self.indexAt(event.position().toPoint()).row())
        elif event.type() in (QEvent.Type.Leave, QEvent.Type.HoverLeave):
            self.set_hover_row(-1)
        return super().viewportEvent(event)

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        if self.hover_row >= 0:
            self.set_hover_row(self.indexAt(self.viewport().mapFromGlobal(QCursor.pos())).row())


def cover_brand_style(image):
    """Choose stable ink from the actual badge background, including hover tint."""
    from PIL import Image
    image = image.convertToFormat(QImage.Format.Format_RGB888)
    pixels = Image.frombytes("RGB", (image.width(), image.height()), bytes(image.constBits()), "raw", "RGB", image.bytesPerLine())
    linear = [round(255 * (v / 3294.6 if v <= 10 else ((v / 255 + .055) / 1.055) ** 2.4)) for v in range(256)]
    histogram = pixels.point(linear * 3).convert("L", (.2126, .7152, .0722, 0)).histogram()
    mean = sum(i * count for i, count in enumerate(histogram)) / (255 * image.width() * image.height())
    dark = (mean + .05) / .05 >= 1.05 / (mean + .05)
    if dark:
        lowest = next(i for i, count in enumerate(histogram) if count) / 255
        contrast = (lowest + .05) / .05
    else:
        hovered = pixels.point([round(v * 240 / 255 + 15) for v in range(256)] * 3)
        highest = hovered.point(linear * 3).convert("L", (.2126, .7152, .0722, 0)).getextrema()[1] / 255
        contrast = 1.05 / (highest + .05)
    # Leave a small margin for the 8-bit luminance histogram's rounding.
    backing = (QColor(255, 255, 255, 180) if dark else QColor(0, 0, 0, 180)) if contrast < 4.6 else None
    return ("#000000" if dark else "#ffffff"), backing


class FeatureCard(BlurPanel):
    clicked = Signal()

    def __init__(self, title, artist, source, width=205):
        super().__init__(base="#35313a", tint=1, radius=10)
        self.set_source(source); self.original = load_cover(source)
        self.sharp = QPixmap(); self.sharp_key = None
        self.brand_key = None; self.brand_backing = None
        self.setFixedSize(width, int(width * 1.34)); self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{title}\n{artist} · 查看专辑")
        self.hovered = False
        layout = QVBoxLayout(self); layout.setContentsMargins(15, 15, 15, 15); layout.setSpacing(4)
        self.brand_icon = IconLabel("note", "#ffffff", 15); self.brand_text = label(APP_NAME, 9, True, "#ffffff")
        top = QHBoxLayout(); top.addStretch(); top.setSpacing(3); top.addWidget(self.brand_icon); top.addWidget(self.brand_text); layout.addLayout(top); layout.addStretch()
        layout.addWidget(label("资料库精选", 9, True, "#ddddE3"))
        name = label(title, 11, True); name.setWordWrap(True); name.setMaximumHeight(42); layout.addWidget(name)
        artist_label = label(artist, 10, color="#ededf1"); artist_label.setText(artist_label.fontMetrics().elidedText(artist, Qt.TextElideMode.ElideRight, width - 30)); layout.addWidget(artist_label)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath(); path.addRoundedRect(QRectF(self.rect()), 10, 10); p.setClipPath(path)
        # Cache the faded cover at physical resolution, including fractional DPI.
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), dpr, self.original.cacheKey())
        if self.sharp_key != key:
            self.sharp = QPixmap(self.size() * dpr); self.sharp.setDevicePixelRatio(dpr); self.sharp.fill(Qt.GlobalColor.transparent)
            layer = QPainter(self.sharp); layer.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            if not self.original.isNull():
                cover = self.original.scaled(QSize(self.width(), self.width()) * dpr, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                cover.setDevicePixelRatio(dpr)
                layer.setClipRect(QRectF(0, 0, self.width(), self.width()))
                size = cover.deviceIndependentSize()
                layer.drawPixmap(QPointF((self.width() - size.width()) / 2, (self.width() - size.height()) / 2), cover)
                layer.setClipping(False)
            layer.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            mask = QLinearGradient(0, 0, 0, self.height()); mask.setColorAt(0, QColor(255, 255, 255)); mask.setColorAt(.5, QColor(255, 255, 255)); mask.setColorAt(.80, QColor(255, 255, 255, 0)); layer.fillRect(self.rect(), mask); layer.end()
            self.sharp_key = key
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform); p.drawPixmap(0, 0, self.sharp)
        shade = QLinearGradient(0, 0, 0, self.height()); shade.setColorAt(0, QColor(0, 0, 0, 16)); shade.setColorAt(.45, QColor(0, 0, 0, 0)); shade.setColorAt(1, QColor(0, 0, 0, 140)); p.fillRect(self.rect(), shade)
        if self.hovered: p.fillRect(self.rect(), QColor(255, 255, 255, 15))
        brand_area = self.brand_icon.geometry().united(self.brand_text.geometry()).adjusted(-5, -3, 5, 3)
        brand_key = (key, brand_area.getRect(), self.backdrop.cacheKey(), self.base, self.tint)
        if self.brand_key != brand_key:
            # Reproduce only this small patch; never grab the widget recursively.
            sample = QImage(brand_area.size() * dpr, QImage.Format.Format_RGB32); sample.setDevicePixelRatio(dpr); sample.fill(QColor(self.base))
            patch = QPainter(sample); patch.translate(-brand_area.x(), -brand_area.y())
            patch.setOpacity(self.tint); draw_cover(patch, self.backdrop, QRectF(self.rect())); patch.setOpacity(1)
            patch.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform); patch.drawPixmap(0, 0, self.sharp)
            patch.fillRect(self.rect(), shade); patch.end()
            ink, self.brand_backing = cover_brand_style(sample)
            self.brand_icon.symbol = icon("note", ink, 15); self.brand_icon.update()
            self.brand_text.setStyleSheet(f"font-size:9pt;font-weight:700;color:{ink};background:transparent;")
            self.brand_key = brand_key
        if self.brand_backing:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(self.brand_backing); p.drawRoundedRect(QRectF(brand_area), 5, 5)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 10, 10); p.end()

    def enterEvent(self, event): self.hovered = True; self.update(); super().enterEvent(event)
    def leaveEvent(self, event): self.hovered = False; self.update(); super().leaveEvent(event)
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton: self.clicked.emit()
        super().mouseReleaseEvent(event)


class Cover(QWidget):
    def __init__(self, source="", size=180, radius=9, parent=None):
        super().__init__(parent)
        self.pixmap = load_cover(source)
        self.scaled = QPixmap(); self.scaled_key = None
        self.radius = radius
        self.setFixedSize(size, size)

    def set_source(self, source):
        self.pixmap = load_cover(source); self.update()

    def set_data(self, data):
        self.pixmap.loadFromData(data); self.update()

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath(); path.addRoundedRect(QRectF(self.rect()), self.radius, self.radius); p.setClipPath(path)
        if not self.pixmap.isNull():
            dpr = self.devicePixelRatioF()
            key = (self.pixmap.cacheKey(), self.width(), self.height(), dpr)
            if self.scaled_key != key:
                self.scaled = self.pixmap.scaled(self.size() * dpr, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                self.scaled.setDevicePixelRatio(dpr); self.scaled_key = key
            w, h = self.scaled.width() / dpr, self.scaled.height() / dpr
            p.drawPixmap(int((self.width() - w) / 2), int((self.height() - h) / 2), self.scaled)
        else:
            gradient = QLinearGradient(0, 0, self.width(), self.height()); gradient.setColorAt(0, QColor("#f9c4c9")); gradient.setColorAt(1, QColor("#ec667d")); p.fillRect(self.rect(), gradient)
            icon("note", "#ffffff", int(self.width() * .38)).paint(p, int(self.width() * .31), int(self.height() * .3), int(self.width() * .38), int(self.height() * .38))
        p.end()


class AlbumCard(QFrame):
    clicked = Signal()

    def __init__(self, title, artist, cover="", size=180):
        super().__init__()
        self.setFixedWidth(size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 6); layout.setSpacing(5)
        self.cover = Cover(cover, size)
        layout.addWidget(self.cover)
        self.title = label(title, 10)
        self.title.setFixedWidth(size); self.title.setToolTip(title)
        metrics = self.title.fontMetrics(); self.title.setText(metrics.elidedText(title, Qt.TextElideMode.ElideRight, size))
        layout.addWidget(self.title)
        artist_label = label(artist, 9, color="#a0a0a8")
        artist_label.setFixedWidth(size); artist_label.setText(artist_label.fontMetrics().elidedText(artist, Qt.TextElideMode.ElideRight, size))
        layout.addWidget(artist_label)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


STYLE = """
QMainWindow, QDialog { background:#202022; }
QWidget { color:#eeeeF2; font-family:'Microsoft YaHei UI','Segoe UI'; font-size:13px; }
QLabel { background:transparent; }
QFrame#sidebar { border-right:1px solid #35353a; }
QFrame#player { border-bottom:1px solid #39393d; }
QFrame#hero { border-radius:10px; }
QPushButton { background:#333337; border:0; border-radius:6px; padding:7px 12px; font-weight:400; }
QPushButton:hover { background:#414146; }
QPushButton:pressed { background:#4a4a50; }
QPushButton:disabled { color:#666670; background:#29292d; }
QPushButton[primary=true] { background:#fa4164; color:white; }
QPushButton[primary=true]:hover { background:#ff5979; }
QPushButton[nav=true] { text-align:left; background:transparent; border-radius:5px; padding:7px 10px; font-weight:400; border-left:3px solid transparent; }
QPushButton[nav=true]:hover { background:#303034; }
QPushButton[nav=true]:checked { background:#333337; }
QPushButton[indented=true] { padding-left:30px; }
QPushButton[plain=true] { background:transparent; padding:5px; }
QPushButton[plain=true]:hover { background:rgba(255,255,255,18); }
QPushButton[plain=true]:checked { background:rgba(250,65,100,42); }
QPushButton#lyricsToggle:checked { background:#fa4164; }
QFrame#player QPushButton { padding:0; }
QPushButton[accent=true] { color:#fa5577; background:transparent; }
QLineEdit, QComboBox, QSpinBox, QTextEdit { background:#2c2c31; border:1px solid #424248; border-radius:5px; padding:8px 10px; selection-background-color:#bd3655; }
QLineEdit:focus, QTextEdit:focus { border:1px solid #fa4164; }
QLineEdit#sidebarSearch { background:#2c2c30; border:0; border-bottom:1px solid #67676c; padding:7px 9px; }
QComboBox::drop-down { border:0; width:28px; }
QComboBox QAbstractItemView { background:#303036; color:#eeeeF3; selection-background-color:#4a3a43; border:1px solid #515158; }
QScrollArea, QScrollArea > QWidget > QWidget { border:0; background:transparent; }
QScrollBar:vertical { width:8px; background:transparent; margin:3px; }
QScrollBar::handle:vertical { background:#616168; min-height:30px; border-radius:3px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }
QScrollBar:horizontal { height:7px; background:transparent; }
QScrollBar::handle:horizontal { background:#55555c; min-width:30px; border-radius:3px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background:transparent; }
QTableWidget { background:#202022; border:0; border-radius:10px; selection-background-color:transparent; selection-color:white; outline:0; }
QTableWidget::item { padding:8px; border:0; background:transparent; }
QHeaderView::section { background:#202022; color:#a0a0a9; border:0; border-bottom:1px solid #3a3a40; padding:9px 8px; text-align:left; font-weight:400; }
QSlider::groove:horizontal { height:3px; background:#55555c; border-radius:1px; }
QSlider::sub-page:horizontal { background:#c4c4cb; border-radius:1px; }
QSlider::handle:horizontal { background:#e8e8ed; width:8px; margin:-3px 0; border-radius:4px; }
QPlainTextEdit { background:#19191c; border:1px solid #3a3a40; border-radius:7px; padding:8px; font-family:Consolas; font-size:12px; }
QMenu { background:#303036; border:1px solid #4a4a50; padding:5px; }
QMenu::item { padding:7px 20px; border-radius:3px; }
QMenu::item:selected { background:#4a3a43; }
QToolTip { background:#3c3c43; color:white; border:1px solid #55555c; padding:6px; }
"""
STYLE += 'QComboBox::down-arrow { image:url("' + (Path(__file__).resolve().parent.parent / 'artwork/chevron.svg').as_posix() + '"); width:10px; height:6px; }'
