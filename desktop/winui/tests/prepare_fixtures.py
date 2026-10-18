"""Small silent audio and metadata fixtures; never touches the real profile."""
from pathlib import Path
import json
import sys
import wave
from PIL import Image, ImageDraw
from mutagen.wave import WAVE
from mutagen.id3 import TIT2, TPE1, TALB, TPE2, TDRC, TRCK, APIC

root = Path(__file__).resolve().parents[2]
target = root / "qa/winui-smoke"
music = target / "music"
profile = target / "profile"
profile.mkdir(parents=True, exist_ok=True)
paths = []
for index, (artist, album, color) in enumerate([
    ("测试艺人 Alpha", "微光 · 测试专辑", "#825a9a"), ("测试艺人 Beta", "静夜听雨", "#425d6b"),
    ("Test Ensemble", "Silver Lines", "#c0b9a2"), ("测试艺人 Alpha", "另一个版本", "#977356"),
    ("Test Ensemble", "Clouds", "#65715b"), ("测试艺人 Beta", "Rosé", "#9b425e")]):
    folder = music / album
    folder.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (500, 500), color)
    draw = ImageDraw.Draw(image)
    for n in range(6): draw.ellipse((50+n*12, 50+n*12, 450-n*12, 450-n*12), outline="#ffffff", width=2)
    draw.text((100, 225), f"ALBUM 0{index+1}", fill="white", font_size=40)
    cover = folder / "cover.jpg"
    image.save(cover)
    for number in range(1, 3):
        path = folder / f"{number:02}.wav"
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(2); audio.setsampwidth(2); audio.setframerate(44100); audio.writeframes(b"\0" * 44100 * 4 * 5)
        audio = WAVE(path); audio.add_tags()
        for frame in [TIT2(encoding=3, text=[f"静音测试 {index+1}-{number}"]), TPE1(encoding=3, text=[artist]),
                      TALB(encoding=3, text=[album]), TPE2(encoding=3, text=[artist]), TDRC(encoding=3, text=[str(2020+index)]), TRCK(encoding=3, text=[str(number)]),
                      APIC(encoding=3, mime="image/jpeg", type=3, data=cover.read_bytes())]: audio.tags.add(frame)
        audio.save(); paths.append(str(path))
        path.with_suffix(".lrc").write_text("[00:00.00]歌词平滑滚动测试\n[00:01.00]第一行歌词\n[00:01.00]Translation of the first line\n[00:02.00]点击歌词可以跳转\n[00:03.00]原生 WinUI 动画\n[00:04.00]最后一行", encoding="utf-8")
preferences = {"library": str(music), "last_track": paths[0], "playback_queue": paths[:4], "favourites": [paths[0], paths[4]], "recently_played": [paths[0], paths[6]],
    "volume": 0, "audio_output": {"mode": "shared", "device": "", "dsd": "pcm"},
    "playlists": [{"id": "playlist:test", "name": "测试歌单", "entries": [{"path": p, "title": Path(p).stem} for p in paths[:3]]}],
    "jobs": [{"id": "fixture-job", "url": "https://music.apple.com/cn/song/test/123", "codec": "alac", "state": "DONE", "title": "测试下载任务", "artist": "测试艺人", "completed": 1, "total": 1}],
    "unknown_legacy_key": {"keep": True}}
(profile / "preferences.json").write_text(json.dumps(preferences, ensure_ascii=False, indent=2), encoding="utf-8")
print(profile)
