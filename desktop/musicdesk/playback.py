"""Qt transport facade with an isolated native Windows direct-output host."""
import json
from pathlib import Path
import sys

import mutagen
from PySide6.QtCore import QObject, QProcess, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer

from .core import audio_codec
from .runtime import code_root


def native_executable():
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    return base / "native" / "bin" / "am_audio.exe"


def output_format(config, is_dsd):
    mode = config.get("mode", "shared")
    if mode == "shared": return "pcm"
    if mode not in {"wasapi", "asio"}: raise ValueError("未知音频输出模式")
    if not config.get("device"): raise ValueError("请选择音频输出设备")
    if not is_dsd: return "pcm"
    dsd = config.get("dsd", "native")
    if dsd == "native" and mode != "asio": raise ValueError("原生 DSD 需要 ASIO；WASAPI 请选 DoP 或转 PCM")
    if dsd not in {"native", "dop", "pcm"}: raise ValueError("未知 DSD 输出方式")
    return "dsd" if dsd == "native" else dsd


def source_format(path):
    audio = mutagen.File(path)
    if audio is None: raise ValueError("无法读取音频格式")
    codec = audio_codec(audio, Path(path))
    return {"rate": int(audio.info.sample_rate), "channels": int(audio.info.channels),
            "bits": int(getattr(audio.info, "bits_per_sample", 0) or 24),
            "duration": round(audio.info.length * 1000), "dsd": codec in {"dsd", "dst"}}


def output_error(message):
    for fragment, explanation in (
        ("2290679818", "设备正被其他程序占用，请关闭其他独占播放器后重试"),
        ("2290679812", "音频设备已断开或正在重连，请检查 USB 连接并重试"),
        ("does not support requested sample rate", "ASIO 驱动不支持这首歌曲的采样率，可选择兼容输出模式"),
        ("does not support this rate/bit depth", "设备不支持当前采样率或位深；DoP 还需要对应的 PCM 传输速率"),
        ("does not support native DSD", "所选 ASIO 驱动不支持原生 DSD，请选择 DAC 的厂商驱动或 DoP"),
        ("DSF and uncompressed DFF", "DSD 直通支持 DSF 和未压缩 DFF，其他 DSD 容器请使用共享模式"),
        ("DST is not supported", "压缩 DST 暂不支持直通，请使用系统共享模式解码播放"),
        ("source precision", "驱动输出位深不足或不支持整数输出，已停止以保留源数据精度"),
        ("underrun", "音频缓冲区供给不足，输出已停止，请关闭高负载任务后重试"),
        ("disconnected", "音频设备不可用，请检查 USB 连接或关闭占用设备的其他播放器"),
        ("Load ASIO driver", "无法加载 ASIO 驱动，请安装 DAC 厂商的 64 位驱动"),
        ("Selected output is unavailable", "所选音频设备不可用，请连接设备或重新选择输出"),
    ):
        if fragment in message: return explanation + "\n" + message
    return message


