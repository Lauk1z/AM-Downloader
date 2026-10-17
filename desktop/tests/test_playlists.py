from pathlib import Path
import pytest

from musicdesk.core import Store
from musicdesk.playlists import Playlists, move_entries, read_m3u, write_m3u, source_path


def test_saved_playlists_preserve_identity_order_and_duplicates(tmp_path):
    store = Store(tmp_path / "profile"); store.set("favourites", ["untouched"])
    lists = Playlists(store)
    item = lists.create("夜晚", [{"path": "b.flac"}, {"path": "a.flac"}, {"path": "b.flac"}])
    item["name"] = "慢慢听"; lists.save()
    restored = Playlists(Store(store.directory))
    assert restored.get(item["id"]) == item
    assert Store(store.directory).get("favourites") == ["untouched"]


@pytest.mark.parametrize("rows,destination,expected", [
    ([0], 4, "bcda"), ([3], 0, "dabc"), ([1, 2], 4, "adbc"),
    ([0, 2], 4, "bdac"), ([1, 2], 2, "abcd"), ([0, 1, 2, 3], 0, "abcd")])
def test_reorder_uses_insertion_position_and_keeps_selection_order(rows, destination, expected):
    assert move_entries(list("abcd"), rows, destination) == list(expected)


@pytest.mark.parametrize("suffix", [".m3u", ".m3u8"])
def test_m3u_unicode_relative_paths_duplicates_and_virtual_tracks_roundtrip(tmp_path, suffix):
    file = tmp_path / ("夜晚" + suffix)
    paths = [tmp_path / "音乐 #1.flac", tmp_path / "#hello.mp3", tmp_path / "整轨.cue"]
    values = [{"path": str(paths[0]), "title": "歌曲,一", "duration": 32}, {"path": str(paths[1]), "title": "#片尾", "duration": 2},
              {"path": str(paths[2]) + "#amtrack=2", "title": "第二曲", "duration": 20},
              {"path": str(tmp_path / "碟.iso") + "#amtrack=stereo-1", "title": "DSD", "duration": 20}]
    values.append(values[0].copy())
    write_m3u(file, "夜晚\n歌单", values)
    name, result, warnings = read_m3u(file)
    assert not warnings and name == "夜晚 歌单"
    assert [value["path"] for value in result] == [value["path"] for value in values]
    assert [value["title"] for value in result] == [value["title"] for value in values]
    assert source_path(result[2]["path"]) == str(paths[2])
    text = file.read_text(encoding="utf-8-sig")
    assert str(tmp_path) not in text and "#EXT-AM-TRACK:2" in text
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "gb18030"])
def test_m3u_comments_file_urls_missing_and_remote_references(tmp_path, encoding):
    missing = tmp_path / "尚未找到.flac"
    file = tmp_path / "local.m3u"
    file.write_text(f"#EXTM3U\n# comment\n#EXTINF:40,测试\n{missing.as_uri()}\nhttps://example.com/remote.mp3\nnotes.txt\n../other.flac\n", encoding=encoding)
    _, values, warnings = read_m3u(file)
    assert values[0]["path"] == str(missing) and values[0]["title"] == "测试"
    assert values[1]["path"] == str(tmp_path.parent / "other.flac")
    assert len(warnings) == 2 and not missing.exists()


def test_export_refuses_audio_destination(tmp_path):
    file = tmp_path / "original.wav"; file.write_bytes(b"original")
    with pytest.raises(ValueError): write_m3u(file, "playlist", [])
    assert file.read_bytes() == b"original"
