"""Escape-frame compatibility must preserve PCM and keep corruption checks strict."""
import ast
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

import backend_patches

ROOT = Path(__file__).resolve().parents[1]


def load_helper():
    tree = ast.parse((ROOT / "vendor/backend/src/mp4.py").read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "normalize_alac_termination")
    namespace = {"SongInfo": SimpleNamespace, "Codec": SimpleNamespace(ALAC="alac"),
                 "logger": SimpleNamespace(info=lambda *_: None)}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "mp4.py", "exec"), namespace)
    return namespace[function.name]


normalize = load_helper()


def fixture(depth=24, channels=2, partial=False):
    count = 7 if partial else 16
    atom = bytearray.fromhex("00000024616c616300000000000010000018280a0e0200ff00006004002328000000bb80")
    atom[12:16] = (16).to_bytes(4, "big")
    atom[17], atom[21] = depth, channels
    header = f"{channels - 1:03b}" + "0" * 16 + ("1001" if partial else "0001")
    if partial:
        header += f"{count:032b}"
    # Nonzero, alternating signed sample patterns; include every audio bit.
    pcm = "".join(f"{((i + 1) * 70193) % (1 << depth):0{depth}b}" for i in range(count * channels))
    end = len(header + pcm)
    pad = "0" * (-(end + 3) % 8)
    invalid_bits, valid_bits = header + pcm + "000" + pad, header + pcm + "111" + pad
    invalid = int(invalid_bits, 2).to_bytes(len(invalid_bits) // 8, "big")
    valid = int(valid_bits, 2).to_bytes(len(valid_bits) // 8, "big")
    song = SimpleNamespace(codec="alac", decoderParams=bytes(atom),
                           samples=[SimpleNamespace(data=invalid, duration=count)])
    return song, invalid, valid


@pytest.mark.parametrize("depth", [16, 20, 24, 32])
@pytest.mark.parametrize("channels", [1, 2])
@pytest.mark.parametrize("partial", [False, True])
def test_only_end_marker_changes_and_valid_frames_are_unchanged(depth, channels, partial):
    song, missing, valid = fixture(depth, channels, partial)
    assert normalize(song, missing) == valid
    assert normalize(song, valid) is valid
    song.samples[0].data = valid
    assert normalize(song, valid) is valid


@pytest.mark.parametrize("defect", ["codec", "atom", "depth", "channels", "duration", "length",
                                    "reserved", "compressed", "truncated", "trailer", "source_trailer"])
def test_ambiguous_or_corrupted_frames_are_not_repaired(defect):
    song, media, _ = fixture()
    if defect == "codec": song.codec = "aac"
    elif defect == "atom": song.decoderParams = b""
    elif defect in ("depth", "channels"):
        atom = bytearray(song.decoderParams)
        atom[17 if defect == "depth" else 21] = 8
        song.decoderParams = bytes(atom)
    elif defect == "duration": song.samples[0].duration -= 1
    elif defect == "length": media += b"\0"
    elif defect == "reserved": media = media[:1] + bytes([media[1] | 1]) + media[2:]
    elif defect == "compressed": media = media[:2] + bytes([media[2] & ~2]) + media[3:]
    elif defect == "truncated":
        media = media[:-1]; song.samples[0].data = media
    elif defect == "trailer": media = media[:-1] + b"\x01"
    elif defect == "source_trailer": song.samples[0].data = media[:-1] + b"\x01"
    assert normalize(song, media) is media


def test_mixed_packets_preserve_boundaries_and_other_frames():
    song, missing, valid = fixture()
    song.samples = [SimpleNamespace(data=valid, duration=16), song.samples[0],
                    SimpleNamespace(data=b"unrecognized packet", duration=16), song.samples[0]]
    assert normalize(song, valid + missing + b"unrecognized packet" + missing) == (
        valid + valid + b"unrecognized packet" + valid)


def test_pinned_backend_patch_is_reproducible(tmp_path):
    with zipfile.ZipFile(ROOT / "vendor/v2-clean.zip") as archive:
        for name in ("src/mp4.py", "src/legacy/mp4.py", "src/api.py", "src/cmd.py", "src/rip.py"):
            target = tmp_path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
    backend_patches.apply(tmp_path)
    assert (tmp_path / "src/mp4.py").read_text(encoding="utf-8") == (
        ROOT / "vendor/backend/src/mp4.py").read_text(encoding="utf-8")
    # A zero exit code with decode errors must still fail integrity checking.
    tree = ast.parse((tmp_path / "src/mp4.py").read_text(encoding="utf-8"))
    check = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name == "check_song_integrity")
    result = SimpleNamespace(returncode=0, stderr=b"invalid element channel count")
    import tempfile
    import uuid
    namespace = {"TemporaryDirectory": tempfile.TemporaryDirectory, "uuid": uuid, "Path": Path,
                 "subprocess": SimpleNamespace(run=lambda *a, **k: result)}
    exec(compile(ast.Module(body=[check], type_ignores=[]), "mp4.py", "exec"), namespace)
    assert not namespace[check.name](b"invalid audio")
    result.stderr = b""; result.returncode = 1
    assert not namespace[check.name](b"invalid audio")
