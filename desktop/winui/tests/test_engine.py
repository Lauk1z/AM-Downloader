"""Exercise the new native binary and Qt-free JSON utility with generated audio."""
import json
from pathlib import Path
import queue
import shutil
import struct
import subprocess
import sys
import threading
import wave

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from audio_fixtures import generate, dsd_files
from disc_fixtures import sacd_image

BUNDLE = ROOT / "vendor/backend"
FFMPEG = BUNDLE / "deps/ffmpeg.exe"
HOST = ROOT / "winui/artifacts/native/am_audio.exe"


class Utility:
    def __init__(self, profile):
        self.profile = str(profile)
        self.process = subprocess.Popen([str(BUNDLE / ".venv/python.exe"), "-u", str(ROOT / "winui/engine/library_worker.py"),
            "--resources", str(ROOT), "--bundle", str(BUNDLE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", cwd=ROOT)
        self.responses = queue.Queue()
        self.errors = []
        threading.Thread(target=lambda: [self.responses.put(json.loads(line)) for line in self.process.stdout], daemon=True).start()
        threading.Thread(target=lambda: self.errors.extend(self.process.stderr), daemon=True).start()
        self.serial = 0

    def call(self, action, **values):
        self.serial += 1
        request = dict(values, action=action, id=str(self.serial), profile=self.profile)
        self.process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n"); self.process.stdin.flush()
        response = self.responses.get(timeout=45)
        assert response["id"] == str(self.serial), response
        assert "error" not in response, response
        return response["result"]

    def close(self):
        self.process.stdin.write('{"action":"stop"}\n'); self.process.stdin.flush(); self.process.stdin.close()
        assert self.process.wait(timeout=20) == 0, self.errors
        assert not any("PySide6" in value for value in self.errors), self.errors


@pytest.fixture
def utility(tmp_path):
    process = Utility(tmp_path / "profile")
    yield process
    process.close()


@pytest.fixture(scope="module")
def formats(tmp_path_factory):
    folder = tmp_path_factory.mktemp("winui-formats")
    generate(folder, FFMPEG)
    return folder


def render(path, output, rate, channels=2, fmt="pcm", position=0):
    result = subprocess.run([str(HOST), "--mode", "render", "--format", fmt, "--file", str(path),
        "--rate", str(rate), "--channels", str(channels), "--position", str(position),
        "--ffmpeg", str(FFMPEG), "--output", str(output)], capture_output=True, timeout=25)
    assert result.returncode == 0, result.stdout.decode("utf8", "replace")
    return output.read_bytes()


@pytest.mark.parametrize("name", ["vorbis.ogg", "opus.ogg", "flac.oga", "audio.opus", "audio.flac", "audio.wav",
    "audio.aiff", "compressed.aifc", "audio.wv", "audio.tta", "audio.wma", "audio.m4a", "audio.mp3", "audio.aac",
    "audio.spx", "audio.mp2", "audio.ac3", "audio.eac3"])
def test_formats_decode_without_qt(utility, formats, tmp_path, name):
    path = formats / name
    info = utility.call("info", path=str(path))
    assert info["rate"] > 0 and info["channels"] == 2 and info["duration"] > 3900
    if "opus" in name: assert info["rate"] == 48000
    actual = render(path, tmp_path / "audio.raw", info["rate"])
    expected = subprocess.run([str(FFMPEG), "-nostdin", "-v", "error", "-i", str(path), "-map", "0:a:0",
        "-f", "s32le", "-acodec", "pcm_s32le", "-"], capture_output=True, check=True, timeout=25).stdout
    assert actual == expected and len(actual) > 0


@pytest.mark.parametrize("multiple", [64, 128, 256, 512])
def test_dsd_and_dop_bit_exact(tmp_path, multiple):
    dsf, dff = dsd_files(tmp_path, multiple, seconds=1)
    data = bytearray(dsf.read_bytes()); left = bytes(range(256)) * 16; right = bytes(reversed(range(256))) * 16
    data[92:4188] = left; data[4188:8284] = right; dsf.write_bytes(data)
    reverse = bytes(int(f"{i:08b}"[::-1], 2) for i in range(256))
    data = bytearray(dff.read_bytes()); start = 16
    while data[start:start+4] != b"DSD ":
        size = int.from_bytes(data[start+4:start+12], "big"); start += 12 + size + (size & 1)
    start += 12; data[start:start+8192:2] = left.translate(reverse); data[start+1:start+8192:2] = right.translate(reverse); dff.write_bytes(data)
    a = render(dsf, tmp_path / "a.raw", 44100 * multiple, fmt="dsd")
    b = render(dff, tmp_path / "b.raw", 44100 * multiple, fmt="dsd")
    assert a == b and len(a) == multiple * 44100 // 8 * 2
    assert a[:8192:2] == left.translate(reverse) and a[1:8192:2] == right.translate(reverse)
    dop = render(dsf, tmp_path / "dop.raw", 44100 * multiple, fmt="dop")
    assert len(dop) == len(a) * 2
    assert dop[0::4] == bytes(len(dop)//4)
    assert dop[3::8] == (b"\x05\xfa" * (len(dop)//16)) and dop[7::8] == dop[3::8]
    restored = bytearray(len(a)); restored[::4] = dop[2::8]; restored[1::4] = dop[6::8]; restored[2::4] = dop[1::8]; restored[3::4] = dop[5::8]
    assert restored == a
    assert render(dsf, tmp_path / "seek.raw", 44100 * multiple, fmt="dsd", position=500) == a[len(a)//2:]


def test_pcm_integer_samples_preserved(tmp_path):
    path = tmp_path / "整数.wav"; values = [0, 1, -1, 32767, -32768, 100, -100] * 2000
    with wave.open(str(path), "wb") as out:
        out.setparams((2, 2, 44100, 0, "NONE", "not compressed")); out.writeframes(struct.pack("<"+"h"*len(values), *values))
    assert render(path, tmp_path / "pcm.raw", 44100) == struct.pack("<"+"i"*len(values), *(v << 16 for v in values))


def test_cue_sacd_extraction_and_read_only_sources(utility, tmp_path):
    source = tmp_path / "完整音轨.wav"
    with wave.open(str(source), "wb") as out:
        out.setparams((1, 2, 44100, 0, "NONE", "not compressed")); out.writeframes(struct.pack("<"+"h"*88200, *(i % 32767 for i in range(88200))))
    cue = tmp_path / "专辑.cue"; cue.write_text('PERFORMER "Album Artist"\nTITLE "Disc"\nREM DATE 2020\nFILE "完整音轨.wav" WAVE\nTRACK 01 AUDIO\nTITLE "One"\nINDEX 01 00:00:00\nTRACK 02 AUDIO\nTITLE "Two"\nINDEX 01 00:01:00\n', encoding="utf-8-sig")
    original = source.read_bytes()
    result = utility.call("scan", extra=[str(cue), str(source)])
    assert not result["errors"] and len(result["tracks"]) == 2
    selected = result["tracks"][1]; assert selected["start"] == 1 and selected["year"] == 2020
    path = utility.call("prepare", track=selected); info = utility.call("info", path=path)
    assert info["duration"] == 1000 and info["rate"] == 44100
    with wave.open(str(source), "rb") as out: out.setpos(44100); samples = out.readframes(44100)
    expected = struct.unpack("<"+"h"*(len(samples)//2), samples)
    assert render(path, tmp_path / "cue.raw", 44100, channels=1) == struct.pack("<"+"i"*len(expected), *(v << 16 for v in expected))
    assert source.read_bytes() == original
    image = sacd_image(tmp_path / "模拟专辑.iso"); original = image.read_bytes()
    result = utility.call("scan", extra=[str(image)])
    assert not result["errors"] and len(result["tracks"]) == 2
    selected = result["tracks"][1]; assert selected["codec"] == "dsd"
    path = utility.call("prepare", track=selected); info = utility.call("info", path=path)
    assert info["duration"] == 1000 and info["dsd"] and info["rate"] == 2822400
    assert render(path, tmp_path / "iso.raw", 2822400, fmt="dsd") == b"\x96" * (2822400//8*2)
    assert image.read_bytes() == original


def test_tags_backup_duplicates_and_config(utility, formats, tmp_path):
    init = utility.call("initialize")
    utility.call("save_config", state=init["state"], language="en-US", rate=96000, bits=24)
    config = utility.call("config", state=init["state"])
    assert config["download"]["maxSampleRate"] == 96000 and config["region"]["language"] == "en-US"
    source = tmp_path / "original.wav"; shutil.copy2(formats / "audio.wav", source)
    duplicate = tmp_path / "duplicate.wav"; shutil.copy2(source, duplicate)
    scanned = utility.call("scan", extra=[str(source), str(duplicate)])
    groups = utility.call("duplicates", tracks=scanned["tracks"])
    assert groups[0]["kind"] == "文件完全相同" and len(groups[0]["tracks"]) == 2
    before = source.read_bytes(); samples = render(source, tmp_path / "before.raw", 96000)
    track = next(t for t in scanned["tracks"] if t["path"] == str(source))
    result = utility.call("edit", tracks=[track], changes=[dict(title="新歌名", artist="新艺人", album="新专辑", album_artist="共同艺人", year=2026, disc=2, number=3, edition="原始母带")])
    assert result["files"] == 1 and Path(result["backups"][0]).read_bytes() == before
    edited = utility.call("scan", extra=[str(source)])["tracks"][0]
    assert edited["title"] == "新歌名" and edited["year"] == 2026 and edited["disc"] == 2 and edited["edition"] == "原始母带"
    assert render(source, tmp_path / "after.raw", 96000) == samples


def test_missing_device_never_falls_back(tmp_path, formats):
    result = subprocess.run([str(HOST), "--mode", "wasapi", "--format", "pcm", "--device", "winui-test-no-device",
        "--file", str(formats / "audio.wav"), "--ffmpeg", str(FFMPEG), "--rate", "96000", "--channels", "2", "--bits", "24"], capture_output=True, timeout=20)
    assert result.returncode != 0 and json.loads(result.stdout)["event"] == "error"
