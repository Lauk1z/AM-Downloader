"""Qt-free utility protocol for existing Mutagen and read-only disc operations."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import threading


def run():
    for stream in (sys.stdin, sys.stdout, sys.stderr): stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--resources", required=True)
    parser.add_argument("--bundle", required=True)
    args = parser.parse_args()
    resources, bundle = Path(args.resources).resolve(), Path(args.bundle).resolve()
    sys.path.insert(0, str(resources))
    from musicdesk import runtime
    runtime.bundled_backend = lambda: bundle
    from musicdesk.core import Track, scan_library, read_config, update_config
    from musicdesk.discs import prepare_track
    from musicdesk.metadata import save_album_edits, find_duplicates
    stdout, lock, cancellations = sys.stdout, threading.Lock(), {}

    def reply(value):
        with lock:
            stdout.write(json.dumps(value, ensure_ascii=False) + "\n")
            stdout.flush()

    def execute(request, cancel):
        try:
            action = request["action"]
            if action == "initialize":
                state = runtime.prepare_backend(request["profile"], bundle)
                result = {"state": str(state), "config": read_config(state)}
            elif action == "config":
                result = read_config(request["state"])
            elif action == "save_config":
                update_config(request["state"], {("region", "language"): request["language"],
                    ("download", "maxSampleRate"): request["rate"], ("download", "maxBitDepth"): request["bits"]})
                result = True
            elif action == "scan":
                tracks, errors = scan_library(request.get("folder"), Path(request["profile"]) / "covers",
                    request.get("extra", []), request.get("excluded", []))
                result = {"tracks": [asdict(track) for track in tracks], "errors": errors}
            elif action == "prepare":
                result = prepare_track(Track(**request["track"]), Path(request["profile"]) / "audio-cache",
                    bundle / "deps/ffmpeg.exe", cancel)
            elif action == "info":
                import mutagen
                from musicdesk.core import audio_codec
                path = Path(request["path"])
                audio = mutagen.File(path)
                if audio is None: raise ValueError("无法读取音频格式")
                codec = audio_codec(audio, path)
                channels = getattr(audio.info, "channels", 0)
                bits = getattr(audio.info, "bits_per_sample", 0) or 24
                if codec == "tta":
                    with path.open("rb") as stream:
                        stream.seek(getattr(audio.tags, "size", 0)); header = stream.read(18)
                    if header[:4] != b"TTA1": raise ValueError("不支持的 TTA 文件头")
                    channels = int.from_bytes(header[6:8], "little"); bits = int.from_bytes(header[8:10], "little")
                if not channels: raise ValueError("无法读取音频通道信息")
                result = {"rate": 48000 if codec == "opus" else int(audio.info.sample_rate), "channels": int(channels),
                    "bits": int(bits),
                    "duration": round(audio.info.length * 1000), "dsd": codec in {"dsd", "dst"}}
            elif action == "edit":
                result = save_album_edits([Track(**track) for track in request["tracks"]],
                    request["changes"], request["profile"], request.get("cover", ""))
            elif action == "duplicates":
                result = [{"kind": kind, "tracks": [asdict(track) for track in tracks]}
                    for kind, tracks in find_duplicates([Track(**track) for track in request["tracks"]], cancel)]
            elif action == "backdrop":
                from PIL import Image, ImageFilter, ImageOps
                source = Path(request["cover"])
                stamp = source.stat()
                key = hashlib.sha256(f"{source}:{stamp.st_mtime_ns}:{stamp.st_size}".encode()).hexdigest()
                target = Path(request["profile"]) / "backdrops" / (key + ".jpg")
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with Image.open(source) as image:
                        image = ImageOps.fit(image.convert("RGB"), (160, 160)).filter(ImageFilter.GaussianBlur(36))
                        image.save(target, quality=90)
                result = str(target)
            elif action == "feature":
                from PIL import Image, ImageFilter, ImageOps
                source = Path(request["cover"])
                stamp = source.stat()
                key = hashlib.sha256(f"feature-v1:{source}:{stamp.st_mtime_ns}:{stamp.st_size}".encode()).hexdigest()
                target = Path(request["profile"]) / "backdrops" / (key + ".png")
                with Image.open(source) as original:
                    cover = ImageOps.fit(original.convert("RGB"), (640, 640))
                    patch = cover.crop((280, 20, 615, 85))
                    linear = [v / 3294.6 if v <= 10 else ((v / 255 + .055) / 1.055) ** 2.4 for v in range(256)]
                    luminances = [.2126 * linear[r] + .7152 * linear[g] + .0722 * linear[b] for r, g, b in patch.getdata()]
                    mean = sum(luminances) / len(luminances)
                    dark = (mean + .05) / .05 >= 1.05 / (mean + .05)
                    backing = ((min(luminances) + .05) / .05 if dark else 1.05 / (max(luminances) + .05)) < 4.6
                    if not target.exists():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        background = ImageOps.fit(original.convert("RGB"), (640, 858)).filter(ImageFilter.GaussianBlur(45)).convert("RGBA")
                        mask = Image.new("L", (1, 640)); mask.putdata([round(255 * max(0, min(1, (686 - y) / 257))) for y in range(640)])
                        background.paste(cover, (0, 0), mask.resize((640, 640)))
                        shade = Image.new("RGBA", (640, 858), (0, 0, 0, 255))
                        alpha = Image.new("L", (1, 858)); alpha.putdata([round(16 * (1-y/386)) if y < 386 else round(140 * (y-386)/472) for y in range(858)])
                        shade.putalpha(alpha.resize((640, 858))); background = Image.alpha_composite(background, shade); background.save(target)
                result = {"path": str(target), "dark": dark, "backing": backing}
            else:
                raise ValueError("Unknown library operation: " + action)
            if any(name.startswith("PySide6") for name in sys.modules):
                raise RuntimeError("Qt must not be loaded by the WinUI utility host")
            reply({"id": request["id"], "result": result})
        except Exception as error:
            reply({"id": request["id"], "error": str(error)})
        finally:
            cancellations.pop(request["id"], None)

    sys.stdout = sys.stderr
    with ThreadPoolExecutor(max_workers=3) as pool:
        try:
            for line in sys.stdin:
                request = json.loads(line)
                if request.get("action") == "stop": break
                if request.get("action") == "cancel":
                    token = cancellations.get(request.get("target"))
                    if token: token.set()
                    continue
                token = threading.Event()
                cancellations[request["id"]] = token
                pool.submit(execute, request, token)
        finally:
            for token in list(cancellations.values()): token.set()


if __name__ == "__main__":
    run()
