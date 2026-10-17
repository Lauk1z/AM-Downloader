"""Own one player per data directory and restore it on subsequent launches."""
import hashlib
import os
from pathlib import Path
import time

from PySide6.QtCore import QObject, QLockFile, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    activated = Signal()

    def __init__(self, directory, parent=None):
        super().__init__(parent)
        directory = Path(directory).resolve(); directory.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(os.path.normcase(str(directory)).encode("utf-8")).hexdigest()[:24]
        self.name = "AM-Dowloader-" + key
        self.lock = QLockFile(str(directory / "app-instance.lock")); self.lock.setStaleLockTime(0)
        self.server = QLocalServer(self); self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self.restore)
        self.pending_activation = False

    def acquire(self, timeout=8):
        deadline = time.monotonic() + timeout
        while True:
            if self.lock.tryLock(0):
                if not self.server.listen(self.name):
                    self.lock.unlock()
                    raise RuntimeError("无法建立窗口唤回连接：" + self.server.errorString())
                return True
            if self.lock.error() != QLockFile.LockError.LockFailedError:
                raise RuntimeError("无法访问程序运行锁，请检查数据目录权限。")
            socket = QLocalSocket()
            socket.connectToServer(self.name)
            if socket.waitForConnected(150):
                if os.name == "nt":
                    import ctypes
                    pid, _, _ = self.lock.getLockInfo()
                    if pid: ctypes.windll.user32.AllowSetForegroundWindow(pid)
                socket.write(b"activate\n"); socket.waitForBytesWritten(250); socket.disconnectFromServer()
                return False
            if time.monotonic() >= deadline:
                raise RuntimeError("软件已在运行，但暂时无法恢复窗口，请稍后重试。")
            time.sleep(.05)

    def restore(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.disconnectFromServer(); socket.deleteLater()
            self.pending_activation = True; self.activated.emit()

    def close(self):
        self.server.close(); self.lock.unlock()
