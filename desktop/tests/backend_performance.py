"""Run with the bundled backend Python; no account or network is used."""
import asyncio
from pathlib import Path
import os
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

WORKSPACE = Path(__file__).resolve().parents[1]
RUNTIME = WORKSPACE / "vendor/backend"
if not RUNTIME.exists(): RUNTIME = WORKSPACE.parent / "backend"
sys.path.insert(0, str(WORKSPACE))
sys.path.insert(0, str(RUNTIME))


class PerformanceTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        previous = Path.cwd()
        shutil.copyfile(RUNTIME / "config.example.toml", Path(cls.directory.name) / "config.toml")
        try:
            os.chdir(cls.directory.name)
            import main
            main.loop.close()
            from src.api import WebAPI
            from src.rip import Ripper
            cls.WebAPI, cls.Ripper = WebAPI, Ripper
        finally: os.chdir(previous)

    @classmethod
    def tearDownClass(cls): cls.directory.cleanup()

    async def test_api_initializes_once_and_is_cancellable(self):
        api = self.WebAPI("", 1)
        started = asyncio.Event()
        async def token():
            started.set(); await asyncio.sleep(.01); api.token = "test-token"
        try:
            with patch.object(api, "_set_token", AsyncMock(side_effect=token)) as fetch:
                await asyncio.gather(api.init(), api.init(), api.init())
                self.assertEqual(fetch.await_count, 1)
                self.assertEqual(api.client.headers["Authorization"], "Bearer test-token")
            api.token = ""; started.clear()
            async def blocked(): started.set(); await asyncio.Event().wait()
            with patch.object(api, "_set_token", blocked):
                task = asyncio.create_task(api.init()); await started.wait(); task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
            self.assertFalse(api.init_lock.locked())
        finally:
            await api.aclose()
            self.assertTrue(api.client.is_closed and api.download_client.is_closed)

    async def test_catalog_cache_deduplicates_and_keeps_language_separate(self):
        import src.api as module
        api = self.WebAPI("", 1)
        response = SimpleNamespace(json=lambda: {}, content=b"cover")
        parsed = SimpleNamespace(data=[SimpleNamespace(relationships=SimpleNamespace(tracks=SimpleNamespace(next=None)))])
        try:
            with patch.object(api, "_request", AsyncMock(return_value=response)) as request, patch.object(module.AlbumMeta, "model_validate", return_value=parsed):
                await asyncio.gather(*(api.get_album_info("album", "CN", "zh-Hans-CN") for _ in range(8)))
                self.assertEqual(request.await_count, 1)
                await api.get_album_info("album", "CN", "en-US")
                self.assertEqual(request.await_count, 2)
                await asyncio.gather(*(api.get_cover("https://example.test/{w}x{h}bb.jpg", "jpg", "500x500") for _ in range(8)))
                self.assertEqual(request.await_count, 3)
                for index in range(5): await api.get_cover(f"https://example.test/{index}.jpg", "jpg", "500x500")
                self.assertLessEqual(api.get_cover.cache_info().currsize, 2)
            api.get_album_info.cache_clear()
            with patch.object(api, "_request", AsyncMock(side_effect=[RuntimeError("offline"), response])) as request, patch.object(module.AlbumMeta, "model_validate", return_value=parsed):
                with self.assertRaises(RuntimeError): await api.get_album_info("album", "CN", "en-US")
                await api.get_album_info("album", "CN", "en-US")
                self.assertEqual(request.await_count, 2)
        finally: await api.aclose()

    async def test_download_client_reused_and_length_check_preserved(self):
        import httpx
        api = self.WebAPI("", 1)
        await api.download_client.aclose()
        requests = []
        async def serve(request):
            requests.append(str(request.url))
            return httpx.Response(200, content=b"abc", headers={"Content-Length": "4" if request.url.path == "/bad" else "3"})
        api.download_client = httpx.AsyncClient(transport=httpx.MockTransport(serve))
        shared = api.download_client
        try:
            self.assertEqual(await api.download_song("https://example.test/one"), b"abc")
            self.assertEqual(await api.download_song("https://example.test/two"), b"abc")
            self.assertIs(api.download_client, shared)
            with self.assertRaises(httpx.HTTPError):
                await self.WebAPI._download_song_internal.__wrapped__(api, "https://example.test/bad")
            self.assertEqual(len(requests), 3)
        finally: await api.aclose()

    def sample_task(self, count):
        samples = [SimpleNamespace(data=index.to_bytes(4, "little"), descIndex=0) for index in range(count)]
        return SimpleNamespace(adamId="test", info=SimpleNamespace(samples=samples),
                               m3u8Info=SimpleNamespace(keys=["test"]), decrypted_samples_futures={})

    async def test_samples_bounded_ordered_and_clean_after_completion(self):
        ripper = self.Ripper(); task = self.sample_task(4000); peak = 0
        async def process(_id, _key, data, index):
            nonlocal peak
            peak = max(peak, len(task.decrypted_samples_futures))
            await asyncio.sleep(0)
            return data
        with patch.object(ripper, "decrypt_sample_with_retry", process):
            result = await ripper._decrypt_samples(task)
        self.assertEqual(result, b"".join(sample.data for sample in task.info.samples))
        self.assertLessEqual(peak, 64)
        self.assertEqual(task.decrypted_samples_futures, {})

    async def test_sample_failure_and_cancellation_drain_workers(self):
        ripper = self.Ripper()
        for fail in (False, True):
            task = self.sample_task(1000); active = set(); started = asyncio.Event()
            async def process(_id, _key, data, index):
                active.add(index); started.set()
                try:
                    if fail and index == 2: raise ValueError("injected failure")
                    await asyncio.Event().wait()
                finally: active.remove(index)
            with patch.object(ripper, "decrypt_sample_with_retry", process):
                operation = asyncio.create_task(ripper._decrypt_samples(task))
                await started.wait()
                if fail:
                    with self.assertRaises(ExceptionGroup): await operation
                else:
                    operation.cancel()
                    with self.assertRaises(asyncio.CancelledError): await operation
            self.assertFalse(active)
            self.assertEqual(task.decrypted_samples_futures, {})

    async def test_real_sample_callbacks_and_retry_preserve_bytes(self):
        import src.rip as module
        from tenacity import wait_none
        from types import MethodType
        ripper = self.Ripper(); task = self.sample_task(257)
        ripper.download_manager.adam_id_task_mapping[task.adamId] = task
        ripper.decrypt_sample_with_retry = MethodType(self.Ripper.decrypt_sample_with_retry.retry_with(wait=wait_none()), ripper)
        callbacks = set(); attempts = {}
        async def decrypt(adam_id, key, data, index):
            attempts[index] = attempts.get(index, 0) + 1
            async def respond():
                await asyncio.sleep(0)
                if index == 7 and attempts[index] == 1:
                    await ripper.on_decrypt_failed(adam_id, key, data, index)
                else: await ripper.on_decrypt_success(adam_id, key, data, index)
            reply = asyncio.create_task(respond()); callbacks.add(reply); reply.add_done_callback(callbacks.discard)
        transport = SimpleNamespace(decrypt=decrypt); original_it = module.it
        with patch.object(module, "it", lambda kind: transport if kind is module.WrapperManager else original_it(kind)):
            result = await asyncio.wait_for(ripper._decrypt_samples(task), 3)
        self.assertEqual(result, b"".join(sample.data for sample in task.info.samples))
        self.assertEqual(attempts[7], 2)
        self.assertEqual(task.decrypted_samples_futures, {})
        await asyncio.gather(*callbacks)

    async def test_existing_file_skips_cover_lyrics_and_download(self):
        import src.rip as module
        from src.task import Status
        from src.types import Codec
        ripper = self.Ripper()
        raw = SimpleNamespace(relationships=SimpleNamespace(albums=SimpleNamespace(data=[SimpleNamespace(id="album")])))
        metadata = SimpleNamespace(parse_from_album_data=lambda _: None, artist="artist", title="title")
        api = SimpleNamespace(get_song_info=AsyncMock(return_value=raw), get_album_info=AsyncMock(return_value=None),
                              get_cover=AsyncMock(side_effect=AssertionError("Cover requested for existing file")))
        original_it = module.it; statuses = []
        def dependencies(kind): return api if kind is module.WebAPI else original_it(kind)
        with patch.object(module, "it", dependencies), patch.object(module.SongMetadata, "parse_from_song_data", return_value=metadata), \
             patch.object(module, "check_song_existence", AsyncMock(return_value=True)), patch.object(module, "check_song_exists", return_value=True), \
             patch.object(module, "language_exist", return_value=True), patch.object(module, "RipLogger", return_value=MagicMock()), \
             patch.object(module.Task, "update_status", lambda _task, status: statuses.append(status)):
            await ripper.rip_song(SimpleNamespace(id="test", storefront="CN"), Codec.ALAC)
        self.assertIn(Status.DONE, statuses)
        self.assertEqual(api.get_cover.await_count, 0)

    async def test_next_song_prefetch_overlaps_and_cancel_cleans_it(self):
        import musicdesk_worker as worker
        for cancel in (False, True):
            bridge = worker.Bridge(RUNTIME, Path(self.directory.name))
            bridge.regions = ["CN"]; bridge.start = AsyncMock()
            bridge.config = SimpleNamespace(download=SimpleNamespace(), region=SimpleNamespace(language="en-US"))
            songs = [(SimpleNamespace(id=str(index), storefront="CN"), None) for index in range(3)]
            bridge.expand = AsyncMock(return_value=songs)
            started = asyncio.Event(); finished = asyncio.Event(); calls = []
            async def song_info(*_):
                started.set()
                try:
                    if cancel: await asyncio.Event().wait()
                    return SimpleNamespace(relationships=SimpleNamespace(albums=SimpleNamespace(data=[SimpleNamespace(id="album")])))
                finally: finished.set()
            bridge.api = SimpleNamespace(get_song_info=song_info, get_album_info=AsyncMock())
            async def rip(song, *_args, **_kwargs):
                calls.append(song.id)
                await asyncio.wait_for(started.wait(), 1)
                if cancel: await asyncio.Event().wait()
                bridge.last_tasks[song.id] = SimpleNamespace(status="DONE")
            bridge.ripper = SimpleNamespace(rip_song=rip)
            events = []
            with patch.object(worker, "send", lambda event, **data: events.append((event, data))):
                operation = asyncio.create_task(bridge.download({"id": "job", "url": "test", "output_dir": self.directory.name}))
                await asyncio.wait_for(started.wait(), 1)
                if cancel: operation.cancel()
                await asyncio.wait_for(operation, 1)
            self.assertIsNone(bridge.prefetch)
            self.assertTrue(finished.is_set())
            self.assertEqual(bridge.last_tasks, {})
            self.assertEqual(next(data["state"] for event, data in events if event == "finished"), "cancelled" if cancel else "DONE")
            if not cancel: self.assertEqual(calls, ["0", "1", "2"])


if __name__ == "__main__": unittest.main(verbosity=2)
