from pathlib import Path
import hashlib
import shutil
import pytest
from musicdesk.core import Track, scan_library
from audio_fixtures import generate


@pytest.fixture(scope='module')
def fixtures(tmp_path_factory):
    folder = tmp_path_factory.mktemp('formats')
    ffmpeg = Path(__file__).resolve().parents[1] / 'vendor/backend/deps/ffmpeg.exe'
    generate(folder, ffmpeg)
    return folder


def test_formats_metadata_and_originals(fixtures, tmp_path):
    before = {p.name: hashlib.sha256(p.read_bytes()).digest() for p in fixtures.iterdir()}
    tracks, errors = scan_library(fixtures, tmp_path / 'covers')
    assert errors == [] and len(tracks) == len(before) == 24
    items = {Path(t.path).name: t for t in tracks}
    assert items['vorbis.ogg'].codec == 'vorbis'
    assert items['opus.ogg'].codec == 'opus' and items['opus.ogg'].rate == 48000
    assert items['flac.oga'].codec == 'flac' and items['flac.oga'].is_lossless
    assert items['compressed.aifc'].codec == 'aifc' and not items['compressed.aifc'].is_lossless
    assert items['audio.wav'].is_lossless and items['audio.wav'].bits == 24
    assert items['audio.aiff'].is_lossless and items['audio.aiff'].bits == 24
    assert items['audio.wma'].artist == 'Test' and items['audio.wma'].album == 'Test Audio'
    for multiple in (64, 128, 256):
        for ext in ('dsf', 'dff'):
            track = items[f'dsd-{multiple}.{ext}']
            assert track.rate == multiple * 44100 and track.bits == 1 and track.duration == 4
            assert track.quality.startswith(f'DSD{multiple}') and track.is_dsd
            assert 'DSD 解码为 PCM' in track.playback_details
            if multiple == 64:
                assert track.title == 'DSD 本地测试' and Path(track.cover).is_file()
    assert all(hashlib.sha256(p.read_bytes()).digest() == before[p.name] for p in fixtures.iterdir())
    # Extension aliases, uppercase names and recursive folder import use one path.
    nested = tmp_path / '音乐' / '子文件夹'; nested.mkdir(parents=True)
    for source, name in [('dsd-64.dff', 'test.DSDIFF'), ('audio.m4a', 'book.M4B'), ('audio.aiff', 'test.AIF')]:
        shutil.copyfile(fixtures / source, nested / name)
    assert len(scan_library(nested.parent, tmp_path / 'alias-covers')[0]) == 3


def test_corrupt_dsd_is_skipped_without_blocking_other_tracks(fixtures, tmp_path):
    bad = tmp_path / 'broken.dsf'; bad.write_bytes(b'DSD bad header')
    tracks, errors = scan_library(None, tmp_path / 'covers', [bad, fixtures / 'dsd-64.dsf'])
    assert len(errors) == 1 and len(tracks) == 1


def test_unknown_bit_depth_and_container_do_not_claim_lossless():
    t = Track('fake.wav', '', '', '', 1, codec='ac-3', rate=48000)
    assert not t.is_lossless and '无损' not in t.quality
    t.codec = 'tta'
    assert '16 bit' not in t.quality and '0 kHz' not in t.quality
    t.codec = 'wavpack hybrid'
    assert not t.is_lossless


def test_real_gui_import_and_playback(fixtures, tmp_path):
    import json, time
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QEventLoop, QTimer
    from musicdesk.appearance import create_application
    from musicdesk.core import Store
    from musicdesk.window import MusicWindow
    from musicdesk.verification import start_audio
    app = QApplication.instance() or create_application([])
    Store(tmp_path / 'profile').set('library', str(tmp_path / 'empty'))
    window = MusicWindow(Path(r'D:\AppleMusicDecrypt-Windows'), tmp_path / 'profile'); window.show()
    output = tmp_path / 'playback'
    start_audio(window, output, fixtures)
    deadline = time.monotonic() + 180
    try:
        while not (output / 'report.json').exists() and time.monotonic() < deadline:
            loop = QEventLoop(); QTimer.singleShot(200, loop.quit); loop.exec()
        report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
        assert report['ok'], report
        assert report['tested'] == 24 and report['original_files_unchanged']
    finally:
        window.tray.exit(); app.processEvents()


@pytest.mark.parametrize('exponent,multiple', [(2, 64), (3, 128), (4, 256)])
def test_dsd_wavpack_source_rate_and_duration(tmp_path, exponent, multiple):
    import struct
    from musicdesk.core import audio_codec
    import mutagen
    # Valid WavPack header metadata only; playback is covered by real fixtures.
    samples = 44100 * multiple // 8 * 2
    metadata = bytes([0x0e, 1, exponent, 0])
    header = struct.pack('<4sIHBBIIIII', b'wvpk', 24 + len(metadata), 0x410, 0, 0,
                         samples, 0, samples, 0x961c1800, 0)
    path = tmp_path / 'source.wv'; path.write_bytes(header + metadata)
    audio = mutagen.File(path)
    assert audio_codec(audio, path) == 'dsd'
    assert audio.info.sample_rate == 44100 * multiple and audio.info.length == 2
    # A truncated metadata entry cannot make the scanner hang or read past it.
    path.write_bytes(header + metadata[:2])
    with pytest.raises(ValueError): audio_codec(audio, path)
