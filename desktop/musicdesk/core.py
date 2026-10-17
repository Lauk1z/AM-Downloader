"""Local library and preferences. No downloader or account state is copied."""
from dataclasses import dataclass
from itertools import chain
from pathlib import Path
import json
import os
import re
import time
from urllib.parse import urlparse

import mutagen
import tomlkit
from .runtime import code_root

CODECS = {"alac": "ALAC · 无损", "aac": "AAC · 256 kbps", "ec3": "Dolby Atmos", "ac3": "Dolby Digital", "aac-binaural": "AAC · 空间音频", "aac-downmix": "AAC · 混音", "aac-legacy": "AAC · 兼容模式"}
STAGES = {"queued": "等待开始", "starting": "启动本地后端", "resolving": "读取曲目信息", "WAITING": "获取播放地址", "awaiting_format": "等待确认下载格式", "DOWNLOADING": "下载中", "DECRYPTING": "解密中", "DONE": "已完成", "FAILED": "失败", "cancelled": "已取消"}
AUDIO_EXTENSIONS = {
    ".m4a", ".m4b", ".mp3", ".mp2", ".flac", ".wav", ".aac", ".opus", ".ogg", ".oga", ".spx",
    ".dsf", ".dff", ".dsdiff", ".aif", ".aiff", ".aifc", ".ape", ".wv", ".tta", ".tak",
    ".wma", ".mpc", ".mpp", ".mp+", ".ac3", ".eac3", ".ec3",
}


IMPORT_EXTENSIONS = AUDIO_EXTENSIONS | {".cue", ".iso"}


def path_key(path):
    return os.path.normcase(str(Path(path).resolve()))


def trash_audio(path):
    from PySide6.QtCore import QFile
    path = Path(path)
    if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
        raise ValueError("音频文件不存在或不是受支持的文件，请使用「从列表中删除」。")
    audio = QFile(str(path))
    if not QFile.supportsMoveToTrash() or not audio.moveToTrash():
        raise OSError("无法移入回收站：" + audio.errorString())


def validate_links(text):
    urls = text.split()
    if not urls:
        raise ValueError("请粘贴 Apple Music 的歌曲、专辑、歌单或艺人链接。")
    result = []
    for value in urls:
        parsed = urlparse(value)
        if parsed.scheme != "https" or parsed.hostname not in {"music.apple.com", "geo.music.apple.com"}:
            raise ValueError("请输入完整的 https://music.apple.com/ 链接；无需输入 dl 命令。")
        if not any(part in parsed.path.split("/") for part in ("song", "album", "playlist", "artist")):
            raise ValueError("这个链接不是歌曲、专辑、歌单或艺人页面。")
        if value not in result:
            result.append(value)
    return result


def redact(text):
    text = re.sub(r"\x1b\[[0-9;]*m", "", str(text))
    text = re.sub(r"(?i)(music-token|authorization|password|cookie|two_step_code)([\s:=\"']+)[^\s,\"']+", r"\1\2[已隐藏]", text)
    text = re.sub(r"https?://\S+", "[链接已隐藏]", text)
    return re.sub(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}", "[账号已隐藏]", text)


def duration_text(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def valid_backend(root):
    root = Path(root)
    try: code = code_root(root)
    except FileNotFoundError: return False
    return (code / "main.py").is_file() and (code / "src" / "rip.py").is_file() and (root / "config.toml").is_file()


def python_path(root):
    root = code_root(root)
    for relative in (".venv/python.exe", ".venv/Scripts/python.exe"):
        path = Path(root) / relative
        if path.is_file():
            return path
    raise FileNotFoundError("所选安装目录中没有找到原程序的 Python 环境。")


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "preferences.json"
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.update({key: value})

    def update(self, values):
        self.data.update(values)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)


def read_config(root):
    return tomlkit.parse((Path(root) / "config.toml").read_text(encoding="utf-8-sig"))


def update_config(root, changes):
    path = Path(root) / "config.toml"
    raw = path.read_bytes()
    document = tomlkit.parse(raw.decode("utf-8-sig"))
    allowed = {("region", "language"), ("download", "maxSampleRate"), ("download", "maxBitDepth")}
    for (section, key), value in changes.items():
        if (section, key) not in allowed:
            raise ValueError("不支持的配置项")
        document[section][key] = value
    backup = path.with_name(f"config.musicdesk-backup-{time.time_ns()}.toml")
    backup.write_bytes(raw)
    temp = path.with_suffix(".musicdesk.tmp")
    temp.write_text(tomlkit.dumps(document), encoding="utf-8")
    temp.replace(path)


