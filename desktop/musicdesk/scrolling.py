"""Pixel scrolling with accumulated wheel motion; native touchpad pixels stay direct."""
import math

from PySide6.QtCore import QObject, QEvent, QElapsedTimer, QTimer, Qt, QVariantAnimation, QEasingCurve, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPolygonF, QCursor
from PySide6.QtWidgets import QApplication, QScrollArea, QAbstractItemView, QScrollBar, QStyle, QStyleOptionSlider


class HoverScrollBar(QScrollBar):
    """Reveal the rail without changing the viewport or native scroll behavior."""
    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Vertical, parent)
        self.reveal = 0.0; self.pressed = False
        self.setFixedWidth(12); self.setMouseTracking(True)
        # Keep hit testing, dragging and arrow repeat in QScrollBar. The style
        # defines fixed geometry; only our painting changes during the reveal.
        self.setStyleSheet("""
            QScrollBar:vertical { width:12px; margin:14px 0; background:transparent; }
            QScrollBar::handle:vertical { min-height:30px; background:transparent; }
            QScrollBar::sub-line:vertical { height:14px; subcontrol-origin:margin; subcontrol-position:top; }
            QScrollBar::add-line:vertical { height:14px; subcontrol-origin:margin; subcontrol-position:bottom; }
        """)
        self.hide_delay = QTimer(self); self.hide_delay.setSingleShot(True); self.hide_delay.setInterval(800)
        self.hide_delay.timeout.connect(lambda: self.animate(False))
        self.animation = QVariantAnimation(self); self.animation.setDuration(180)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self.set_reveal)

    def set_reveal(self, value):
        self.reveal = value; self.update()

    def animate(self, expanded):
        if expanded: self.hide_delay.stop()
        self.animation.stop(); self.animation.setStartValue(self.reveal)
        self.animation.setEndValue(1.0 if expanded else 0.0); self.animation.start()

    def enterEvent(self, event):
        self.animate(True); super().enterEvent(event)

    def leaveEvent(self, event):
        if not self.pressed: self.hide_delay.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.pressed = True; self.animate(True)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event); self.update()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.pressed = False
            if not self.underMouse(): self.hide_delay.start()

    def hideEvent(self, event):
        self.hide_delay.stop(); self.animation.stop(); self.reveal = 0.0; self.pressed = False
        super().hideEvent(event)

    def paintEvent(self, event):
        option = QStyleOptionSlider(); self.initStyleOption(option)
        control = QStyle.ComplexControl.CC_ScrollBar; sub = QStyle.SubControl
        thumb = self.style().subControlRect(control, option, sub.SC_ScrollBarSlider, self)
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(57, 57, 61, round(220 * self.reveal)))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, 0, -.5, 0), 3, 3)
        width = 2 + 4 * self.reveal
        center = self.width() - 3 - (self.width() / 2 - 3) * self.reveal
        shade = round(116 + 66 * self.reveal)
        painter.setBrush(QColor(shade, shade, shade + 4))
        painter.drawRoundedRect(QRectF(center - width / 2, thumb.y(), width, thumb.height()), width / 2, width / 2)
        cursor = self.mapFromGlobal(QCursor.pos())
        for part, direction, enabled in ((sub.SC_ScrollBarSubLine, -1, self.value() > self.minimum()), (sub.SC_ScrollBarAddLine, 1, self.value() < self.maximum())):
            rect = self.style().subControlRect(control, option, part, self)
            x, y = QRectF(rect).center().x(), QRectF(rect).center().y()
            shade = (224 if rect.contains(cursor) else 172) if enabled else 96
            painter.setBrush(QColor(shade, shade, shade + 4, round(255 * self.reveal)))
            painter.drawPolygon(QPolygonF([QPointF(x - 2.5, y - direction * 1.5), QPointF(x + 2.5, y - direction * 1.5), QPointF(x, y + direction * 1.5)]))
        painter.end()


class SmoothWheel(QObject):
    def __init__(self, area):
        super().__init__(area)
        self.area = area
        if not isinstance(area.verticalScrollBar(), HoverScrollBar): area.setVerticalScrollBar(HoverScrollBar(area))
        self.bar = None
        self.position = self.target = 0.0
        self.writing = False
        self.clock = QElapsedTimer()
        self.timer = QTimer(self); self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(8); self.timer.timeout.connect(self.advance)
        if isinstance(area, QAbstractItemView):
            area.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            area.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        area.installEventFilter(self)
        area.viewport().installEventFilter(self)
        for bar in (area.verticalScrollBar(), area.horizontalScrollBar()):
            bar.installEventFilter(self)
            bar.valueChanged.connect(self.external_change)
            bar.rangeChanged.connect(self.stop)
            bar.sliderPressed.connect(self.stop)

    def stop(self, *_):
        self.timer.stop()

    def external_change(self, *_):
        if not self.writing: self.stop()

    def write(self, value):
        self.writing = True
        try: self.bar.setValue(round(value))
        finally: self.writing = False

    def advance(self):
        seconds = min(.05, self.clock.nsecsElapsed() / 1e9); self.clock.restart()
        self.position += (self.target - self.position) * (1 - math.exp(-seconds / .055))
        if abs(self.target - self.position) < .5:
            self.position = self.target; self.stop()
        self.write(self.position)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Hide, QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress):
            self.stop()
        if event.type() != QEvent.Type.Wheel: return False
        # Leave modified zoom gestures to the owning control.
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier: return False
        pixels, angles = event.pixelDelta(), event.angleDelta()
        horizontal = abs(angles.x()) > abs(angles.y()) or abs(pixels.x()) > abs(pixels.y()) or bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        bar = self.area.horizontalScrollBar() if horizontal else self.area.verticalScrollBar()
        delta = pixels.x() if horizontal and pixels.x() else pixels.y()
        direct = not pixels.isNull()
        if not direct:
            angle = angles.x() if horizontal and angles.x() else angles.y()
            distance = min(bar.pageStep(), QApplication.wheelScrollLines() * self.area.fontMetrics().height())
            delta = angle / 120 * distance
        if not delta:
            event.ignore(); return True
        current = self.position if self.timer.isActive() and self.bar is bar else float(bar.value())
        # Reverse immediately instead of spending the next gesture finishing old motion.
        base = self.target if not direct and self.timer.isActive() and self.bar is bar and (self.target - current) * delta < 0 else current
        target = max(bar.minimum(), min(bar.maximum(), base - delta))
        if target == current:
            event.ignore(); return True  # Allow an enclosing page to consume the wheel.
        self.bar, self.position, self.target = bar, current, target
        if direct:
            self.stop(); self.position = target; self.write(target)
        elif not self.timer.isActive():
            # Match the screen instead of capping high-refresh displays at 125 Hz.
            refresh = self.area.screen().refreshRate() or 60
            self.timer.setInterval(max(4, round(1000 / refresh)))
            self.clock.start(); self.timer.start()
        event.accept(); return True


class SmoothScrollArea(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.smooth_wheel = SmoothWheel(self)
