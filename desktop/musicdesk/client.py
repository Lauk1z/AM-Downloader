import ctypes
import json
import os
from pathlib import Path
import sys

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal
from .core import python_path, redact
from .runtime import code_root, is_managed


class BackendClient(QObject):
    event = Signal(dict)
    message = Signal(str)

    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.root = Path(root)
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.read_stdout)
        self.process.readyReadStandardError.connect(self.read_stderr)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        self.buffer = b""
        self.pending = []
        self.hello = False
        self.stopping = False

    def process_error(self, error):
        self.message.emit(self.process.errorString())
        if error == QProcess.ProcessError.FailedToStart:
            self.pending.clear()
            self.event.emit({"event": "fatal", "message": "无法启动下载后端：" + self.process.errorString()})

    def start_process(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            return
        self.stopping = False
        self.hello = False
        self.buffer = b""
        resource = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        worker = resource / "musicdesk_worker.py"
        runtime = code_root(self.root)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PATH", str(runtime / "deps") + os.pathsep + env.value("PATH"))
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("PYTHONDONTWRITEBYTECODE", "1")
        self.process.setProcessEnvironment(env)
        self.process.setWorkingDirectory(str(self.root))
        self.process.setProgram(str(python_path(self.root)))
        arguments = ["-u", str(worker), "--root", str(runtime)]
        if is_managed(self.root): arguments.extend(["--state-root", str(self.root)])
        self.process.setArguments(arguments)
        if os.name == "nt" and getattr(sys, "frozen", False):
            ctypes.windll.kernel32.SetDllDirectoryW(None)
        try:
            self.process.start()
        finally:
            if os.name == "nt" and getattr(sys, "frozen", False):
                ctypes.windll.kernel32.SetDllDirectoryW(str(resource))

    def send(self, command):
        if not self.hello:
            self.pending.append(command)
            try:
                self.start_process()
            except Exception as error:
                self.pending.clear()
                self.event.emit({"event": "fatal", "message": str(error)})
            return
        self.process.write((json.dumps(command, ensure_ascii=False) + "\n").encode("utf-8"))

    def read_stdout(self):
        self.buffer += bytes(self.process.readAllStandardOutput())
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            try:
                event = json.loads(line)
            except ValueError:
                self.message.emit(redact(line.decode("utf-8", "replace")))
                continue
            if event.get("event") == "hello":
                self.hello = True
                pending, self.pending = self.pending, []
                for command in pending:
                    self.send(command)
            if event.get("event") == "log":
                event["text"] = redact(event.get("text", ""))
            self.event.emit(event)

    def read_stderr(self):
        value = bytes(self.process.readAllStandardError()).decode("utf-8", "replace").strip()
        if value:
            self.message.emit(redact(value))

    def finished(self, code, _):
        self.hello = False
        self.pending.clear()
        self.event.emit({"event": "disconnected", "expected": self.stopping, "code": code})

    def shutdown(self):
        self.stopping = True
        if self.process.state() != QProcess.ProcessState.NotRunning:
            if self.hello:
                self.send({"action": "stop"})
            else:
                self.process.closeWriteChannel()
