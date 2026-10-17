"""Persistent ordered references and local Extended M3U interchange."""
import os
import math
import re
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

from .core import IMPORT_EXTENSIONS


def source_path(path):
    return re.sub(r"#amtrack=(?:\d+|(?:stereo|multichannel)-\d+)$", "", path)


def entry(track):
    return {"path": track.path, "title": track.title, "artist": track.artist, "duration": track.duration}


def move_entries(entries, rows, destination):
    rows = sorted(set(rows))
    selected = set(rows)
    moving = [value for index, value in enumerate(entries) if index in selected]
    remaining = [value for index, value in enumerate(entries) if index not in selected]
    destination = max(0, min(len(entries), destination)) - sum(row < destination for row in rows)
    return remaining[:destination] + moving + remaining[destination:]


class Playlists:
    def __init__(self, store):
        self.store = store
        self.items = store.get("playlists", [])

    def get(self, key):
        return next((item for item in self.items if item["id"] == key), None)

    def save(self):
        self.store.set("playlists", self.items)

    def create(self, name, entries=()):
        item = {"id": "playlist:" + uuid.uuid4().hex, "name": name.strip() or "新建歌单", "entries": list(entries)}
        self.items.append(item); self.save()
        return item


def read_m3u(filename):
    file = Path(filename).resolve()
    raw = file.read_bytes()
    encodings = ("utf-16",) if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else ("utf-8-sig", "gb18030", "cp1252")
    for encoding in encodings:
        try: text = raw.decode(encoding); break
        except UnicodeDecodeError: continue
    else: raise ValueError("无法识别歌单文本编码，请另存为 UTF-8 M3U8。")
    name, entries, warnings = file.stem, [], []
    title, duration, virtual = "", 0, ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line: continue
        if line.startswith("#PLAYLIST:"): name = line.partition(":")[2].strip() or name
        elif line.startswith("#EXTINF:"):
            details, _, title = line.partition(":")[2].partition(",")
            try: duration = max(0, float(details))
            except ValueError: duration = 0
            if not math.isfinite(duration): duration = 0
        elif line.startswith("#EXT-AM-TRACK:"):
            virtual = line.partition(":")[2].strip()
        elif not line.startswith("#"):
            if line.lower().startswith("file:"):
                parsed = urlparse(line)
                line = url2pathname(("//" + parsed.netloc if parsed.netloc and parsed.netloc != "localhost" else "") + parsed.path)
            if re.match(r"^[a-zA-Z][\w+.-]*://", line):
                warnings.append("跳过网络地址：" + line)
            else:
                path = Path(line)
                path = (file.parent / path).resolve() if not path.is_absolute() else path.resolve()
                logical = str(path)
                if virtual and re.fullmatch(r"\d+|(?:stereo|multichannel)-\d+", virtual): logical += "#amtrack=" + virtual
                if Path(source_path(logical)).suffix.lower() in IMPORT_EXTENSIONS:
                    entries.append({"path": logical, "title": title or Path(source_path(logical)).stem, "artist": "", "duration": duration})
                else: warnings.append("跳过不支持的文件：" + line)
            title, duration, virtual = "", 0, ""
    return name, entries, warnings


def write_m3u(filename, name, entries):
    file = Path(filename).resolve()
    if file.suffix.lower() not in {".m3u", ".m3u8"}: raise ValueError("请选择 .m3u 或 .m3u8 文件。")
    clean = lambda value: str(value).replace("\r", " ").replace("\n", " ")
    lines = ["#EXTM3U", "#PLAYLIST:" + clean(name)]
    for value in entries:
        logical = value["path"]; source = source_path(logical)
        caption = " - ".join(part for part in (value.get("artist"), value.get("title")) if part)
        lines.append(f'#EXTINF:{round(value.get("duration", 0))},{clean(caption)}')
        if logical != source: lines.append("#EXT-AM-TRACK:" + logical[len(source) + 9:])
        try: path = os.path.relpath(source, file.parent)
        except ValueError: path = source  # A different Windows drive cannot be relative.
        if path.startswith("#"): path = "." + os.sep + path
        lines.append(path)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8-sig", newline="\n", dir=file.parent, suffix=".tmp", delete=False) as stream:
            temp = Path(stream.name); stream.write("\n".join(lines) + "\n")
        temp.replace(file)
    finally:
        if temp and temp.exists(): temp.unlink()
