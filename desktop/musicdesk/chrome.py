"""Player-integrated window controls with native Windows move/resize support."""
import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import Qt, QEvent, QPoint, QRectF, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QAbstractSlider, QHBoxLayout, QLineEdit, QMainWindow, QWidget, QScrollBar


class CaptionButton(QAbstractButton):
    def __init__(self, kind, text, parent):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(36, 26); self.setAccessibleName(text); self.setToolTip(text)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.underMouse() or self.isDown():
            p.fillRect(self.rect(), QColor("#c42b1c") if self.kind == "close" else QColor(255, 255, 255, 30 if self.isDown() else 18))
        p.setPen(QPen(QColor("#dedee0"), 1)); p.translate(self.width() / 2, self.height() / 2)
        if self.kind == "minimize": p.drawLine(-5, 0, 5, 0)
        elif self.kind == "close": p.drawLine(-4, -4, 4, 4); p.drawLine(-4, 4, 4, -4)
        elif self.window().isMaximized():
            p.drawLine(-2, -5, 5, -5); p.drawLine(5, -5, 5, 2)
            p.drawRoundedRect(QRectF(-5, -2, 7, 7), .6, .6)
        else: p.drawRoundedRect(QRectF(-4, -4, 8, 8), .6, .6)
        p.end()

    def enterEvent(self, event):
        super().enterEvent(event); self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event); self.update()


class AlbumWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        if sys.platform == "win32": self.setWindowFlag(Qt.WindowType.FramelessWindowHint)

    def init_chrome(self, player, now_playing, brand_icon):
        if sys.platform != "win32": return
        self.caption_player, self.caption_now_playing, self.caption_icon = player, now_playing, brand_icon
        self.window_controls = QWidget(player); self.window_controls.setObjectName("windowControls")
        self.window_controls.setFixedSize(108, 26)
        controls = QHBoxLayout(self.window_controls); controls.setContentsMargins(0, 0, 0, 0); controls.setSpacing(0)
        self.minimize_button = CaptionButton("minimize", "最小化", self.window_controls)
        self.maximize_button = CaptionButton("maximize", "最大化", self.window_controls)
        self.close_button = CaptionButton("close", "关闭", self.window_controls)
        for control in (self.minimize_button, self.maximize_button, self.close_button): controls.addWidget(control)
        margins = player.layout().contentsMargins()
        player.layout().setContentsMargins(margins.left(), margins.top(), margins.right() + self.window_controls.width(), margins.bottom())
        player.installEventFilter(self); self.position_window_controls()
        self.minimize_button.clicked.connect(self.showMinimized)
        self.maximize_button.clicked.connect(self.toggle_maximized)
        self.close_button.clicked.connect(self.close)
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        self._user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        self._user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        self._user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self._user32.IsZoomed.argtypes = [wintypes.HWND]
        self._user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        self._user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        handle = int(self.winId())
        # Retain native caption semantics and thick-frame resizing, while NCCALCSIZE
        # below removes the OS caption painting. Qt still treats the frame as zero.
        style = self._user32.GetWindowLongPtrW(handle, -16)
        self._user32.SetWindowLongPtrW(handle, -16, style | 0x00CF0000)
        self._user32.SetWindowPos(handle, None, 0, 0, 0, 0, 0x0027)
        dwm = ctypes.WinDLL("dwmapi")
        margins = (ctypes.c_int * 4)(1, 1, 1, 1)
        dwm.DwmExtendFrameIntoClientArea(wintypes.HWND(handle), ctypes.byref(margins))
        for attribute, value in ((20, 1), (33, 2)):
            setting = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(wintypes.HWND(handle), attribute, ctypes.byref(setting), ctypes.sizeof(setting))

    def toggle_maximized(self):
        if self.isMaximized(): self.showNormal()
        else: self.showMaximized()

    def position_window_controls(self):
        self.window_controls.move(self.caption_player.width() - self.window_controls.width(), 0)
        self.window_controls.raise_()

    def eventFilter(self, watched, event):
        if watched is getattr(self, "caption_player", None) and event.type() == QEvent.Type.Resize:
            self.position_window_controls()
        return super().eventFilter(watched, event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "maximize_button"):
            QTimer.singleShot(0, self.sync_caption)

    def sync_caption(self):
        self.window_controls.setVisible(not self.isFullScreen())
        text = "还原" if self.isMaximized() else "最大化"
        self.maximize_button.setToolTip(text); self.maximize_button.setAccessibleName(text); self.maximize_button.update()

    def nativeEvent(self, event_type, message):
        if sys.platform != "win32" or not hasattr(self, "_user32"):
            return super().nativeEvent(event_type, message)
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == 0x0083 and msg.wParam:  # WM_NCCALCSIZE
            if self._user32.IsZoomed(msg.hWnd) and not self.isFullScreen():
                rect = wintypes.RECT.from_address(msg.lParam)
                dpi = round(96 * self.devicePixelRatioF())
                border = sum(self._user32.GetSystemMetricsForDpi(value, dpi) for value in (33, 92))
                rect.left += border; rect.top += border; rect.right -= border; rect.bottom -= border
            return True, 0
        if msg.message == 0x0084 and not self.isFullScreen():  # WM_NCHITTEST
            rect = wintypes.RECT(); self._user32.GetWindowRect(msg.hWnd, ctypes.byref(rect))
            x = ctypes.c_short(msg.lParam & 0xffff).value - rect.left
            y = ctypes.c_short((msg.lParam >> 16) & 0xffff).value - rect.top
            scale = self.devicePixelRatioF(); dpi = round(96 * scale)
            border = sum(self._user32.GetSystemMetricsForDpi(value, dpi) for value in (33, 92))
            client = wintypes.POINT(x + rect.left, y + rect.top)
            self._user32.ScreenToClient(msg.hWnd, ctypes.byref(client))
            point = QPoint(round(client.x / scale), round(client.y / scale))
            # The native resize band overlaps the right scrollbar. Give its
            # controls the click while retaining the outer two pixels for resize.
            if isinstance(self.childAt(point), QScrollBar) and self.rect().adjusted(2, 2, -2, -2).contains(point):
                return True, 1  # HTCLIENT
            if not self._user32.IsZoomed(msg.hWnd):
                left, right = x < border, x >= rect.right - rect.left - border
                top, bottom = y < border, y >= rect.bottom - rect.top - border
                if top: return True, 13 if left else 14 if right else 12
                if bottom: return True, 16 if left else 17 if right else 15
                if left or right: return True, 10 if left else 11
            if point.y() < self.caption_player.height():
                child = self.childAt(point)
                while child and child is not self:
                    if child is self.caption_icon: return True, 3  # HTSYSMENU
                    # Keep hover details, seeking, playback buttons and the search
                    # field in the client area; only the surrounding space drags.
                    if child is self.caption_now_playing or isinstance(child, (QAbstractButton, QAbstractSlider, QLineEdit)):
                        return True, 1
                    child = child.parentWidget()
                return True, 2  # HTCAPTION
            return True, 1  # HTCLIENT; buttons keep their normal Qt click handling.
        return super().nativeEvent(event_type, message)