@dataclass
class Track:
    path: str
    title: str
    artist: str
    album: str
    duration: float
    cover: str = ""
    codec: str = ""
    rate: int = 0
    bits: int = 0
    number: int = 0
    modified: float = 0
    album_artist: str = ""
    year: int = 0
    disc: int = 0
    edition: str = ""
    container: str = ""
    source_path: str = ""
    start: float = 0
    source_index: int = 0
    area: str = ""

    @property
    def file_path(self):
        return self.container or self.path

    @property
    def format_name(self):
        return "SACD ISO" if self.area else "CUE" if self.container else Path(self.path).suffix[1:].upper()

    @property
    def album_key(self):
        parent = Path(self.file_path).parent
        if re.fullmatch(r"(?i)(cd|disc|disk)[ _-]*\d+", parent.name): parent = parent.parent
        version = self.edition or path_key(parent)
        return self.album, self.album_artist or self.artist, version

    @property
    def order(self):
        return self.disc, self.number, self.title.casefold()

    @property
    def is_dsd(self):
        return self.codec.lower() in {"dsd", "dst"}

    @property
    def is_lossless(self):
        return self.is_dsd or self.codec.lower() in {"alac", "flac", "pcm", "ape", "wavpack", "tta", "tak", "wma lossless"}

    @property
    def quality(self):
        if self.is_dsd:
            multiple = self.rate // 44100 if self.rate and self.rate % 44100 == 0 else 0
            name = f"DSD{multiple}" if multiple else "DSD"
            if self.codec.lower() == "dst": name += " (DST)"
            return name + (f" · 1 bit / {self.rate / 1000000:g} MHz" if self.rate else "")
        details = " / ".join(value for value in (f"{self.bits} bit" if self.bits else "", f"{self.rate / 1000:g} kHz" if self.rate else "") if value)
        if self.is_lossless:
            label = "高解析度无损" if self.rate > 48000 or self.bits > 16 else "无损"
            return label + (" · " + details if details else "")
        return self.codec.upper() or Path(self.path).suffix[1:].upper()

    @property
    def playback_details(self):
        if self.is_dsd:
            return self.quality + "\n可通过音频设置选择 DSD 解码为 PCM、原生 DSD 或 DoP；实际输出见播放器状态。"
        return self.quality


