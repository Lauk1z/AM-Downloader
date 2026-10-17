"""Explicit tag edits, staged before replacement, with original-file backups."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

import mutagen
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TPE2, TDRC, TPOS, TRCK, TXXX, APIC
from mutagen.mp4 import MP4, MP4Cover
from mutagen.flac import FLAC, Picture
from mutagen.apev2 import APEv2, APEBinaryValue
from mutagen.asf import ASF
from mutagen._vorbis import VCommentDict

from .core import path_key


def write_tags(path, changes, cover=None):
    audio = mutagen.File(path)
    if audio is None: raise ValueError("音频格式无法读取")
    if audio.tags is None:
        try: audio.add_tags()
        except (AttributeError, NotImplementedError): return False
    tags = audio.tags
    fields = {"title": "title", "artist": "artist", "album": "album", "album_artist": "albumartist",
              "year": "date", "disc": "discnumber", "number": "tracknumber", "edition": "version"}
    if isinstance(audio, MP4):
        names = {"title": "©nam", "artist": "©ART", "album": "©alb", "album_artist": "aART", "year": "©day",
                 "disc": "disk", "number": "trkn", "edition": "----:com.apple.iTunes:VERSION"}
        for field, value in changes.items():
            name = names[field]
            if field in {"disc", "number"}:
                total = (tags.get(name) or [(0, 0)])[0][1]
                tags[name] = [(int(value), total)]
            else: tags[name] = [str(value).encode() if field == "edition" else str(value)]
        if cover: tags["covr"] = [MP4Cover(cover, imageformat=MP4Cover.FORMAT_PNG)]
    elif isinstance(tags, ID3):
        frames = {"title": TIT2, "artist": TPE1, "album": TALB, "album_artist": TPE2, "year": TDRC, "disc": TPOS, "number": TRCK}
        for field, value in changes.items():
            if field == "edition": tags.delall("TXXX:VERSION"); tags.add(TXXX(encoding=3, desc="VERSION", text=[str(value)]))
            else:
                frame = frames[field]
                old = str(tags.get(frame.__name__, ""))
                text = str(value)
                if field in {"disc", "number"} and "/" in old: text += "/" + old.split("/", 1)[1]
                tags.setall(frame.__name__, [frame(encoding=3, text=[text])])
        if cover:
            # Keep booklet/back images; replace front-cover pictures only.
            images = [image for image in tags.getall("APIC") if image.type != 3]
            tags.delall("APIC")
            for image in images: tags.add(image)
            tags.add(APIC(encoding=3, mime="image/png", type=3, desc="Front cover", data=cover))
    elif isinstance(audio, FLAC) or isinstance(tags, VCommentDict):
        for field, value in changes.items(): tags[fields[field]] = [str(value)]
        if cover:
            picture = Picture(); picture.type = 3; picture.mime = "image/png"; picture.data = cover
            if isinstance(audio, FLAC):
                images = [image for image in audio.pictures if image.type != 3]
                audio.clear_pictures()
                for image in images: audio.add_picture(image)
                audio.add_picture(picture)
            else: tags["metadata_block_picture"] = [base64.b64encode(picture.write()).decode("ascii")]
    elif isinstance(tags, APEv2):
        names = {"album_artist": "Album Artist", "number": "Track", "disc": "Disc", "year": "Year", "edition": "Version"}
        for field, value in changes.items(): tags[names.get(field, field.title())] = str(value)
        if cover: tags["Cover Art (Front)"] = APEBinaryValue(b"cover.png\0" + cover)
    elif isinstance(audio, ASF):
        names = {"title": "Title", "artist": "Author", "album": "WM/AlbumTitle", "album_artist": "WM/AlbumArtist",
                 "year": "WM/Year", "disc": "WM/PartOfSet", "number": "WM/TrackNumber", "edition": "WM/Version"}
        for field, value in changes.items(): tags[names[field]] = [str(value)]
        # Artwork for ASF is stored as a library override, preserving WM/Picture.
    else: return False
    audio.save()
    return True


def save_album_edits(tracks, changes, profile, cover_path=""):
    profile = Path(profile)
    overrides_path = profile / "metadata-overrides.json"
    try: overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    except FileNotFoundError: overrides = {}
    cover, cached_cover = None, ""
    if cover_path:
        from PIL import Image, ImageOps
        import io
        with Image.open(cover_path) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((3000, 3000))
            output = io.BytesIO(); image.save(output, "PNG"); cover = output.getvalue()
        folder = profile / "covers"; folder.mkdir(parents=True, exist_ok=True)
        target = folder / (hashlib.sha256(cover).hexdigest() + ".png")
        target.write_bytes(cover); cached_cover = str(target)
    staged, committed, backups, local = [], [], [], 0
    token = uuid.uuid4().hex[:12]
    try:
        for track, edit in zip(tracks, changes, strict=True):
            edit = {key: value for key, value in edit.items() if value != getattr(track, key)}
            if not edit and not cover: continue
            key = path_key(track.path)
            saved = False
            if not track.container:
                source = Path(track.path)
                temporary = source.with_name(source.stem + ".am-edit-" + token + source.suffix)
                backup = source.with_name(source.name + ".am-tag-backup-" + token)
                staged.append((source, temporary, backup))
                shutil.copy2(source, temporary)
                saved = write_tags(temporary, edit, cover)
                if not saved:
                    temporary.unlink(); staged.pop()
            values = overrides.setdefault(key, {})
            if saved:
                for field in edit: values.pop(field, None)
            else: values.update(edit); local += 1
            if cached_cover: values["cover"] = cached_cover
        for source, temporary, backup in staged:
            shutil.copy2(source, backup)
            os.replace(temporary, source); committed.append((source, backup)); backups.append(str(backup))
        temporary = overrides_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(overrides, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, overrides_path)
    except Exception:
        for source, backup in reversed(committed): os.replace(backup, source)
        raise
    finally:
        for source, temporary, backup in staged:
            if temporary.exists(): temporary.unlink()
    return {"files": len(staged), "local": local, "backups": backups}


def find_duplicates(tracks, cancel=None):
    groups, files = {}, {}
    for track in tracks: files.setdefault(path_key(track.file_path), track)
    for track in files.values():
        path = Path(track.file_path)
        if path.is_file(): groups.setdefault(path.stat().st_size, []).append(track)
    result = []
    for group in groups.values():
        if len(group) < 2: continue
        hashes = {}
        for track in group:
            digest = hashlib.sha256()
            with open(track.file_path, "rb") as stream:
                while data := stream.read(1024 * 1024):
                    if cancel and cancel.is_set(): return []
                    digest.update(data)
            digest = digest.hexdigest()
            hashes.setdefault(digest, []).append(track)
        result.extend(("文件完全相同", values) for values in hashes.values() if len(values) > 1)
    matches = {}
    for track in tracks:
        key = (track.title.strip().casefold(), track.artist.strip().casefold())
        matches.setdefault(key, []).append(track)
    for group in matches.values():
        if len(group) > 1 and max(track.duration for track in group) - min(track.duration for track in group) <= 2:
            result.append(("同名且时长接近 · 可能是不同版本", group))
    return result
