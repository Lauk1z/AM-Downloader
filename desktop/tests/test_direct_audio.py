"""Byte-level direct-output regression tests; these never open an audio device."""
import json
from pathlib import Path
import struct
import subprocess
import pytest
from audio_fixtures import dsd_files
from musicdesk.playback import native_executable, output_format


def render(path, output, rate, fmt, position=0):
    subprocess.run([str(native_executable()), "--mode", "render", "--format", fmt,
                    "--file", str(path), "--rate", str(rate), "--channels", "2", "--position", str(position),
                    "--output", str(output)], check=True, capture_output=True, timeout=20)
    return output.read_bytes()


@pytest.mark.parametrize("multiple", [64, 128, 256, 512])
def test_dsf_dff_raw_and_dop_are_bit_exact(tmp_path, multiple):
    dsf, dff = dsd_files(tmp_path, multiple, seconds=1)
    # Non-symmetric bytes and different channels detect both bit and channel swaps.
    data = bytearray(dsf.read_bytes())
    left = bytes(range(256)) * 16; right = bytes(reversed(range(256))) * 16
    data[92:92+4096] = left; data[92+4096:92+8192] = right; dsf.write_bytes(data)
    canonical = bytearray(dff.read_bytes()); start = 16
    while canonical[start:start+4] != b"DSD ":
        size = int.from_bytes(canonical[start+4:start+12], "big"); start += 12+size+(size & 1)
    start += 12
    reverse = bytes(int(f"{i:08b}"[::-1], 2) for i in range(256))
    canonical[start:start+8192:2] = left.translate(reverse)
    canonical[start+1:start+8192:2] = right.translate(reverse); dff.write_bytes(canonical)
    a = render(dsf, tmp_path / "dsf.raw", multiple * 44100, "dsd")
    b = render(dff, tmp_path / "dff.raw", multiple * 44100, "dsd")
    assert a == b and len(a) == multiple * 44100 // 8 * 2
    assert a[:8192:2] == left.translate(reverse) and a[1:8192:2] == right.translate(reverse)
    dop = render(dsf, tmp_path / "dop.raw", multiple * 44100, "dop")
    assert len(dop) == len(a) * 2
    restored = bytearray(len(a))
    for i in range(0, len(dop), 8):
        for c in range(2):
            pad, newer, older, marker = dop[i+c*4:i+c*4+4]
            assert pad == 0 and marker == (0x05 if (i//8)%2 == 0 else 0xfa)
            restored[i//2+c] = older; restored[i//2+c+2] = newer
    assert restored == a
    seek = render(dsf, tmp_path / "seek.raw", multiple * 44100, "dsd", 500)
    assert seek == a[len(a)//2:]


def test_bad_dsd_and_wrong_mode_fail_before_output(tmp_path):
    path = tmp_path / "bad.dsf"; path.write_bytes(b"DSD bad header")
    result = subprocess.run([str(native_executable()), "--mode", "render", "--format", "dsd", "--rate", "2822400", "--channels", "2", "--file", str(path), "--output", str(tmp_path / "bad.raw")], capture_output=True, text=True)
    assert result.returncode and json.loads(result.stdout)["event"] == "error"
    with pytest.raises(ValueError, match="原生 DSD 需要 ASIO"):
        output_format({"mode": "wasapi", "device": "dac", "dsd": "native"}, True)
    assert output_format({"mode": "asio", "device": "dac", "dsd": "native"}, True) == "dsd"
    assert output_format({"mode": "wasapi", "device": "dac", "dsd": "dop"}, True) == "dop"
    assert output_format({"mode": "asio", "device": "dac", "dsd": "native"}, False) == "pcm"


def test_pcm_decode_keeps_integer_samples(tmp_path):
    import wave
    wav = tmp_path / "pcm.wav"
    values = [0, 1, -1, 32767, -32768, 100, -100] * 2000
    with wave.open(str(wav), "wb") as out:
        out.setnchannels(2); out.setsampwidth(2); out.setframerate(44100)
        out.writeframes(struct.pack("<"+"h"*len(values), *values))
    output = tmp_path / "pcm.raw"
    decoder = Path(__file__).resolve().parents[1] / "vendor/backend/deps/ffmpeg.exe"
    subprocess.run([str(native_executable()), "--mode", "render", "--format", "pcm", "--rate", "44100", "--channels", "2", "--file", str(wav), "--ffmpeg", str(decoder), "--output", str(output)], check=True, capture_output=True, timeout=20)
    assert output.read_bytes() == struct.pack("<"+"i"*len(values), *(v << 16 for v in values))


def test_missing_device_does_not_fallback_and_can_recover(tmp_path):
    import time
    import wave
    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtWidgets import QApplication
    from PySide6.QtMultimedia import QAudioOutput
    from musicdesk.appearance import create_application
    from musicdesk.playback import PlaybackEngine
    app = QApplication.instance() or create_application([])
    wav = tmp_path / "silence.wav"
    with wave.open(str(wav), "wb") as file:
        file.setnchannels(2); file.setsampwidth(2); file.setframerate(44100); file.writeframes(b"\0"*44100*4)
    audio = QAudioOutput(); audio.setMuted(True)
    engine = PlaybackEngine(audio, Path(__file__).resolve().parents[1] / "vendor/backend",
                            {"mode": "wasapi", "device": "missing-device", "dsd": "dop"})
    errors = []; engine.errorOccurred.connect(lambda _, message: errors.append(message))
    def wait_until(condition):
        deadline = time.monotonic() + 5
        while not condition():
            loop = QEventLoop(); QTimer.singleShot(20, loop.quit); loop.exec()
            assert time.monotonic() < deadline
    try:
        engine.setSource(QUrl.fromLocalFile(str(wav))); engine.play()
        wait_until(lambda: bool(errors))
        assert engine.direct and engine.mediaStatus() == engine.MediaStatus.InvalidMedia
        assert engine.qt.source().isEmpty() and engine.qt.playbackState() != engine.PlaybackState.PlayingState
        assert "设备不可用" in errors[0]
        engine.configure({"mode": "shared"}); engine.play()
        wait_until(lambda: engine.position() > 100)
        assert engine.error() == engine.Error.NoError and engine.source().toLocalFile() == str(wav).replace("\\", "/")
    finally: engine.shutdown()