def audio_codec(audio, path):
    """Identify the encoding, not just the container's filename extension."""
    kind = type(audio).__name__
    names = {"DSF": "dsd", "DSDIFF": (getattr(audio.info, "compression", None) or "dsd").lower(),
             "FLAC": "flac", "OggFLAC": "flac", "OggVorbis": "vorbis", "OggOpus": "opus",
             "OggSpeex": "speex", "MonkeysAudio": "ape", "WavPack": "wavpack", "TrueAudio": "tta",
             "TAK": "tak", "Musepack": "musepack"}
    if kind == "WAVE":
        from mutagen.wave import _WaveFile
        with path.open("rb") as stream: fmt = _WaveFile(stream)["fmt"].read()
        code = int.from_bytes(fmt[:2], "little")
        if code == 65534: code = int.from_bytes(fmt[24:26], "little")
        return "pcm" if code in {1, 3} else "wav"
    if kind == "AIFF":
        from mutagen.aiff import AIFFFile
        with path.open("rb") as stream: common = AIFFFile(stream)["COMM"].read()
        return "pcm" if len(common) == 18 or common[18:22] in {b"NONE", b"sowt", b"fl32", b"fl64", b"FL32", b"FL64"} else "aifc"
    if kind == "WavPack":
        with path.open("rb") as stream: header = stream.read(32)
        flags = int.from_bytes(header[24:28], "little")
        if flags & 0x80000000:
            # Mutagen uses a fixed DSD64 byte-rate multiplier. Read WavPack's
            # DSD metadata for other rates, then display the one-bit source rate.
            byte_rate = wavpack_dsd_rate(path, header, audio.info.sample_rate // 4)
            audio.info.length *= audio.info.sample_rate / byte_rate
            audio.info.sample_rate = byte_rate * 8
            return "dsd"
        if flags & 8: return "wavpack hybrid"
    if kind == "ASF":
        return "wma lossless" if "lossless" in getattr(audio.info, "codec_type", "").lower() else "wma"
    return names.get(kind, getattr(audio.info, "codec", path.suffix[1:])).lower()


def wavpack_dsd_rate(path, header, base_rate):
    end = int.from_bytes(header[4:8], "little") + 8
    if end > path.stat().st_size: raise ValueError("WavPack 音频块不完整")
    multiplier = 4
    with path.open("rb") as stream:
        stream.seek(32)
        while stream.tell() < end:
            tag = stream.read(1)[0]
            length = stream.read(3 if tag & 0x80 else 1)
            size = int.from_bytes(length, "little") * 2
            start = stream.tell()
            if len(length) != (3 if tag & 0x80 else 1) or start + size > end:
                raise ValueError("WavPack 元数据不完整")
            actual_size = size - bool(tag & 0x40)
            if tag & 0x3f == 0x0e and actual_size >= 2:
                multiplier = 1 << (stream.read(1)[0] & 0x1f)
            elif tag & 0x3f == 0x27 and actual_size >= 3:
                base_rate = int.from_bytes(stream.read(3), "little")
            stream.seek(start + size)
    rate = base_rate * multiplier
    if not 0 < rate < 2147483647: raise ValueError("WavPack 采样率无效")
    return rate


def scan_library(folder, cache_folder, extra_files=(), excluded_files=()):
    folder, cache_folder = Path(folder) if folder else None, Path(cache_folder)
    cache_folder.mkdir(parents=True, exist_ok=True)
    tracks, errors = [], []
    candidates = list(dict.fromkeys(str(Path(path).resolve()) for path in chain(folder.rglob("*") if folder and folder.is_dir() else (), extra_files)))
    containers = [Path(path) for path in candidates if Path(path).suffix.lower() in {".cue", ".iso"} and Path(path).is_file()]
    covered = set()
    for container in containers:
        try:
            from .discs import read_cue, read_sacd
            found = read_cue(container, cache_folder) if container.suffix.lower() == ".cue" else read_sacd(container)
            tracks.extend(track for track in found if path_key(track.path) not in {path_key(value) for value in excluded_files})
            covered.update(path_key(track.source_path) for track in found if track.source_path)
        except (OSError, ValueError, mutagen.MutagenError) as error: errors.append(f"{container.name}: {error}")
    seen = {path_key(path) for path in excluded_files}
    for path in candidates:
        path = Path(path)
        if path.suffix.lower() not in AUDIO_EXTENSIONS or ".am-edit-" in path.name or not path.is_file():
            continue
        key = path_key(path)
        if key in seen or key in covered: continue
        seen.add(key)
        try:
            audio = mutagen.File(path)
            if audio is None:
                errors.append(f"{path.name}: 无法识别音频格式")
                continue
            codec = audio_codec(audio, path)
            tags = audio.tags or {}
            tag_keys = {name.casefold(): name for name in tags.keys()}
            def first(*names, default=""):
                for name in names:
                    key = tag_keys.get(name.casefold())
                    value = tags[key] if key is not None else None
                    if value:
                        value = value[0] if isinstance(value, list) else value
                        return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
                return default
            cover = next((str(path.parent / name) for name in ("cover.jpg", "cover.png", "cover.jpeg", "cover.webp") if (path.parent / name).is_file()), "")
            if not cover:
                data = (tags.get("covr") or [None])[0]
                if not data and getattr(audio, "pictures", None):
                    data = audio.pictures[0].data
                if not data and hasattr(tags, "getall") and tags.getall("APIC"):
                    data = tags.getall("APIC")[0].data
                if data:
                    import hashlib
                    cover_path = cache_folder / (hashlib.sha256(data).hexdigest()[:24] + ".jpg")
                    if not cover_path.exists():
                        cover_path.write_bytes(data)
                    cover = str(cover_path)
            number = re.match(r"\d+", first("tracknumber", "TRCK", "Track", "WM/TrackNumber", default="0").strip())
            number = (tags.get("trkn") or [(0, 0)])[0][0] if "trkn" in tags else int(number[0]) if number else 0
            tracks.append(Track(str(path), first("\xa9nam", "title", "TIT2", default=path.stem), first("\xa9ART", "artist", "TPE1", "Author", default="未知艺人"), first("\xa9alb", "album", "TALB", "WM/AlbumTitle", default=path.parent.name), getattr(audio.info, "length", 0), cover, codec, 48000 if codec == "opus" else getattr(audio.info, "sample_rate", 0), getattr(audio.info, "bits_per_sample", 0), number, path.stat().st_mtime,
                first("aART", "albumartist", "Album Artist", "TPE2", "WM/AlbumArtist"),
                int((re.search(r"\d{4}", first("©day", "date", "year", "TDRC", "TYER", "WM/Year")) or ["0"])[0]),
                (tags.get("disk") or [(0, 0)])[0][0] if "disk" in tags else int((re.match(r"\d+", first("discnumber", "Disc", "TPOS", "WM/PartOfSet", default="0")) or ["0"])[0]),
                first("----:com.apple.iTunes:VERSION", "version", "TXXX:VERSION", "WM/Version")))
        except (OSError, ValueError, TypeError, mutagen.MutagenError) as error:
            errors.append(f"{path.name}: {error}")
    overrides_path = cache_folder.parent / "metadata-overrides.json"
    try: overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    except (OSError, ValueError): overrides = {}
    for track in tracks:
        for key, value in overrides.get(path_key(track.path), {}).items():
            if key in {"title", "artist", "album", "album_artist", "year", "disc", "number", "edition", "cover"}: setattr(track, key, value)
    return sorted(tracks, key=lambda track: track.modified, reverse=True), errors