class PlaybackEngine(QObject):
    positionChanged = Signal(int)
    durationChanged = Signal(int)
    playbackStateChanged = Signal(object)
    mediaStatusChanged = Signal(object)
    errorOccurred = Signal(object, str)
    outputChanged = Signal(str)
    PlaybackState = QMediaPlayer.PlaybackState
    MediaStatus = QMediaPlayer.MediaStatus
    Error = QMediaPlayer.Error

    def __init__(self, audio, root, config=None, parent=None):
        super().__init__(parent)
        self.audio, self.root = audio, root
        self.qt = QMediaPlayer(self); self.qt.setAudioOutput(audio)
        self.config = dict(config or {"mode": "shared"})
        self._source = QUrl(); self._position = self._duration = 0
        self._state = self.PlaybackState.StoppedState; self._status = self.MediaStatus.NoMedia
        self._error = ""; self._process = None; self._pending = None; self._buffer = b""
        self._generation = 0; self._process_generation = -1; self._source_info = None
        self._intent = self.PlaybackState.StoppedState
        self._shared_play_pending = False
        self.negotiated_output = None
        self.output_description = "系统共享输出 · 尚未播放"
        for name in ("positionChanged", "durationChanged", "playbackStateChanged", "mediaStatusChanged", "errorOccurred"):
            getattr(self.qt, name).connect(lambda *args, name=name: getattr(self, name).emit(*args) if not self.direct else None)

    @property
    def direct(self): return self.config.get("mode", "shared") != "shared"

    def source(self): return self._source
    def position(self): return self._position if self.direct else self.qt.position()
    def duration(self): return self._duration if self.direct else self.qt.duration()
    def playbackState(self): return self._state if self.direct else self.qt.playbackState()
    def mediaStatus(self): return self._status if self.direct else self.qt.mediaStatus()
    def isSeekable(self): return bool(self._source_info) if self.direct else self.qt.isSeekable()
    def errorString(self): return self._error if self.direct else self.qt.errorString()
    def error(self): return self.Error.ResourceError if self.direct and self._error else self.Error.NoError if self.direct else self.qt.error()
    def setAudioBufferOutput(self, output): self.qt.setAudioBufferOutput(output)

    def _describe(self, text):
        self.output_description = text; self.outputChanged.emit(text)

    def _state_changed(self, state):
        self._state = state; self.playbackStateChanged.emit(state)

    def _status_changed(self, status):
        self._status = status; self.mediaStatusChanged.emit(status)

    def _fail(self, message):
        self._cancel()
        message = output_error(message)
        self._error = message; self._intent = self.PlaybackState.StoppedState
        self._state_changed(self.PlaybackState.StoppedState)
        self._status_changed(self.MediaStatus.InvalidMedia)
        self._describe("输出失败 · " + message)
        self.errorOccurred.emit(self.Error.ResourceError, message)

    def _cancel(self):
        self.negotiated_output = None
        self._generation += 1; self._pending = None; self._shared_play_pending = False
        process = self._process
        if process and process.state() != QProcess.ProcessState.NotRunning:
            process.write(b"stop\n")
            QTimer.singleShot(1200, lambda: process.kill() if process is self._process and process.state() != QProcess.ProcessState.NotRunning else None)

    def configure(self, config):
        source, position, playing = self.source(), self.position(), self.playbackState() == self.PlaybackState.PlayingState
        self._cancel(); self.qt.stop(); self.qt.setSource(QUrl()); self.config = dict(config)
        self.setSource(source); self.setPosition(position)
        if playing: self.play()

    def setSource(self, source):
        self._cancel(); self._source = QUrl(source); self._error = ""; self._position = self._duration = 0; self._source_info = None
        self._intent = self.PlaybackState.StoppedState
        if not self.direct:
            self.qt.setSource(source)
            self._describe("系统共享输出 · DSD 解码为 PCM（输出格式由系统及设备决定）")
            return
        self.qt.stop(); self.qt.setSource(QUrl()); self._state_changed(self.PlaybackState.StoppedState)
        self.positionChanged.emit(0); self.durationChanged.emit(0)
        self._describe("直通输出待命 · 播放时连接所选设备")
        if source.isEmpty(): self._status_changed(self.MediaStatus.NoMedia); return
        try:
            self._source_info = source_format(source.toLocalFile()); self._duration = self._source_info["duration"]
            self.durationChanged.emit(self._duration); self._status_changed(self.MediaStatus.LoadedMedia)
        except Exception as error: self._fail(str(error))

    def _arguments(self):
        if not native_executable().is_file(): raise ValueError("原生音频组件缺失，请完整解压新版软件")
        info = self._source_info
        if not info: raise ValueError("未选择有效音频文件")
        fmt = output_format(self.config, info["dsd"])
        if info["dsd"] and fmt == "pcm":
            raise ValueError("DSD 转 PCM 请使用系统共享模式；独占模式请选择原生 DSD 或 DoP")
        decoder = code_root(self.root) / "deps" / "ffmpeg.exe"
        if fmt == "pcm" and not decoder.is_file(): raise ValueError("找不到内置 FFmpeg 解码器")
        return ["--mode", self.config["mode"], "--format", fmt, "--device", self.config["device"],
                "--file", self._source.toLocalFile(), "--rate", str(info["rate"]), "--channels", str(info["channels"]),
                "--bits", str(min(32, info["bits"])), "--ffmpeg", str(decoder), "--position", str(self._position)]

    def _launch(self, args):
        if self._process and self._process.state() != QProcess.ProcessState.NotRunning:
            self._pending = (args, self._generation); return
        process = QProcess(self); self._process = process; self._buffer = b""
        generation = self._generation; self._process_generation = generation
        process.readyReadStandardOutput.connect(lambda: self._read(process, generation))
        process.finished.connect(lambda code, status: self._finished(process, generation, code))
        process.errorOccurred.connect(lambda error: self._fail("无法启动原生音频组件：" + process.errorString()) if generation == self._generation and error == QProcess.ProcessError.FailedToStart else None)
        process.start(str(native_executable()), args)

    def _read(self, process, generation):
        data = bytes(process.readAllStandardOutput())
        if generation != self._generation: return
        self._buffer += data
        while b"\n" in self._buffer:
            if generation != self._generation: break
            line, self._buffer = self._buffer.split(b"\n", 1)
            try: event = json.loads(line)
            except (ValueError, UnicodeError): continue
            kind = event.get("event")
            if kind == "ready":
                self.negotiated_output = dict(event)
                fmt = event["format"]
                detail = f"原生 DSD{event['rate'] // 44100} · {event['rate'] / 1000000:g} MHz" if fmt == "dsd" else f"{'DoP' if fmt == 'dop' else 'PCM'} · {event['bits']} bit / {event['rate'] / 1000:g} kHz"
                self._describe(f"{'ASIO' if event['mode'] == 'asio' else 'WASAPI 独占'} · {event['device']}\n{detail} · 软件音量旁路")
                self._status_changed(self.MediaStatus.BufferedMedia)
                if self._intent == self.PlaybackState.PausedState: process.write(b"pause\n")
                else: self._state_changed(self.PlaybackState.PlayingState)
            elif kind == "position":
                self._position = min(self._duration, event["ms"]); self.positionChanged.emit(self._position)
            elif kind in {"paused", "playing"}:
                self._state_changed(self.PlaybackState.PausedState if kind == "paused" else self.PlaybackState.PlayingState)
            elif kind == "error": self._fail(event["message"])
            elif kind == "end":
                self._position = self._duration; self.positionChanged.emit(self._position)
                self._intent = self.PlaybackState.StoppedState; self._state_changed(self.PlaybackState.StoppedState)
                self._status_changed(self.MediaStatus.EndOfMedia)

    def _finished(self, process, generation, code):
        self._read(process, generation)
        if process is self._process: self._process = None
        if generation == self._generation:
            self.negotiated_output = None
            self.outputChanged.emit(self.output_description)
        process.deleteLater()
        if generation == self._generation and not self._error and self._intent != self.PlaybackState.StoppedState:
            self._fail(f"音频输出进程退出（{code}）；设备可能已断开，请重新选择设备")
        pending, self._pending = self._pending, None
        if pending and pending[1] == self._generation: self._launch(pending[0])
        elif self._shared_play_pending and not self.direct:
            self._shared_play_pending = False; self.qt.play()

    def play(self):
        if not self.direct:
            if self._process and self._process.state() != QProcess.ProcessState.NotRunning: self._shared_play_pending = True
            else: self.qt.play()
            return
        if self._source.isEmpty(): return
        self._error = ""; self._intent = self.PlaybackState.PlayingState
        if self._position >= self._duration: self._position = 0
        if self._process and self._process_generation == self._generation:
            self._process.write(b"resume\n"); return
        try: self._launch(self._arguments())
        except Exception as error: self._fail(str(error))

    def pause(self):
        if not self.direct: self.qt.pause(); return
        self._intent = self.PlaybackState.PausedState
        if self._process: self._process.write(b"pause\n")
        else: self._state_changed(self.PlaybackState.PausedState)

    def stop(self):
        self._cancel(); self.qt.stop(); self._intent = self.PlaybackState.StoppedState
        if self.direct:
            self._position = 0; self._state_changed(self.PlaybackState.StoppedState); self.positionChanged.emit(0)

    def setPosition(self, value):
        if not self.direct: self.qt.setPosition(value); return
        playing = self._intent == self.PlaybackState.PlayingState
        self._cancel(); self._position = max(0, min(self._duration, int(value))); self.positionChanged.emit(self._position)
        if playing: self.play()

    def shutdown(self):
        self.stop()
        if self._process and not self._process.waitForFinished(1500):
            self._process.kill(); self._process.waitForFinished(500)
