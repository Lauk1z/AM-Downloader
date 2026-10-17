from pathlib import Path
import shutil
import struct
import subprocess
import wave

import mutagen
import pytest
from musicdesk.core import Track, scan_library
from musicdesk.discs import read_sacd, prepare_track
from musicdesk.metadata import save_album_edits, find_duplicates
from musicdesk.library_tools import matches_filters
from musicdesk.shuffle import ShuffleOrder
from disc_fixtures import sacd_image

FFMPEG = Path(__file__).resolve().parents[1] / "vendor/backend/deps/ffmpeg.exe"


def wav(path, seconds=2):
    with wave.open(str(path), "wb") as out:
        out.setparams((1, 2, 44100, 0, "NONE", "not compressed"))
        out.writeframes(struct.pack("<" + "h" * (44100 * seconds), *[index % 32767 for index in range(44100 * seconds)]))
    return path


def test_shuffle_rounds_and_back_do_not_redraw():
    order = ShuffleOrder(); paths = list("ABCDEFG")
    current = paths[0]; round_values = [current]
    for _ in range(6): current = order.step(paths, current); round_values.append(current)
    assert set(round_values) == set(paths) and len(set(round_values)) == 7
    for _ in range(100):
        last = current; values = []
        for _ in paths: current = order.step(paths, current); values.append(current)
        assert len(set(values)) == 7 and values[0] != last
    last = current; previous = order.step(paths, current, -1)
    assert order.step(paths, previous) == last
    assert order.step(["A", "A"], "A") == "A"
    assert order.step([], "") is None


def test_shuffle_queue_removal_keeps_unplayed_remainder():
    paths = list("ABCDEFG")
    order = ShuffleOrder(); current = "A"; visited = [current]
    for _ in range(2): current = order.step(paths, current); visited.append(current)
    removed = next(path for path in paths if path not in visited)
    paths.remove(removed)
    for _ in range(3): current = order.step(paths, current); visited.append(current)
    assert len(visited) == len(set(visited)) == 6 and set(visited) == set(paths)


def test_cue_index_scan_exclusion_and_exact_pcm_segment(tmp_path):
    source = wav(tmp_path / "完整音轨.wav")
    cue = tmp_path / "专辑.cue"
    cue.write_text('PERFORMER "Album Artist"\nTITLE "Disc"\nREM DATE 2020\nFILE "完整音轨.wav" WAVE\n TRACK 01 AUDIO\n TITLE "One"\n INDEX 01 00:00:00\n TRACK 02 AUDIO\n TITLE "Two"\n INDEX 01 00:01:00\n', encoding="utf-8-sig")
    profile = tmp_path / "profile"; cache = profile / "covers"
    tracks, errors = scan_library(tmp_path, cache)
    assert not errors and len(tracks) == 2
    assert [track.title for track in tracks] == ["One", "Two"]
    assert tracks[1].start == 1 and tracks[1].duration == 1 and tracks[1].year == 2020
    assert tracks[0].album_artist == "Album Artist"
    selected, _ = scan_library(tmp_path, cache, excluded_files=[tracks[0].path])
    assert len(selected) == 1 and selected[0].title == "Two"
    before = source.read_bytes()
    prepared = prepare_track(tracks[1], tmp_path / "audio-cache", FFMPEG)
    audio = mutagen.File(prepared); assert audio.info.length == 1 and audio.info.sample_rate == 44100
    raw = subprocess.run([str(FFMPEG), "-v", "error", "-i", prepared, "-f", "s16le", "-"], capture_output=True, check=True).stdout
    with wave.open(str(source), "rb") as original:
        original.setpos(44100); expected = original.readframes(44100)
    assert raw == expected and source.read_bytes() == before
    assert prepare_track(tracks[1], tmp_path / "audio-cache", FFMPEG) == prepared


def test_cue_invalid_index_keeps_original_audio(tmp_path):
    wav(tmp_path / "disc.wav")
    (tmp_path / "bad.cue").write_text('FILE "disc.wav" WAVE\nTRACK 01 AUDIO\nINDEX 01 01:00:00')
    tracks, errors = scan_library(tmp_path, tmp_path / "covers")
    assert len(errors) == 1 and len(tracks) == 1 and not tracks[0].container


