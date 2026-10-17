import re
from bisect import bisect_right
from pathlib import Path

from PySide6.QtCore import Qt, QEvent, QRectF, QPoint, QPointF, QTimer, QElapsedTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap, QRegion, QPen, QTextDocument, QTextCursor, QTextCharFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout, QVBoxLayout, QSizePolicy

from .widgets import BlurPanel, PageTransition, draw_cover, label, reflow_items, paint_reflow
from .scrolling import SmoothScrollArea


def lyric_lines(text):
    """Return display lines and optional LRC timestamps in milliseconds."""
    timed, plain = [], []
    offset = re.search(r"\[offset:([+-]?\d+)\]", text, re.I)
    offset = int(offset[1]) if offset else 0
    for line in text.splitlines():
        stamps = re.findall(r"\[(\d+):(\d{2}(?:\.\d+)?)\]", line)
        content = re.sub(r"\[[^\]]*\]|<\d+:\d+(?:\.\d+)?>", "", line).strip()
        if stamps:
            for minutes, seconds in stamps:
                timed.append((max(0, round((int(minutes) * 60 + float(seconds)) * 1000) + offset), content or "•••"))
        elif content:
            plain.append(content)
    if timed:
        timed.sort(key=lambda item: item[0])
        # Translations at the same timestamp belong to the same displayed line.
        grouped = {}
        for stamp, content in timed: grouped.setdefault(stamp, []).append(content)
        return [(stamp, "\n".join(lines)) for stamp, lines in grouped.items()]
    return [(None, line) for line in plain]


