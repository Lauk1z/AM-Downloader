from pathlib import Path
import pytest
import tomlkit
from musicdesk.core import Store, duration_text, redact, update_config, validate_links, scan_library


def test_links_validate_before_network():
    url = "https://music.apple.com/cn/song/hotel-california/635770202"
    assert validate_links(url + "\n" + url) == [url]
    for value in ("dl -c aac " + url, "file:///C:/windows", "https://music.apple.com.evil.test/cn/song/123", "https://user:pass@evil.test/song/123", ""):
        with pytest.raises(ValueError): validate_links(value)


def test_settings_preserve_unrelated_values_and_comments(tmp_path):
    raw = '# preserve this\n[region]\nlanguage="zh-Hant-HK"\n[download]\nmaxBitDepth=24 # retain\nmaxSampleRate=192000\n[localInstance]\nenable=true\nstartArgs="-host 0.0.0.0 -port 32767 -debug"\n'
    path = tmp_path / "config.toml"; path.write_text(raw)
    update_config(tmp_path, {("region", "language"): "zh-Hans-CN", ("download", "maxBitDepth"): 16})
    current = path.read_text(); parsed = tomlkit.parse(current)
    assert "# preserve this" in current and "# retain" in current
    assert parsed["localInstance"]["enable"] is True
    assert parsed["download"]["maxSampleRate"] == 192000
    assert parsed["region"]["language"] == "zh-Hans-CN"
    assert next(tmp_path.glob("config.musicdesk-backup-*.toml")).read_text() == raw
    with pytest.raises(ValueError): update_config(tmp_path, {("localInstance", "enable"): False})


def test_store_survives_restart(tmp_path):
    store = Store(tmp_path); store.set("favourites", ["D:/音乐/曲目.m4a"])
    assert Store(tmp_path).get("favourites") == ["D:/音乐/曲目.m4a"]
    assert not (tmp_path / "preferences.tmp").exists()


def test_redact_secrets():
    value = redact('Music-Token: SECRET password="PASSWORD" person@example.org https://host/path?token=KEY')
    assert all(secret not in value for secret in ("SECRET", "PASSWORD", "person@example.org", "KEY"))


def test_bad_audio_does_not_abort_library_scan(tmp_path):
    music = tmp_path / "library"; music.mkdir(); (music / "bad.m4a").write_bytes(b"not music")
    tracks, errors = scan_library(music, tmp_path / "cache")
    assert tracks == []
    assert duration_text(366) == "6:06"


def test_external_audio_metadata_duplicates_and_original_preserved(tmp_path):
    import hashlib
    import wave
    from mutagen.wave import WAVE
    from mutagen.id3 import TIT2, TPE1, TALB, TRCK, APIC
    folder = tmp_path / "外部 Audio"; folder.mkdir()
    source = folder / "My Song.WAV"
    with wave.open(str(source), "wb") as audio:
        audio.setparams((1, 2, 8000, 0, "NONE", "not compressed")); audio.writeframes(b"\0\0" * 16000)
    audio = WAVE(source); audio.add_tags()
    audio.tags.add(TIT2(encoding=3, text=["本地歌曲"]))
    audio.tags.add(TPE1(encoding=3, text=["本地艺人"]))
    audio.tags.add(TALB(encoding=3, text=["本地专辑"]))
    audio.tags.add(TRCK(encoding=3, text=["3/10"]))
    audio.tags.add(APIC(mime="image/png", type=3, data=b"cover bytes")); audio.save()
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    bad = folder / "bad.mp3"; bad.write_bytes(b"invalid audio")
    tracks, errors = scan_library(folder, tmp_path / "cache", [source, source, bad])
    assert len(tracks) == 1 and len(errors) == 1
    assert (tracks[0].title, tracks[0].artist, tracks[0].album, tracks[0].number) == ("本地歌曲", "本地艺人", "本地专辑", 3)
    assert Path(tracks[0].cover).read_bytes() == b"cover bytes"
    assert tracks[0].duration == 2 and tracks[0].rate == 8000
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert scan_library(tmp_path / "missing library", tmp_path / "cache", [source])[0] == tracks