def test_sacd_index_and_real_extractor_keep_generated_dsd(tmp_path):
    image = sacd_image(tmp_path / "模拟专辑.iso"); original = image.read_bytes()
    tracks = read_sacd(image)
    assert len(tracks) == 2 and tracks[1].title == "Track 2"
    assert tracks[1].duration == 1 and tracks[1].rate == 2822400 and tracks[1].year == 2024
    output = prepare_track(tracks[1], tmp_path / "cache", FFMPEG)
    audio = mutagen.File(output)
    assert audio.info.length == 1 and audio.info.sample_rate == 2822400 and audio.info.bits_per_sample == 1
    from musicdesk.playback import native_executable
    raw = tmp_path / "dsd.raw"
    subprocess.run([str(native_executable()), "--mode", "render", "--format", "dsd", "--rate", "2822400", "--channels", "2", "--file", output, "--output", str(raw)], check=True, capture_output=True)
    assert raw.read_bytes() == b"\x96" * (2822400 // 8 * 2)
    assert image.read_bytes() == original


def test_library_filters_editions_and_disc_sort(tmp_path):
    a = Track(str(tmp_path / "Edition A/one.flac"), "Song", "Singer", "Album", 60, codec="flac", rate=96000, bits=24, year=2021, album_artist="Band", disc=2, number=1)
    b = Track(str(tmp_path / "Edition B/one.flac"), "Song", "Other Singer", "Album", 60, album_artist="Band", disc=1, number=9)
    assert a.album_key != b.album_key
    a.edition = b.edition = "Original"
    assert a.album_key == b.album_key and b.order < a.order
    assert matches_filters(a, {"rate": 96000, "year": 2021, "bits": 24, "format_name": "FLAC"})
    assert not matches_filters(a, {"year": 2020})


@pytest.mark.parametrize("extension,codec", [("wav", "pcm_s24le"), ("flac", "flac"), ("m4a", "alac"), ("ogg", "libvorbis"), ("mp3", "libmp3lame"), ("wv", "wavpack"), ("wma", "wmav2")])
def test_metadata_roundtrip_and_original_backup(tmp_path, extension, codec):
    source = tmp_path / ("track." + extension)
    subprocess.run([str(FFMPEG), "-v", "error", "-f", "lavfi", "-i", "sine=duration=1", "-c:a", codec, str(source)], check=True, capture_output=True)
    profile = tmp_path / "profile"; tracks, _ = scan_library(None, profile / "covers", [source])
    original = source.read_bytes()
    decode = lambda path: subprocess.run([str(FFMPEG), "-v", "error", "-i", str(path), "-f", "f64le", "-"], capture_output=True, check=True).stdout
    samples = decode(source)
    edits = {"title": "新歌名", "artist": "艺人", "album": "专辑", "album_artist": "共同艺人", "year": 2022, "number": 3, "disc": 2, "edition": "2022 母带"}
    result = save_album_edits(tracks, [edits], profile)
    assert result["files"] == 1 and Path(result["backups"][0]).read_bytes() == original
    updated, errors = scan_library(None, profile / "covers", [source])
    assert not errors
    for field, value in edits.items(): assert getattr(updated[0], field) == value, field
    assert decode(source) == samples


def test_batch_failed_stage_never_changes_originals(tmp_path, monkeypatch):
    from musicdesk import metadata
    paths = [wav(tmp_path / f"{index}.wav") for index in range(2)]
    tracks, _ = scan_library(None, tmp_path / "profile/covers", paths)
    original = [path.read_bytes() for path in paths]
    actual = metadata.write_tags
    def fail(path, changes, cover):
        if changes["title"] == "bad": raise ValueError("deliberate failure")
        return actual(path, changes, cover)
    monkeypatch.setattr(metadata, "write_tags", fail)
    with pytest.raises(ValueError): save_album_edits(tracks, [{"title": "good"}, {"title": "bad"}], tmp_path / "profile")
    assert [path.read_bytes() for path in paths] == original
    assert not list(tmp_path.glob("*.am-edit-*"))


def test_virtual_edits_and_duplicate_hashes(tmp_path):
    source = wav(tmp_path / "one.wav"); copy = tmp_path / "two.wav"; shutil.copy2(source, copy)
    tracks, _ = scan_library(None, tmp_path / "profile/covers", [source, copy])
    result = find_duplicates(tracks)
    assert result[0][0] == "文件完全相同" and len(result[0][1]) == 2
    image = sacd_image(tmp_path / "disc.iso")
    tracks = read_sacd(image); before = image.read_bytes()
    save_album_edits(tracks, [{"title": "Local Title"}, {}], tmp_path / "profile")
    updated, _ = scan_library(None, tmp_path / "profile/covers", [image])
    assert updated[0].title == "Local Title" and image.read_bytes() == before


def test_cover_replacement_previews_new_art_and_preserves_audio(tmp_path):
    from PIL import Image
    source = wav(tmp_path / "song.wav")
    Image.new("RGB", (20, 20), "blue").save(tmp_path / "cover.png")
    image = tmp_path / "new.png"; Image.new("RGB", (40, 40), "red").save(image)
    profile = tmp_path / "profile"
    tracks, _ = scan_library(None, profile / "covers", [source])
    save_album_edits(tracks, [{}], profile, str(image))
    updated, _ = scan_library(None, profile / "covers", [source])
    assert Image.open(updated[0].cover).getpixel((0, 0)) == (255, 0, 0)
    assert Image.open(tmp_path / "cover.png").getpixel((0, 0)) == (0, 0, 255)
    assert mutagen.File(source).tags.getall("APIC")[0].type == 3
