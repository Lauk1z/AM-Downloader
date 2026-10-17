"""Readable output diagnostics; requested settings are never treated as measurements."""
from PySide6.QtCore import Qt
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout

from .widgets import button, label


def chain_details(engine, track, preparing=False):
    config = engine.config; direct = engine.direct
    source = f"{track.format_name} · {track.codec.upper()}\n{track.quality}" if track else "尚未选择歌曲"
    mode = {"shared": "系统共享", "wasapi": "WASAPI 独占", "asio": "ASIO"}.get(config.get("mode", "shared"), "未知输出模式")
    actual = engine.negotiated_output
    active = engine.playbackState() in (engine.PlaybackState.PlayingState, engine.PlaybackState.PausedState)
    if not track: decode = "选择歌曲后显示解码路径"
    elif preparing: decode = "正在准备镜像／整轨中的曲目"
    elif track.container and not track.area: decode = "CUE 分轨缓存 → PCM" + (" → 系统混音" if not direct else " → 独占输出")
    elif track.is_dsd and direct:
        decode = "DSD 数据直接输出" if config.get("dsd") == "native" else "DSD 数据 → DoP 封装（不是转为 PCM 音频）"
        if track.area: decode = "SACD 提取为 DSF → " + decode
    else: decode = "Qt / FFmpeg 解码为 PCM" if not direct else "FFmpeg 解码为 PCM，保持源采样率"
    if direct:
        device = config.get("device_name") or config.get("device") or "未选择设备"
        output = mode + " · 尚未建立输出，播放时确认实际规格"
        if actual and active:
            device = actual["device"]
            rate, bits, fmt = actual["rate"], actual["bits"], actual["format"]
            detail = f"DSD{rate // 44100} · {rate / 1000000:g} MHz" if fmt == "dsd" else f"{bits} bit / {rate / 1000:g} kHz"
            output = mode + " · 驱动已确认\n" + ("DoP 传输帧：" if fmt == "dop" else "") + detail
            if fmt == "dop" and track: output += f"\n承载 {track.quality}"
        process = "软件音量旁路；未添加均衡或混音"
        if actual and active and actual["format"] == "pcm" and engine._source_info:
            process += "；采样率与解码源一致" if actual["rate"] == engine._source_info["rate"] else "；输出采样率与解码源不同"
    else:
        device = engine.audio.device()
        if device.isNull(): device = QMediaDevices.defaultAudioOutput()
        device = device.description() or "Windows 默认音频设备"
        output = "系统共享混音 → 音频设备\n最终采样率与位深未直接测得，由 Windows 和设备决定"
        process = "软件音量：" + ("已静音" if engine.audio.isMuted() else f"{round(engine.audio.volume() * 100)}%")
        process += "；系统可能重采样或混音"
        if track and track.is_dsd: process += "；DSD 已解码为 PCM"
    state = "正在准备" if preparing else "播放中" if engine.playbackState() == engine.PlaybackState.PlayingState else "已暂停" if engine.playbackState() == engine.PlaybackState.PausedState else "未播放"
    if engine.error() != engine.Error.NoError: state = "输出失败：" + engine.errorString()
    return [("源文件", source), ("解码与传输", decode), ("输出接口", output), ("输出设备", device), ("音频处理", process), ("当前状态", state)]


class OutputChainDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner; self.setWindowTitle("音频输出链路"); self.resize(560, 610)
        layout = QVBoxLayout(self); layout.setContentsMargins(24, 22, 24, 22); layout.setSpacing(14)
        layout.addWidget(label("音频输出链路", 20, True))
        self.fields = []
        for name, _ in chain_details(owner.media, None):
            layout.addWidget(label(name, 9, True, "#a0a0a9"))
            value = label("", 11); value.setWordWrap(True); value.setTextFormat(Qt.TextFormat.PlainText)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(value); self.fields.append(value)
        layout.addStretch()
        actions = QHBoxLayout(); settings = button("音频设置"); settings.clicked.connect(lambda: (owner.navigate("settings"), self.close()))
        done = button("关闭"); done.clicked.connect(self.close); actions.addWidget(settings); actions.addStretch(); actions.addWidget(done); layout.addLayout(actions)
        for signal in (owner.media.outputChanged, owner.media.playbackStateChanged, owner.media.mediaStatusChanged, owner.audio.volumeChanged, owner.audio.mutedChanged, owner.audio.deviceChanged):
            signal.connect(self.refresh)
        self.refresh()

    def refresh(self, *_):
        track = next((item for item in self.owner.playlist if item.path == self.owner.current_path), None)
        for value, (_, text) in zip(self.fields, chain_details(self.owner.media, track, self.owner.preparing)): value.setText(text)