class LyricLabel(QLabel):
    """Add a small same-color outline to the installed bold font's glyphs."""
    def __init__(self, text, color):
        super().__init__(text)
        self.setStyleSheet(f"font-size:15pt;font-weight:700;color:{color};background:transparent;")
        self.document = None; self.document_key = None

    def paintEvent(self, event):
        color = self.palette().color(self.foregroundRole())
        key = (self.text(), self.font().toString(), self.width(), color.rgba())
        if self.document_key != key:
            self.document = QTextDocument(); self.document.setDocumentMargin(0)
            self.document.setDefaultFont(self.font()); self.document.setPlainText(self.text())
            self.document.setTextWidth(self.contentsRect().width())
            cursor = QTextCursor(self.document); cursor.select(QTextCursor.SelectionType.Document)
            style = QTextCharFormat(); style.setForeground(color)
            style.setTextOutline(QPen(color, .45, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            cursor.mergeCharFormat(style); self.document_key = key
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.translate(self.contentsRect().x(), (self.height() - self.document.size().height()) / 2)
        self.document.drawContents(painter); painter.end()


class LyricScrollSurface(QOpenGLWidget):
    """Composite visible lyric rows at fractional positions on display swaps."""
    def __init__(self, panel):
        super().__init__(panel)
        self.panel, self.rows = panel, {}
        self.painted_offset = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.frameSwapped.connect(panel.advance_scroll)
        self.hide()

    def paintGL(self):
        panel = self.panel
        self.painted_offset = panel.scroll_offset
        panel.prepare_background()
        visible, positions = {}, []
        for index, line in enumerate(panel.lines):
            y = line.y() - panel.scroll_offset
            if y + line.height() < 0 or y > self.height(): continue
            key = (index, index == panel.active, line.size().width(), line.size().height(), self.devicePixelRatioF())
            pixels = self.rows.get(key)
            if pixels is None:
                pixels = QPixmap(line.size() * self.devicePixelRatioF())
                pixels.setDevicePixelRatio(self.devicePixelRatioF()); pixels.fill(Qt.GlobalColor.transparent)
                line.render(pixels, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
            visible[key] = pixels
            positions.append((QPointF(line.x(), y), pixels))
        # Finish widget rasterization before starting the OpenGL paint engine.
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(-self.x(), -self.y(), panel.background)
        for position, pixels in positions: painter.drawPixmap(position, pixels)
        painter.end()
        # Bound textures to the viewport, including for long lyrics and large seeks.
        self.rows = visible


class LyricsPanel(BlurPanel):
    seek_requested = Signal(int)

    def __init__(self):
        super().__init__(base="#2b2b2e", tint=.07)
        self.setObjectName("lyricsPanel")
        self.setAccessibleName("歌词侧栏")
        self.background = QPixmap(); self.background_key = None
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        layout = QVBoxLayout(self); layout.setContentsMargins(1, 0, 0, 0)
        self.scroll = SmoothScrollArea(); self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.scroll)
        self.scroll_clock = QElapsedTimer()
        self.scroll_timer = QTimer(self); self.scroll_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.scroll_timer.timeout.connect(self.advance_scroll)
        self.scroll_start = self.scroll_target = self.scroll_offset = 0
        self.surface = LyricScrollSurface(self)
        self.scroll.viewport().installEventFilter(self)
        self.scroll.verticalScrollBar().sliderPressed.connect(self.stop_scroll)
        self.scroll.verticalScrollBar().actionTriggered.connect(self.stop_scroll)
        self.lines, self.times, self.active = [], [], -1
        self.set_track("")

    def set_track(self, path, cover=""):
        self.stop_scroll(); self.scroll_offset = 0
        self.pressed_line = None
        self.set_source(cover)
        source = Path(path).with_suffix(".lrc") if path else None
        try:
            rows = lyric_lines(source.read_text(encoding="utf-8-sig", errors="replace")) if source and source.is_file() else []
        except OSError:
            rows = []
        body = QWidget(); layout = QVBoxLayout(body); layout.setContentsMargins(20, 20, 18, 32); layout.setSpacing(24)
        self.lines, self.times, self.active = [], [], -1
        for stamp, content in rows:
            line = LyricLabel(content, "#858589" if stamp is not None else "#dedee0")
            line.setTextFormat(Qt.TextFormat.PlainText); line.setWordWrap(True)
            policy = line.sizePolicy(); policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored); line.setSizePolicy(policy)
            self.lines.append(line); layout.addWidget(line)
            if stamp is not None:
                self.times.append(stamp); line.setProperty("timestamp", stamp)
                line.setCursor(Qt.CursorShape.PointingHandCursor); line.setToolTip("点击跳转到这句")
                line.installEventFilter(self)
        if not rows:
            hint = label("这首歌暂无歌词" if path else "播放音乐后在这里查看歌词", 14, True, "#a0a0a8")
            hint.setWordWrap(True); layout.addWidget(hint)
        layout.addStretch()
        self.scroll.setWidget(body)

    def eventFilter(self, watched, event):
        if event.type() not in {QEvent.Type.Wheel, QEvent.Type.Resize, QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease}:
            return super().eventFilter(watched, event)
        if watched is self.scroll.viewport():
            if event.type() == QEvent.Type.Wheel or event.type() == QEvent.Type.Resize and event.size().height() != event.oldSize().height():
                self.stop_scroll()
            return super().eventFilter(watched, event)
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self.stop_scroll()
            self.pressed_line = watched; return True
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            pressed, self.pressed_line = self.pressed_line, None
            if pressed is watched and watched.rect().contains(event.position().toPoint()):
                self.seek_requested.emit(watched.property("timestamp"))
            return True
        return super().eventFilter(watched, event)

    def scroll_to(self, target, animate=True):
        self.scroll.smooth_wheel.stop()
        bar = self.scroll.verticalScrollBar()
        target = max(bar.minimum(), min(target, bar.maximum()))
        if animate and self.is_scrolling() and target == self.scroll_target: return
        start = self.surface.painted_offset if self.is_scrolling() and self.surface.isVisible() else bar.value()
        self.scroll_timer.stop()
        if not animate or target == bar.value():
            self.stop_scroll(); self.scroll_offset = target; bar.setValue(target); return
        self.scroll_start, self.scroll_target, self.scroll_offset = start, target, start
        viewport = self.scroll.viewport()
        self.surface.setGeometry(QRectF(viewport.mapTo(self, QPoint()), viewport.size()).toRect())
        self.surface.show(); self.surface.raise_(); self.surface.repaint()
        self.scroll_clock.start()
        if self.surface.isValid():
            self.surface.update()
        else:
            self.surface.hide()
            self.scroll_timer.start(max(1, round(1000 / (self.screen().refreshRate() or 60))))

    def is_scrolling(self):
        return self.scroll_clock.isValid()

    def stop_scroll(self):
        self.scroll_timer.stop(); self.scroll_clock.invalidate()
        self.surface.hide(); self.surface.rows.clear()

    def advance_scroll(self):
        if not self.is_scrolling(): return
        viewport = self.scroll.viewport(); bar = self.scroll.verticalScrollBar()
        if self.surface.isVisible() and self.surface.size() != viewport.size():
            # A newly visible scrollbar narrows wrapped lyrics; keep the animation.
            self.surface.setGeometry(QRectF(viewport.mapTo(self, QPoint()), viewport.size()).toRect())
            if self.active >= 0:
                self.scroll_target = max(0, min(bar.maximum(), self.lines[self.active].y() - viewport.height() // 3))
        progress = min(1., self.scroll_clock.nsecsElapsed() / 380_000_000)
        eased = 1 - (1 - progress) ** 3
        self.scroll_offset = self.scroll_start + (self.scroll_target - self.scroll_start) * eased
        if progress == 1:
            bar.setValue(self.scroll_target); self.stop_scroll()
        elif self.surface.isVisible():
            # Mouse hit testing follows the frame just submitted, not the next one.
            bar.setValue(round(self.surface.painted_offset)); self.surface.update()
        else: bar.setValue(round(self.scroll_offset))

    def set_position(self, position, follow=False, force=False):
        index = bisect_right(self.times, position) - 1
        if index == self.active and not follow and not force: return
        if self.active >= 0: self.lines[self.active].setStyleSheet("color:#858589; font-size:15pt; font-weight:700;")
        self.active = index
        if index < 0:
            if self.isVisible() and self.times: self.scroll_to(0, animate=not follow)
            return
        line = self.lines[index]; line.setStyleSheet("color:#f2f2f5; font-size:15pt; font-weight:700;")
        if self.isVisible():
            self.scroll.widget().layout().activate()
            # Opening/resizing aligns before the sidebar snapshot; playback scrolls.
            self.scroll_to(line.y() - self.scroll.viewport().height() // 3, animate=not follow)

    def hideEvent(self, event):
        self.stop_scroll()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event); QTimer.singleShot(0, self.prepare_surface)

    def prepare_surface(self):
        if self.isVisible() and not self.surface.isValid():
            viewport = self.scroll.viewport()
            self.surface.setGeometry(QRectF(viewport.mapTo(self, QPoint()), viewport.size()).toRect())
            self.surface.show(); self.surface.lower(); self.surface.grabFramebuffer(); self.surface.hide()

    def prepare_background(self):
        key = (self.size(), self.devicePixelRatioF(), self.backdrop.cacheKey())
        if key != self.background_key:
            self.background_key = key
            self.background = QPixmap(self.size() * self.devicePixelRatioF())
            self.background.setDevicePixelRatio(self.devicePixelRatioF()); self.background.fill(QColor(self.base))
            painter = QPainter(self.background); painter.setOpacity(self.tint)
            draw_cover(painter, self.backdrop, QRectF(self.rect())); painter.setOpacity(1)
            painter.fillRect(0, 0, 1, self.height(), QColor("#39393d")); painter.end()

    def paintEvent(self, event):
        self.prepare_background()
        painter = QPainter(self); painter.drawPixmap(0, 0, self.background); painter.end()


class LyricsTransition(PageTransition):
    """Reflow the cached main page in step with the sliding lyric sidebar."""
    finished = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.from_width = self.to_width = 0
        self.panel = QPixmap()

    def visible_width(self):
        return self.from_width + (self.to_width - self.from_width) * (1 - (1 - self.progress) ** 3)

    def clear(self):
        running = self.clock.isValid()
        super().clear(); self.panel = QPixmap()
        if running: self.finished.emit()

    def paint_content(self, painter):
        width = self.visible_width()
        eased = 1 - (1 - self.progress) ** 3
        content = QRectF(0, 0, self.width() - width, self.height())
        painter.save(); painter.setClipRect(content)
        if self.reflow: paint_reflow(painter, reflow_items(*self.reflow, eased))
        painter.restore()
        painter.drawPixmap(QPointF(self.width() - width, 0), self.panel)


class LyricsArea(QWidget):
    def __init__(self, stack, panel):
        super().__init__()
        self.stack, self.panel, self.opened = stack, panel, False
        self.row = QHBoxLayout(self); self.row.setContentsMargins(0, 0, 0, 0); self.row.setSpacing(0)
        stack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.row.addWidget(stack, 1); self.row.addWidget(panel); panel.hide()
        self.transition = LyricsTransition(self)

    def showEvent(self, event):
        super().showEvent(event); QTimer.singleShot(0, self.prepare_transition)

    def prepare_transition(self):
        if self.transition.clock.isValid(): return
        if not self.transition.isValid():
            self.transition.setGeometry(self.rect()); self.transition.show(); self.transition.lower()
            self.transition.grabFramebuffer(); self.transition.hide()

    def set_open(self, opened, refresh):
        transition = self.transition
        if transition.isVisible() and transition.isValid():
            start_width = transition.visible_width()
            panel = transition.panel
            items = reflow_items(*transition.reflow, 1 - (1 - transition.progress) ** 3)
        else:
            start_width = self.panel.width() if self.opened else 0
            items = self.stack.capture_items()
            self.panel.stop_scroll()
            panel = self.panel.grab() if self.opened else QPixmap()
        transition.clear(); self.stack.transition.clear()
        self.stack.resize_before = QPixmap()
        self.stack.resize_items = {}
        self.opened = opened
        self.panel.setFixedWidth(min(320, max(250, self.width() // 4)))
        self.panel.setVisible(opened); self.row.activate(); refresh()
        if opened:
            self.panel.stop_scroll(); panel = self.panel.grab()
        transition.from_width, transition.to_width = start_width, self.panel.width() if opened else 0
        transition.panel = panel
        transition.start(QPixmap(), QPixmap(), reflow=(items, self.stack.capture_items()))

    def resizeEvent(self, event):
        self.transition.clear()
        self.panel.setFixedWidth(min(320, max(250, self.width() // 4)))
        super().resizeEvent(event)
