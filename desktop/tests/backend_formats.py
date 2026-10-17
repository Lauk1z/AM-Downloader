"""Run with backend Python; synthetic manifests, no account or network access."""
import asyncio
from contextlib import ExitStack
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "vendor/backend"
if not RUNTIME.exists(): RUNTIME = ROOT.parent / "backend"
sys.path[:0] = [str(ROOT), str(RUNTIME)]
import musicdesk_worker as worker


def master(*variants):
    lines = ["#EXTM3U"]
    for codec, bandwidth in variants:
        extra = ""
        if codec.startswith("audio-alac"):
            rate, depth = codec.rsplit("-", 2)[-2:]
            extra = f",SAMPLE-RATE={rate},BIT-DEPTH={depth}"
        lines.extend([f'#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="{codec}",NAME="{codec}"{extra}',
                      f'#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},AUDIO="{codec}"', codec + ".m3u8"])
    return "\n".join(lines)


CHILD = '#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="skd://synthetic/c6"\n#EXT-X-MAP:URI="audio.mp4"\n#EXTINF:10,\naudio.mp4\n'


class FormatTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        previous = Path.cwd()
        shutil.copyfile(RUNTIME / "config.example.toml", Path(cls.directory.name) / "config.toml")
        try:
            os.chdir(cls.directory.name)
            import main
            main.loop.close()
        finally: os.chdir(previous)

    @classmethod
    def tearDownClass(cls): cls.directory.cleanup()

    async def asyncSetUp(self):
        self.events = []
        self.patch_send = patch.object(worker, "send", lambda event, **data: self.events.append({"event": event, **data}))
        self.patch_send.start(); self.addCleanup(self.patch_send.stop)
        self.bridge = worker.Bridge(RUNTIME)
        self.bridge.job_id = "job"
        self.bridge.config = SimpleNamespace(download=SimpleNamespace(maxBitDepth=24, maxSampleRate=192000),
                                             region=SimpleNamespace(language="en-US"))
        self.bridge.api = SimpleNamespace(download_m3u8=AsyncMock())
        self.bridge.wm = SimpleNamespace(webPlayback=AsyncMock(return_value="https://example.test/legacy.m3u8"))
        self.task = SimpleNamespace(adamId="song", metadata=SimpleNamespace(title="Test song", artist="Artist"))
        self.raw = SimpleNamespace(attributes=SimpleNamespace(extendedAssetUrls=None))

    async def answer(self, operation, accepted):
        await asyncio.sleep(0)
        self.assertFalse(operation.done())
        request = next(e for e in reversed(self.events) if e["event"] == "format_fallback")
        self.bridge.format_response({"job_id": "job", "request_id": "stale", "accepted": True})
        self.bridge.format_response({"job_id": "another", "request_id": request["request_id"], "accepted": True})
        self.assertFalse(self.bridge.format_future.done())
        self.bridge.format_response({"job_id": "job", "request_id": request["request_id"], "accepted": accepted})
        return request

    async def test_requested_available_no_prompt_highest_variant_and_limits(self):
        self.bridge.api.download_m3u8.return_value = master(("audio-alac-stereo-48000-24", 3000000),
            ("audio-alac-stereo-96000-24", 2000000), ("audio-alac-stereo-192000-24", 4000000))
        self.bridge.config.download.maxSampleRate = 96000
        codec, url = await self.bridge.select_audio(self.task, "alac", self.raw, "https://example.test/master.m3u8")
        self.assertEqual(codec, "alac")
        self.assertEqual(self.task.selected_media.stream_info.audio, "audio-alac-stereo-96000-24")
        self.assertNotIn("format_fallback", [e["event"] for e in self.events])
        self.assertIn("96 kHz", self.events[-1]["quality"])

    async def test_accept_selects_highest_aac_and_reuses_exact_manifest_variant(self):
        import src.mp4 as mp4
        self.bridge.api.download_m3u8.side_effect = [master(("audio-stereo-128", 128000), ("audio-stereo-256", 256000)), CHILD]
        operation = asyncio.create_task(self.bridge.select_audio(self.task, "alac", self.raw, "https://example.test/master.m3u8"))
        request = await self.answer(operation, True)
        codec, url = await operation
        self.assertEqual(codec, "aac"); self.assertIn("256", request["quality"])
        self.assertIsNone(self.bridge.format_future)
        original_it = mp4.it
        with patch.object(mp4, "it", lambda kind: self.bridge.api if kind is mp4.WebAPI else original_it(kind)):
            media = await mp4.extract_media(url, codec, self.task)
        self.assertEqual(media.codec_id, "audio-stereo-256")
        self.assertEqual(self.bridge.api.download_m3u8.await_count, 2)  # Master once, then the selected child.
        self.assertEqual(self.bridge.api.download_m3u8.await_args.args[0], "https://example.test/audio-stereo-256.m3u8")

    async def test_unavailable_spatial_format_prefers_lossless(self):
        self.bridge.api.download_m3u8.return_value = master(("audio-stereo-256", 256000), ("audio-alac-stereo-48000-24", 2000000))
        operation = asyncio.create_task(self.bridge.select_audio(self.task, "ec3", self.raw, "https://example.test/master.m3u8"))
        request = await self.answer(operation, True)
        self.assertEqual(request["codec"], "alac"); self.assertEqual((await operation)[0], "alac")

    async def test_no_enhanced_asset_offers_verified_legacy_aac(self):
        import src.legacy.mp4 as legacy
        self.bridge.api.download_m3u8.return_value = CHILD
        original_it = legacy.it
        with patch.object(legacy, "it", lambda kind: self.bridge.api if kind is legacy.WebAPI else original_it(kind)):
            operation = asyncio.create_task(self.bridge.select_audio(self.task, "alac", self.raw, None))
            request = await self.answer(operation, True)
            self.assertEqual((await operation)[0], "aac-legacy")
        self.assertEqual(request["codec"], "aac-legacy")
        self.assertEqual(self.task.legacy_media.uri, "https://example.test/audio.mp4")

    async def test_empty_lossless_manifest_uses_catalog_manifest(self):
        self.raw.attributes.extendedAssetUrls = SimpleNamespace(enhancedHls="https://example.test/master.m3u8")
        self.bridge.api.download_m3u8.return_value = master(("audio-stereo-256", 256000))
        operation = asyncio.create_task(self.bridge.select_audio(self.task, "alac", self.raw, None))
        await self.answer(operation, True)
        self.assertEqual(await operation, ("aac", "https://example.test/master.m3u8"))

    async def test_reject_cancels_job_and_does_not_advance_album_or_start_audio(self):
        self.bridge.start = AsyncMock()
        songs = [(SimpleNamespace(id="song"), None), (SimpleNamespace(id="second"), None)]
        self.bridge.expand = AsyncMock(return_value=songs)
        self.bridge.api.download_m3u8.return_value = master(("audio-stereo-256", 256000))
        audio_download = AsyncMock()
        async def rip(*_args, **_kwargs):
            await self.bridge.select_audio(self.task, "alac", self.raw, "https://example.test/master.m3u8")
            await audio_download()
        self.bridge.ripper = SimpleNamespace(rip_song=AsyncMock(side_effect=rip))
        operation = asyncio.create_task(self.bridge.download({"id": "job", "url": "original-link", "codec": "alac"}))
        await self.answer(operation, False); await operation
        self.assertEqual(self.events[-1]["state"], "cancelled")
        self.assertEqual(self.bridge.ripper.rip_song.await_count, 1)
        audio_download.assert_not_awaited(); self.assertIsNone(self.bridge.format_future)

    async def test_external_cancellation_cleans_pending_response(self):
        self.bridge.api.download_m3u8.return_value = master(("audio-stereo-256", 256000))
        operation = asyncio.create_task(self.bridge.select_audio(self.task, "alac", self.raw, "https://example.test/master.m3u8"))
        await asyncio.sleep(0); operation.cancel()
        with self.assertRaises(asyncio.CancelledError): await operation
        self.assertIsNone(self.bridge.format_future); self.assertEqual(self.bridge.format_request_id, "")

    async def test_network_errors_are_not_treated_as_missing_format(self):
        self.bridge.api.download_m3u8.side_effect = RuntimeError("network failure")
        with self.assertRaisesRegex(RuntimeError, "network failure"):
            await self.bridge.select_audio(self.task, "alac", self.raw, "https://example.test/master.m3u8")
        self.assertFalse(self.events); self.bridge.wm.webPlayback.assert_not_awaited()

    async def test_legacy_selection_reaches_legacy_pipeline_after_confirmation(self):
        import src.rip as rip
        from src.flags import Flags
        from src.task import Status
        ripper = rip.Ripper(); selected = []
        raw = SimpleNamespace(relationships=SimpleNamespace(albums=SimpleNamespace(data=[SimpleNamespace(id="album")])),
                              attributes=SimpleNamespace(hasTimeSyncedLyrics=False, extendedAssetUrls=None))
        metadata = SimpleNamespace(parse_from_album_data=lambda _: None, artist="Artist", title="Song", cover_url="cover")
        api = SimpleNamespace(get_song_info=AsyncMock(return_value=raw), get_album_info=AsyncMock(), get_cover=AsyncMock())
        async def choose(task, codec, raw, url):
            selected.append(codec); return "aac-legacy", None
        ripper.select_audio = choose
        ripper._get_m3u8_url = AsyncMock(return_value=None)
        ripper._rip_song_legacy = AsyncMock()
        original_it = rip.it
        with ExitStack() as stack:
            stack.enter_context(patch.object(rip, "it", lambda kind: api if kind is rip.WebAPI else original_it(kind)))
            stack.enter_context(patch.object(rip.SongMetadata, "parse_from_song_data", return_value=metadata))
            stack.enter_context(patch.object(rip, "check_song_existence", AsyncMock(return_value=True)))
            stack.enter_context(patch.object(rip, "check_song_exists", return_value=False))
            stack.enter_context(patch.object(rip, "language_exist", return_value=True))
            stack.enter_context(patch.object(rip, "RipLogger", return_value=MagicMock()))
            await ripper.rip_song(SimpleNamespace(id="song", storefront="CN"), "alac", Flags(language="en-US"))
        self.assertEqual(selected, ["alac"]); ripper._rip_song_legacy.assert_awaited_once()


if __name__ == "__main__": unittest.main(verbosity=2)
