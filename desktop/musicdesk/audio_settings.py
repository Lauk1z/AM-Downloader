"""Device discovery and direct-output settings, independent of the downloader."""
import json
from PySide6.QtCore import QProcess, QTimer, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QHBoxLayout
from .playback import native_executable
from .widgets import SettingsComboBox, button, label


class AudioSettings(QWidget):
    applied = Signal(dict)

    def __init__(self, engine, store, parent=None):
        super().__init__(parent)
        self.engine, self.store, self.devices = engine, store, []
        self.process = None
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 12, 0, 0); layout.setSpacing(12)
        layout.addWidget(label("音频输出", 15, True))
        form = QFormLayout(); form.setVerticalSpacing(12)
        self.mode = SettingsComboBox()
        for title, key in (("系统共享（兼容模式）", "shared"), ("WASAPI 独占", "wasapi"), ("ASIO（支持原生 DSD）", "asio")):
            self.mode.addItem(title, key)
        self.device = SettingsComboBox(); self.dsd = SettingsComboBox()
        form.addRow("输出模式", self.mode); form.addRow("输出设备", self.device); form.addRow("DSD 播放方式", self.dsd); layout.addLayout(form)
        actions = QHBoxLayout()
        self.refresh = button("刷新设备", "refresh"); self.refresh.clicked.connect(self.discover); actions.addWidget(self.refresh)
        self.probe = button("检测 DSD 能力"); self.probe.clicked.connect(self.inspect_dsd); actions.addWidget(self.probe)
        self.apply_button = button("应用音频设置", primary=True); self.apply_button.clicked.connect(self.apply); actions.addWidget(self.apply_button); actions.addStretch(); layout.addLayout(actions)
        self.note = label("", 9, color="#a7a7b0"); self.note.setWordWrap(True); layout.addWidget(self.note)
        self.status = label(engine.output_description, 9, color="#aaaaB2"); self.status.setWordWrap(True); layout.addWidget(self.status)
        engine.outputChanged.connect(self.status.setText)
        self.mode.setCurrentIndex(max(0, self.mode.findData(engine.config.get("mode", "shared"))))
        self.mode.currentIndexChanged.connect(self.populate)
        self.populate(); QTimer.singleShot(0, self.discover)

    def populate(self):
        mode = self.mode.currentData(); config = self.engine.config
        previous_dsd = self.dsd.currentData() or config.get("dsd", "native")
        previous = self.device.currentData() if self.device.property("kind") == mode else config.get("device") if mode == config.get("mode") else None
        self.device.clear(); self.device.setProperty("kind", mode); self.dsd.clear()
        if mode == "shared":
            self.device.addItem("Windows 默认音频设备", ""); self.dsd.addItem("解码为 PCM", "pcm")
        else:
            for device in self.devices:
                if device["kind"] == mode: self.device.addItem(device["name"], device["id"])
            index = self.device.findData(previous)
            if previous and index < 0:
                self.device.addItem("已保存设备当前不可用 · 请连接或重新选择", previous); index = self.device.count() - 1
            if index < 0:
                index = next((i for i in range(self.device.count()) if "SMSL" in self.device.itemText(i).upper() or "USB DAC" in self.device.itemText(i).upper()), 0)
            self.device.setCurrentIndex(index)
            if mode == "asio": self.dsd.addItem("原生 DSD（保持源采样率，支持 DSD512）", "native")
            self.dsd.addItem("DoP（保持 DSD 数据，封装为 PCM 帧传输）", "dop")
            self.dsd.setCurrentIndex(max(0, self.dsd.findData(previous_dsd)))
        self.device.setEnabled(mode != "shared"); self.dsd.setEnabled(mode != "shared"); self.probe.setEnabled(mode == "asio" and self.process is None)
        self.note.setText("共享模式保留软件音量，DSD 解码为 PCM。" if mode == "shared" else
                          "直通输出旁路软件音量，请用 DAC 调节音量。设备不支持时会停止并提示，不自动重采样。DSD 直通支持 DSF 和未压缩 DFF；DST、WavPack DSD 请使用共享模式。" +
                          (" DoP 的最高档位还取决于 DAC 的 DoP 支持和 PCM 传输速率。" if mode == "wasapi" else ""))

    def request(self, arguments, callback):
        if self.process: return
        if not native_executable().is_file(): self.note.setText("原生音频组件缺失，请完整解压软件。"); return
        process = QProcess(self); self.process = process; self.refresh.setEnabled(False); self.probe.setEnabled(False)
        def finished(*_):
            if process is not self.process: return
            data = bytes(process.readAllStandardOutput()).decode("utf-8", "replace")
            self.process = None; self.refresh.setEnabled(True); self.probe.setEnabled(self.mode.currentData() == "asio")
            try:
                rows = [json.loads(line) for line in data.splitlines() if line.strip()]
                if not rows: raise ValueError("未获得设备信息，请检查 DAC 连接及驱动")
                if any(row.get("event") == "error" for row in rows): raise ValueError(next(row["message"] for row in rows if row.get("event") == "error"))
                callback(rows)
            except Exception as error: self.note.setText(str(error))
            process.deleteLater()
        process.finished.connect(finished)
        process.errorOccurred.connect(lambda error: finished() if error == QProcess.ProcessError.FailedToStart else None)
        process.start(str(native_executable()), arguments)
        QTimer.singleShot(10000, lambda: process.kill() if self.process is process else None)

    def discover(self):
        def done(rows): self.devices = rows; self.populate()
        self.request(["--list"], done)

    def inspect_dsd(self):
        if self.engine.playbackState() == self.engine.PlaybackState.PlayingState:
            self.note.setText("请先停止播放再检测，避免中断当前音频设备。"); return
        if self.engine._process:
            self.note.setText("请先切换到系统共享模式并应用，再检测设备能力。"); return
        device = self.device.currentData()
        if not device: return
        self.request(["--probe-asio", device], lambda rows: self.note.setText("驱动报告支持：" + "、".join(f"DSD{rate}" for rate in rows[0]["dsd_rates"]) + "。播放时仍会验证实际采样率与通道格式。"))

    def apply(self):
        mode = self.mode.currentData(); device = self.device.currentData()
        if mode != "shared" and not device: self.note.setText("请先连接并选择输出设备。"); return
        config = {"mode": mode, "device": device or "", "device_name": self.device.currentText(), "dsd": self.dsd.currentData()}
        self.store.set("audio_output", config); self.engine.configure(config); self.applied.emit(config)

    def shutdown(self):
        if self.process: self.process.kill(); self.process.waitForFinished(1000)
