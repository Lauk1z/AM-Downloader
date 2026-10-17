"""Keep playback available from the Windows notification area."""
from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QMenu, QSystemTrayIcon, QVBoxLayout

from . import APP_NAME
from .widgets import button, icon, label, RED


class CloseDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.action = None
        self.setWindowTitle("关闭 " + APP_NAME); self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self); layout.setContentsMargins(24, 22, 24, 22); layout.setSpacing(16)
        layout.addWidget(label("要如何关闭主窗口？", 15, True))
        note = label("最小化到托盘后，播放和下载会继续。", 10, color="#aaaaB2")
        note.setWordWrap(True); layout.addWidget(note)
        actions = QHBoxLayout()
        self.tray_button = button("最小化到托盘", primary=True); self.tray_button.setDefault(True)
        self.exit_button = button("关闭程序"); self.exit_button.setAutoDefault(False)
        self.tray_button.clicked.connect(lambda: self.choose("tray"))
        self.exit_button.clicked.connect(lambda: self.choose("exit"))
        actions.addWidget(self.tray_button); actions.addWidget(self.exit_button); layout.addLayout(actions)
        self.remember = QCheckBox("记住我的选择", self); layout.addWidget(self.remember)

    def choose(self, action):
        self.action = action; self.accept()


class SystemTray(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner; self.exiting = False; self.restore_state = Qt.WindowState.WindowNoState
        self.close_dialog = None
        self.icon = QSystemTrayIcon(icon("app", RED, 32), owner)
        self.menu = QMenu(owner)
        self.menu.addAction("显示主窗口", self.restore)
        self.title = self.menu.addAction(APP_NAME); self.title.setEnabled(False)
        self.play = self.menu.addAction("播放 / 暂停", owner.toggle_play)
        self.previous = self.menu.addAction("上一首", lambda: owner.skip(-1))
        self.next = self.menu.addAction("下一首", lambda: owner.skip(1))
        self.menu.addSeparator()
        self.menu.addAction("正在播放队列", self.show_queue)
        self.menu.addAction("音频输出链路", self.show_output)
        self.menu.addAction("最小化到托盘", self.minimize)
        self.menu.addSeparator(); self.menu.addAction("退出", self.exit)
        self.menu.aboutToShow.connect(self.refresh)
        self.icon.setContextMenu(self.menu); self.icon.activated.connect(self.activate)
        owner.media.playbackStateChanged.connect(self.refresh)
        self.refresh()
        if QSystemTrayIcon.isSystemTrayAvailable(): self.icon.show()

    def refresh(self, *_):
        owner = self.owner
        title = owner.play_title.text() if owner.current_path else APP_NAME
        self.title.setText(title); self.icon.setToolTip((APP_NAME + "\n" + title)[:127])
        playing = owner.media.playbackState() == owner.media.PlaybackState.PlayingState or owner.gap_timer.isActive() or (owner.preparing and owner.prepare_autoplay)
        self.play.setText("暂停" if playing else "播放")
        self.play.setEnabled(bool(owner.current_path or owner.tracks) and not owner.closing)
        for action in (self.previous, self.next): action.setEnabled(bool(owner.playlist) and not owner.closing)

    def activate(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick): self.restore()

    def minimize(self):
        if not QSystemTrayIcon.isSystemTrayAvailable(): self.owner.showMinimized(); return
        self.icon.show(); self.restore_state = self.owner.windowState() & ~Qt.WindowState.WindowMinimized
        self.owner.hide()

    def restore(self):
        if self.owner.closing: return
        if not self.owner.isVisible(): self.owner.setWindowState(self.restore_state)
        elif self.owner.isMinimized(): self.owner.setWindowState(self.owner.windowState() & ~Qt.WindowState.WindowMinimized)
        self.owner.show(); self.owner.raise_(); self.owner.activateWindow()
        if self.close_dialog:
            self.close_dialog.raise_(); self.close_dialog.activateWindow()

    def request_close(self):
        action = self.owner.store.get("close_action", "ask")
        if action == "tray": self.minimize(); return
        if action == "exit": QTimer.singleShot(0, self.exit); return
        self.restore()
        if self.close_dialog: return
        dialog = CloseDialog(self.owner); self.close_dialog = dialog
        dialog.finished.connect(lambda _: self.finish_close(dialog)); dialog.open()

    def finish_close(self, dialog):
        self.close_dialog = None
        if dialog.action and dialog.remember.isChecked():
            self.owner.store.set("close_action", dialog.action)
            self.owner.close_action.setCurrentIndex(self.owner.close_action.findData(dialog.action))
        if dialog.action == "tray": self.minimize()
        elif dialog.action == "exit": self.exit()
        dialog.deleteLater()

    def show_queue(self):
        self.restore()
        if not self.owner.body.opened or self.owner.panels.currentWidget() is not self.owner.playback_queue: self.owner.show_now_playing()

    def show_output(self):
        self.restore(); self.owner.show_output_chain()

    def exit(self):
        if self.close_dialog: self.close_dialog.reject()
        self.exiting = True
        if not self.owner.close() and not self.owner.closing:
            self.exiting = False; self.restore()

    def shutdown(self):
        self.icon.hide()
