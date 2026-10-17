"""Read-only CUE/SACD indexing and on-demand, lossless track preparation."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time

from .core import Track, path_key, scan_library


def read_cue(path, cache):
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "gb18030", "cp1252"):
        try: text = raw.decode(encoding); break
        except UnicodeError: continue
    else: raise ValueError("无法识别 CUE 文本编码")
    album, entries, source, current = {}, [], None, None
    for line in text.splitlines():
        match = re.match(r'\s*(\w+)\s+(.*)', line)
        if not match: continue
        command, value = match[1].upper(), match[2].strip()
        target = current if current is not None else album
        if command == "FILE":
            name = re.match(r'"([^"]+)"|([^\s]+)', value)
            if not name: raise ValueError("CUE 的 FILE 无效")
            source = (Path(path).parent / (name[1] or name[2])).resolve()
            current = None
        elif command == "TRACK":
            number, kind = value.split()[:2]
            if kind.upper() != "AUDIO": raise ValueError("仅支持音频 CUE")
            if source is None: raise ValueError("CUE 缺少 FILE")
            current = {"number": int(number), "source": source}; entries.append(current)
        elif command == "INDEX" and current is not None and value.startswith("01 "):
            minute, second, frame = map(int, value.split()[1].split(":"))
            if second >= 60 or frame >= 75: raise ValueError("CUE 时间索引无效")
            current["start"] = minute * 60 + second + frame / 75
        elif command in {"TITLE", "PERFORMER"}: target[command] = value.strip('"')
        elif command == "REM":
            key, _, item = value.partition(" ")
            if key.upper() in {"DATE", "DISCNUMBER"}: target[key.upper()] = item.strip('"')
    if not entries: raise ValueError("CUE 中没有音轨")
    sources, result = {}, []
    for item in entries:
        source = item["source"]
        if source not in sources:
            if source.suffix.lower() in {".cue", ".iso"}: raise ValueError("CUE 不能引用另一个索引或镜像")
            found, errors = scan_library(None, cache, [source])
            if not found: raise ValueError(f"CUE 音频无法读取：{source.name} " + "; ".join(errors))
            sources[source] = found[0]
    used = set()
    for index, item in enumerate(entries):
        base = sources[item["source"]]
        start = item.get("start")
        following = next((entry for entry in entries[index + 1:] if entry["source"] == item["source"]), None)
        end = following.get("start") if following else base.duration
        if start is None or end is None or start < 0 or not start < end <= base.duration + .05:
            raise ValueError("CUE 索引缺失、顺序错误或超过音频时长")
        if item["number"] in used: raise ValueError("CUE 音轨编号重复")
        used.add(item["number"])
        result.append(replace(base, path=str(path) + f"#amtrack={item['number']}",
            title=item.get("TITLE", f"音轨 {item['number']:02d}"),
            artist=item.get("PERFORMER", album.get("PERFORMER", base.artist)),
            album=album.get("TITLE", base.album), album_artist=album.get("PERFORMER", base.album_artist),
            year=int((re.search(r"\d{4}", album.get("DATE", "")) or [str(base.year)])[0]),
            disc=int(album.get("DISCNUMBER", base.disc) or 0), number=item["number"],
            container=str(path), source_path=str(item["source"]), start=start, duration=end - start,
            modified=max(base.modified, Path(path).stat().st_mtime)))
    return result


def read_sacd(path):
    """Read bounded Scarlet Book TOCs (layout documented by libsacd)."""
    path = Path(path)
    def number(data, offset, length=2): return int.from_bytes(data[offset:offset + length], "big")
    def string(data, offset, charset):
        if not offset: return ""
        if not 0 <= offset < len(data): raise ValueError("SACD 文本偏移无效")
        end = data.find(b"\0", offset)
        if end < 0: raise ValueError("SACD 文本没有结束标记")
        return data[offset:end].decode(charset, errors="replace").strip()
    charsets = ("ascii", "ascii", "latin1", "shift_jis", "euc_kr", "gb2312", "big5", "latin1")
    with path.open("rb") as stream:
        stride, skip = 2048, 0
        stream.seek(510 * stride)
        if stream.read(8) != b"SACDMTOC":
            stride, skip = 2064, 12
            stream.seek(510 * stride + skip)
            if stream.read(8) != b"SACDMTOC": raise ValueError("不是受支持的 SACD ISO 镜像")
        def blocks(start, count):
            if not 0 < count <= 96 or (start + count) * stride > path.stat().st_size:
                raise ValueError("SACD 目录超出镜像范围")
            result = []
            for sector in range(start, start + count):
                stream.seek(sector * stride + skip); result.append(stream.read(2048))
            return b"".join(result)
        master = blocks(510, 1)
        charset = charsets[master[138] & 7]
        text = blocks(511, 1)
        title = artist = ""
        if text[:8] == b"SACDText":
            title = string(text, number(text, 16), charset) or string(text, number(text, 32), charset)
            artist = string(text, number(text, 18), charset) or string(text, number(text, 34), charset)
        result = []
        for offset in (64, 72):
            address = number(master, offset, 4)
            if not address: continue
            toc = blocks(address, 1)
            if toc[:8] not in {b"TWOCHTOC", b"MULCHTOC"}: raise ValueError("SACD 音区目录无效")
            area = "stereo" if toc[:8] == b"TWOCHTOC" else "multichannel"
            count = toc[69]
            if not count: continue
            data = blocks(address, number(toc, 10))
            charset = charsets[toc[90] & 7]
            texts = durations = None
            for at in range(2048, len(data), 2048):
                block = data[at:at + 2048]
                if block[:8] == b"SACDTTxt" and texts is None: texts = block
                if block[:8] == b"SACDTRL2": durations = block
            if durations is None: raise ValueError("SACD 缺少曲目时长目录")
            for index in range(count):
                tags = {}
                pos = number(texts, 8 + index * 2) if texts else 0
                if pos:
                    if pos + 4 > len(texts): raise ValueError("SACD 曲目文本无效")
                    amount = texts[pos]; pos += 4
                    for _ in range(amount):
                        if pos + 2 >= len(texts): raise ValueError("SACD 曲目文本无效")
                        kind = texts[pos]; pos += 2
                        tags[kind] = string(texts, pos, charset)
                        pos = texts.find(b"\0", pos)
                        while pos < len(texts) and texts[pos] == 0: pos += 1
                at = 8 + 255 * 4 + index * 4
                minutes, seconds, frames = durations[at:at + 3]
                if seconds >= 60 or frames >= 75: raise ValueError("SACD 曲目时长无效")
                cover = next((str(path.parent / name) for name in ("cover.jpg", "cover.png") if (path.parent / name).is_file()), "")
                result.append(Track(str(path) + f"#amtrack={area}-{index + 1}", tags.get(1) or f"音轨 {index + 1:02d}",
                    tags.get(2) or artist or "未知艺人", title or path.stem, minutes * 60 + seconds + frames / 75,
                    cover=cover, codec="dsd", rate=2822400, bits=1, number=index + 1, modified=path.stat().st_mtime,
                    album_artist=artist, year=number(master, 120), disc=number(master, 18),
                    edition=f"SACD {'立体声' if area == 'stereo' else '多声道'} · {path.stem}",
                    container=str(path), source_index=index + 1, area=area))
        if not result: raise ValueError("SACD 中没有音轨")
        return result


_prepare_lock = threading.Lock()


def prepare_track(track, cache, ffmpeg, cancel=None):
    if not track.container: return track.path
    source = Path(track.container if track.area else track.source_path)
    stamp = source.stat()
    key = hashlib.sha256(json.dumps([path_key(source), stamp.st_size, stamp.st_mtime_ns,
        track.area, track.source_index, track.start, track.duration]).encode()).hexdigest()
    cache = Path(cache); cache.mkdir(parents=True, exist_ok=True)
    final = cache / (key + (".dsf" if track.area else ".wav"))
    # Serialize preparation to avoid competing extractors for the same image.
    with _prepare_lock:
        if cancel and cancel.is_set(): raise ValueError("已取消曲目准备")
        if final.is_file(): return str(final)
        with tempfile.TemporaryDirectory(prefix="prepare-", dir=cache) as temporary:
            target = Path(temporary)
            if track.area:
                base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
                executable = base / "native/bin/sacd_extract.exe"
                args = [str(executable), "-2" if track.area == "stereo" else "-m", "-s", "-c", "-t", str(track.source_index), "-i", str(source), "-o", str(target), "track"]
            else:
                # Decode only this segment. PCM remains at source rate/precision;
                # compressed audio uses floating point, never a lossy re-encode.
                floating = False
                if source.suffix.lower() == ".wav":
                    from mutagen.wave import _WaveFile
                    with source.open("rb") as stream: fmt = _WaveFile(stream)["fmt"].read()
                    code = int.from_bytes(fmt[:2], "little")
                    floating = code == 3 or (code == 65534 and int.from_bytes(fmt[24:26], "little") == 3)
                elif source.suffix.lower() in {".aif", ".aiff", ".aifc"}:
                    from mutagen.aiff import AIFFFile
                    with source.open("rb") as stream: fmt = AIFFFile(stream)["COMM"].read()
                    floating = fmt[18:22].lower() in {b"fl32", b"fl64"}
                codec = "pcm_f64le" if track.bits > 32 else "pcm_f32le" if floating or not track.is_lossless or track.is_dsd else "pcm_s16le" if track.bits <= 16 else "pcm_s24le" if track.bits <= 24 else "pcm_s32le"
                args = [str(ffmpeg), "-nostdin", "-v", "error", "-ss", f"{track.start:.9f}", "-i", str(source),
                    "-t", f"{track.duration:.9f}", "-map", "0:a:0", "-c:a", codec, "-rf64", "auto", str(target / "track.wav")]
            with (target / "prepare.log").open("wb") as log:
                process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=log,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                deadline = time.monotonic() + 1800
                while process.poll() is None:
                    if (cancel and cancel.is_set()) or time.monotonic() > deadline:
                        process.kill(); process.wait()
                        raise ValueError("曲目准备已取消或超时")
                    time.sleep(.1)
            files = list(target.rglob("*.dsf" if track.area else "*.wav"))
            if process.returncode or len(files) != 1:
                message = (target / "prepare.log").read_bytes().decode("utf-8", errors="replace")[-1500:]
                raise ValueError("曲目准备失败：" + message)
            import mutagen
            audio = mutagen.File(files[0])
            if audio is None or audio.info.length <= 0: raise ValueError("准备的曲目没有有效音频")
            os.replace(files[0], final)
    return str(final)
