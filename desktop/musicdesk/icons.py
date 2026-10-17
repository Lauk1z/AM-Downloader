"""MusicDesk control glyphs, redrawn from the supplied Windows Music reference."""
from functools import lru_cache
from pathlib import Path
from PySide6.QtCore import Qt, QRectF, QSize, QLineF
from PySide6.QtGui import QColor, QIcon, QIconEngine, QPainter, QPainterPath, QPen, QPixmap, QPixmapCache
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget


@lru_cache(maxsize=1)
def app_icon_renderer():
    return QSvgRenderer(str(Path(__file__).resolve().parent.parent / "artwork/am-dowloader-icon.svg"))


def draw_icon(p, name, color, rect):
    p.save()
    side = min(rect.width(), rect.height())
    p.translate(rect.center().x() - side / 2, rect.center().y() - side / 2)
    p.scale(side / 24, side / 24)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    ink = QColor(color)
    player = name.startswith("player_")
    if player: name = name.removeprefix("player_")
    if player and name == "star": name = "star_fill"
    p.setPen(QPen(ink, 2.35 if player else 1.65, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)

    if name == "app":
        app_icon_renderer().render(p, QRectF(0, 0, 24, 24))
    elif name in ("note", "songs", "playlist"):
        if name == "playlist":
            for y in (6, 10, 14): p.drawLine(QLineF(2, y, 10, y))
            p.translate(10, 1); p.scale(.62, .9)
        path = QPainterPath()
        if name == "note":
            path.moveTo(9, 6); path.lineTo(20, 3.5); path.quadTo(21, 3.2, 21, 4.4)
            path.lineTo(21, 16.2); path.cubicTo(21, 20.3, 13.7, 21, 13.7, 17.6)
            path.cubicTo(13.7, 15.8, 16.4, 14.6, 19, 14.8); path.lineTo(19, 8)
            path.lineTo(10, 10); path.lineTo(10, 18.2)
            path.cubicTo(10, 22.3, 2.7, 23, 2.7, 19.6)
            path.cubicTo(2.7, 17.8, 5.4, 16.6, 8, 16.8); path.lineTo(8, 7)
            path.quadTo(8, 6.2, 9, 6)
        else:
            path.moveTo(10, 5); path.lineTo(18, 3); path.lineTo(18, 7.5); path.lineTo(12, 9)
            path.lineTo(12, 18); path.cubicTo(12, 22, 4.5, 22.8, 4.5, 19.1)
            path.cubicTo(4.5, 17.1, 7.5, 16.1, 10, 16.4)
        path.closeSubpath(); p.fillPath(path, ink)
    elif name == "home":
        path = QPainterPath(); path.moveTo(2.8, 10.2); path.lineTo(10.6, 3.7)
        path.quadTo(12, 2.5, 13.4, 3.7); path.lineTo(21.2, 10.2)
        path.moveTo(4.4, 9.2); path.lineTo(4.4, 19.6); path.quadTo(4.4, 21, 5.8, 21)
        path.lineTo(18.2, 21); path.quadTo(19.6, 21, 19.6, 19.6); path.lineTo(19.6, 9.2)
        p.drawPath(path); p.fillRect(QRectF(9.2, 13, 5.6, 8), ink)
    elif name in ("album", "library"):
        p.drawLine(QLineF(7, 3, 17, 3)); p.drawLine(QLineF(5, 6, 19, 6))
        p.drawRoundedRect(QRectF(4, 9, 16, 12), 1.8, 1.8)
        if name == "library": draw_icon(p, "note", ink, QRectF(6.5, 9.5, 11, 11))
    elif name == "artist":
        p.translate(12, 12); p.rotate(42); p.translate(-12, -12)
        p.drawRoundedRect(QRectF(8.5, 2.5, 7, 10), 3.5, 3.5)
        p.drawLine(QLineF(9, 7, 15, 7)); p.drawLine(QLineF(9.5, 9.5, 14.5, 9.5))
        path = QPainterPath(); path.moveTo(10.4, 12.2); path.lineTo(10.8, 19.8)
        path.quadTo(12, 22, 13.2, 19.8); path.lineTo(13.6, 12.2); p.drawPath(path)
    elif name == "recent":
        p.drawEllipse(QRectF(3, 3, 18, 18)); p.drawLine(QLineF(12, 6.2, 12, 12)); p.drawLine(QLineF(12, 12, 8, 12))
    elif name in ("star", "star_fill", "favourites"):
        if name == "favourites":
            p.drawRoundedRect(QRectF(3.2, 3.2, 17.6, 17.6), 2, 2)
            p.translate(4.2, 3.8); p.scale(.65, .65)
        path = QPainterPath(); path.moveTo(12, 3)
        for x, y in ((14.7, 8.6), (21, 9.5), (16.5, 14), (17.6, 20.4), (12, 17.4), (6.4, 20.4), (7.5, 14), (3, 9.5), (9.3, 8.6)):
            path.lineTo(x, y)
        path.closeSubpath()
        if name != "star": p.fillPath(path, ink)
        else: p.drawPath(path)
    elif name in ("play", "next", "prev"):
        if name == "prev": p.translate(24, 0); p.scale(-1, 1)
        triangles = ((7, 20, 3.5, 20.5),) if name == "play" else ((2.5, 12.2, 5, 19), (12, 21.7, 5, 19))
        if player: triangles = ((5.5, 21, 2.5, 21.5),) if name == "play" else ((1.5, 12.6, 5, 19), (11.4, 22.5, 5, 19))
        radius = 1.7 if player else 1.3
        for left, right, top, bottom in triangles:
            path = QPainterPath(); path.moveTo(left + radius, top + .2)
            tip, half, corner = (1, 1.2, radius) if player else (.7, 1, 1)
            path.lineTo(right - tip, 12 - half); path.quadTo(right + .6, 12, right - tip, 12 + half)
            path.lineTo(left + radius, bottom - .2); path.quadTo(left, bottom + .6, left, bottom - corner)
            path.lineTo(left, top + corner); path.quadTo(left, top - .6, left + radius, top + .2)
            p.fillPath(path, ink)
    elif name == "pause":
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(ink)
        for x in (6, 14): p.drawRoundedRect(QRectF(x, 4, 4.5 if player else 4, 16), 1.2 if player else .8, 1.2 if player else .8)
    elif name == "shuffle":
        path = QPainterPath(); path.moveTo(3, 6); path.lineTo(5, 6)
        path.cubicTo(10, 6, 13, 18, 18, 18); path.lineTo(21, 18)
        path.moveTo(3, 18); path.lineTo(5, 18); path.cubicTo(7.2, 18, 8.8, 15.7, 10.2, 13.7)
        path.moveTo(13.8, 10.3); path.cubicTo(15.2, 8.3, 16.7, 6, 18, 6); path.lineTo(21, 6)
        for y in (6, 18):
            path.moveTo(18, y - 3); path.lineTo(21, y); path.lineTo(18, y + 3)
        p.drawPath(path)
    elif name == "repeat":
        path = QPainterPath(); path.moveTo(3, 13); path.lineTo(3, 10)
        path.quadTo(3, 6, 7, 6); path.lineTo(20, 6); path.moveTo(17, 3); path.lineTo(20, 6); path.lineTo(17, 9)
        path.moveTo(21, 11); path.lineTo(21, 14); path.quadTo(21, 18, 17, 18)
        path.lineTo(4, 18); path.moveTo(7, 15); path.lineTo(4, 18); path.lineTo(7, 21); p.drawPath(path)
    elif name in ("volume", "volume_low", "volume_medium", "volume_high"):
        if name != "volume": p.translate(-2, 0); p.scale(.85, 1)
        path = QPainterPath(); path.moveTo(6, 9); path.lineTo(9, 9); path.lineTo(14.5, 4.5)
        path.lineTo(14.5, 19.5); path.lineTo(9, 15); path.lineTo(6, 15); path.closeSubpath(); p.drawPath(path)
        waves = {"volume": 0, "volume_low": 1, "volume_medium": 2, "volume_high": 3}[name]
        for rect in (QRectF(12.5, 8, 7, 8), QRectF(12.5, 4.5, 11.5, 15), QRectF(12.5, 1.5, 16, 21))[:waves]:
            p.drawArc(rect, -60 * 16, 120 * 16)
    elif name == "lyrics" and player:
        p.setPen(QPen(ink, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        path = QPainterPath(); path.moveTo(7.5, 17.5); path.lineTo(5.5, 22); path.lineTo(12, 17.5)
        path.lineTo(18.5, 17.5); path.quadTo(21, 17.5, 21, 15); path.lineTo(21, 6)
        path.quadTo(21, 3.5, 18.5, 3.5); path.lineTo(5.5, 3.5); path.quadTo(3, 3.5, 3, 6)
        path.lineTo(3, 15); path.quadTo(3, 17.5, 5.5, 17.5); path.closeSubpath(); p.drawPath(path)
        for x in (7, 13):
            quote = QPainterPath(); quote.addEllipse(QRectF(x, 7, 3.8, 3.6)); quote.addEllipse(QRectF(x + 1.2, 8.1, 1.4, 1.25)); p.fillPath(quote, ink)
            tail = QPainterPath(); tail.moveTo(x + 2.6, 9.5); tail.lineTo(x + 3.8, 9)
            tail.cubicTo(x + 3.9, 11.5, x + 1.7, 13.5, x, 13.7); tail.lineTo(x, 12.4)
            tail.quadTo(x + 2.5, 11.5, x + 2.6, 9.5); p.fillPath(tail, ink)
    elif name == "lyrics":
        path = QPainterPath(); path.moveTo(7.5, 18); path.lineTo(6, 21.5); path.lineTo(11.5, 18)
        path.lineTo(18, 18); path.quadTo(21, 18, 21, 15); path.lineTo(21, 6)
        path.quadTo(21, 3, 18, 3); path.lineTo(6, 3); path.quadTo(3, 3, 3, 6)
        path.lineTo(3, 15); path.quadTo(3, 18, 6, 18); path.closeSubpath(); p.drawPath(path)
        for x in (7, 13):
            quote = QPainterPath(); quote.addRoundedRect(QRectF(x, 7, 3.4, 3.8), .7, .7)
            quote.moveTo(x + 1.7, 10); quote.quadTo(x + 1.7, 12, x, 13)
            quote.lineTo(x + 1.2, 13); quote.quadTo(x + 3.4, 12, x + 3.4, 9); quote.closeSubpath(); p.fillPath(quote, ink)
    elif name == "queue":
        for y in (6, 12, 18):
            p.drawLine(QLineF(8, y, 21, y))
            dot = QPainterPath(); dot.addEllipse(QRectF(2.25, y - 1.25, 2.5, 2.5)); p.fillPath(dot, ink)
    elif name == "more":
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(ink)
        for x in (5, 12, 19): p.drawEllipse(QRectF(x - 1.5, 10.5, 3, 3))
    elif name == "lossless":
        p.setPen(QPen(ink, 1.35, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for offset in (0, 3.4, 6.8):
            path = QPainterPath(); path.moveTo(1.6 + offset, 13)
            path.cubicTo(3 + offset, 2.8, 5.6 + offset, 2.8, 7.9 + offset, 11.9)
            path.cubicTo(10.2 + offset, 21.2, 13.3 + offset, 21.5, 15.6 + offset, 10.5); p.drawPath(path)
    elif name == "search":
        p.drawEllipse(QRectF(4, 3.5, 12.5, 12.5)); p.drawLine(QLineF(14.7, 14.2, 20.5, 20))
    elif name == "plus":
        p.drawLine(QLineF(12, 4, 12, 20)); p.drawLine(QLineF(4, 12, 20, 12))
    elif name in ("back", "forward"):
        if name == "forward": p.translate(24, 0); p.scale(-1, 1)
        path = QPainterPath(); path.moveTo(15, 4); path.lineTo(7, 12); path.lineTo(15, 20); p.drawPath(path)
    elif name == "download":
        path = QPainterPath(); path.moveTo(12, 3); path.lineTo(12, 16)
        path.moveTo(7, 11); path.lineTo(12, 16); path.lineTo(17, 11)
        path.moveTo(4, 17); path.lineTo(4, 20); path.quadTo(4, 21, 5, 21)
        path.lineTo(19, 21); path.quadTo(20, 21, 20, 20); path.lineTo(20, 17); p.drawPath(path)
    elif name == "refresh":
        path = QPainterPath(); path.arcMoveTo(QRectF(3.8, 3.8, 16.4, 16.4), -8)
        path.arcTo(QRectF(3.8, 3.8, 16.4, 16.4), -8, -309); p.drawPath(path)
        head = QPainterPath(); head.moveTo(15.1, 7.5); head.lineTo(19.4, 3.2)
        head.quadTo(20, 2.6, 20, 3.5); head.lineTo(20, 7.5)
        head.quadTo(20, 8, 19.5, 8); head.lineTo(15.4, 8)
        head.quadTo(14.6, 8, 15.1, 7.5); p.fillPath(head, ink)
    elif name == "settings":
        # Eight rounded gear teeth around a circular hub.
        for angle in range(0, 360, 45):
            p.save(); p.translate(12, 12); p.rotate(angle)
            tooth = QPainterPath(); tooth.moveTo(-3.1, -7.1); tooth.lineTo(-2.5, -9.7)
            tooth.quadTo(-2.4, -10.3, -1.7, -10.3); tooth.lineTo(1.7, -10.3)
            tooth.quadTo(2.4, -10.3, 2.5, -9.7); tooth.lineTo(3.1, -7.1)
            p.drawPath(tooth); p.restore()
        p.drawEllipse(QRectF(8.2, 8.2, 7.6, 7.6))
    elif name == "folder":
        path = QPainterPath(); path.moveTo(3, 7); path.lineTo(3, 5); path.quadTo(3, 3.5, 4.5, 3.5)
        path.lineTo(9, 3.5); path.lineTo(12, 7); path.lineTo(19.5, 7); path.quadTo(21, 7, 21, 8.5)
        path.lineTo(21, 19); path.quadTo(21, 20.5, 19.5, 20.5); path.lineTo(4.5, 20.5)
        path.quadTo(3, 20.5, 3, 19); path.closeSubpath(); p.drawPath(path)
    elif name == "close":
        p.drawLine(QLineF(5, 5, 19, 19)); p.drawLine(QLineF(19, 5, 5, 19))
    elif name == "grid":
        for x, y in ((3, 3), (14, 3), (3, 14), (14, 14)): p.drawRoundedRect(QRectF(x, y, 7, 7), 1.3, 1.3)
    p.restore()


class MusicIconEngine(QIconEngine):
    def __init__(self, name, color):
        super().__init__(); self.name, self.color = name, color

    def clone(self):
        return MusicIconEngine(self.name, self.color)

    def iconName(self):
        return self.name

    def isNull(self):
        return False

    def paint(self, painter, rect, mode, state):
        painter.save()
        color = self.color
        if mode == QIcon.Mode.Disabled: painter.setOpacity(painter.opacity() * .35)
        elif state == QIcon.State.On and self.name.removeprefix("player_") in ("shuffle", "repeat"): color = "#fa4164"
        elif mode in (QIcon.Mode.Active, QIcon.Mode.Selected) and color != "#fa4164": color = "#ffffff"
        draw_icon(painter, self.name, color, QRectF(rect))
        painter.restore()

    def pixmap(self, size, mode, state):
        return self.scaledPixmap(size, mode, state, 1)

    def scaledPixmap(self, size, mode, state, scale):
        key = f"musicdesk:{self.name}:{self.color}:{size.width()}:{size.height()}:{mode.value}:{state.value}:{scale}"
        cached = QPixmapCache.find(key)
        if cached is not None: return cached
        result = QPixmap(max(1, round(size.width() * scale)), max(1, round(size.height() * scale)))
        result.setDevicePixelRatio(scale); result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result); self.paint(painter, QRectF(0, 0, size.width(), size.height()), mode, state); painter.end()
        QPixmapCache.insert(key, result)
        return result


def icon(name, color="#b7b7bf", size=22):
    # Size is kept for existing callers; the engine draws at the requested size/DPR.
    return QIcon(MusicIconEngine(name, color))


class IconLabel(QWidget):
    """Paint decorative glyphs directly, including after moving between monitors."""
    def __init__(self, name, color="#b7b7bf", size=22, parent=None):
        super().__init__(parent); self.symbol = icon(name, color); self.setFixedSize(QSize(size, size))

    def paintEvent(self, event):
        painter = QPainter(self); self.symbol.paint(painter, self.rect()); painter.end()
