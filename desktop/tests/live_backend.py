"""Opt-in live backend check. Writes only to a supplied isolated output folder."""
import argparse
import asyncio
import os
import subprocess
from pathlib import Path
import sys


async def check(root, output, codec):
    import musicdesk_worker as worker
    events = []
    original_send = worker.send
    def send(event, **data):
        events.append({"event": event, **data})
        if event != "speed": original_send(event, **data)
    worker.send = send
    bridge = worker.Bridge(root)
    bridge.bootstrap()
    bridge.config.download.dirPathFormat = str(output / "{album_artist}" / "{album}")
    bridge.config.download.playlistDirPathFormat = str(output / "playlists" / "{playlistName}")
    bridge.config.download.afterDownloaded = ""
    ticker = asyncio.create_task(bridge.tick())
    try:
        await asyncio.wait_for(bridge.download({"id": "live-" + codec, "url": "https://music.apple.com/cn/song/hotel-california/635770202", "codec": codec}), 300)
        result = next(event for event in reversed(events) if event["event"] == "finished")
        assert result["state"] == "DONE", result
        from mutagen.mp4 import MP4
        files = list(output.rglob("*.m4a"))
        assert files, "No downloaded file"
        audio = MP4(files[0])
        assert audio.info.codec.startswith(codec)
        if codec == "alac": assert audio.info.sample_rate == 192000 and audio.info.bits_per_sample == 24
        decoded = subprocess.run([str(root / "deps" / "ffmpeg.exe"), "-v", "error", "-xerror", "-i", str(files[0]), "-map", "0:a:0", "-f", "null", "-"], capture_output=True, timeout=60)
        assert decoded.returncode == 0, decoded.stderr[:1200]
        send("verified", codec=audio.info.codec, sample_rate=audio.info.sample_rate, bits=audio.info.bits_per_sample, duration=audio.info.length, bytes=files[0].stat().st_size, full_decode=True)
    finally:
        ticker.cancel()
        if bridge.owns_vm: await bridge.vm.terminate()
        await bridge.api.client.aclose()
        if hasattr(bridge.wm, "_channel"): await bridge.wm._channel.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--root", required=True); parser.add_argument("--output", required=True); parser.add_argument("--codec", choices=["alac", "aac"], default="alac")
    args = parser.parse_args()
    root, output = Path(args.root).resolve(), Path(args.output).resolve()
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent)); sys.path.insert(0, str(root)); os.chdir(root)
    os.environ["PATH"] = str(root / "deps") + os.pathsep + os.environ.get("PATH", "")
    os.environ.setdefault("SYSTEMROOT", r"C:\Windows"); os.environ.setdefault("COMSPEC", r"C:\Windows\System32\cmd.exe")
    asyncio.run(check(root, output, args.codec))
