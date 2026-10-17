import asyncio
from types import SimpleNamespace

import musicdesk_worker as worker


def test_overlapping_start_requests_share_one_backend(monkeypatch, tmp_path):
    events = []; launches = []
    monkeypatch.setattr(worker, "send", lambda event, **data: events.append({"event": event, **data}))
    async def ready(*_): pass
    async def launch(*_):
        launches.append(True); await asyncio.sleep(0)
    class Status:
        def cache_invalidate(self): pass
        async def __call__(self): return SimpleNamespace(ready=True, regions=[])
    async def decrypt(*_): await asyncio.Event().wait()
    async def run():
        bridge = worker.Bridge(tmp_path, tmp_path)
        bridge.vm = SimpleNamespace(launch_instance=launch, terminate=ready, port=12345,
                                    accelerator="WHPX", acceleration_fallback=False)
        bridge.api = SimpleNamespace(init=lambda: None)
        bridge.wm = SimpleNamespace(init=ready, status=Status(), _channel=SimpleNamespace(channel_ready=ready), decrypt_init=decrypt)
        bridge.ripper = SimpleNamespace(on_decrypt_success=None, on_decrypt_failed=None)
        bridge.config = SimpleNamespace(instance=SimpleNamespace(url="", secure=False))
        await asyncio.gather(bridge.start(), bridge.start())
        assert bridge.ready and len(launches) == 1
        assert len([event for event in events if event.get("state") == "ready"]) == 1
        bridge.decrypt_task.cancel(); await asyncio.gather(bridge.decrypt_task, return_exceptions=True)
    asyncio.run(run())


def test_api_initialization_overlaps_vm_boot_and_cancels(monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "send", lambda *_args, **_kwargs: None)
    async def run(cancel):
        api_started = asyncio.Event(); api_finished = asyncio.Event()
        async def initialize():
            api_started.set()
            try: await asyncio.Event().wait()
            finally: api_finished.set()
        async def launch(*_):
            await asyncio.wait_for(api_started.wait(), 1)
            if cancel: raise asyncio.CancelledError()
            raise RuntimeError("VM failed")
        async def terminate(): pass
        bridge = worker.Bridge(tmp_path, tmp_path)
        bridge.api = SimpleNamespace(init=initialize)
        bridge.vm = SimpleNamespace(launch_instance=launch, terminate=terminate)
        try: await bridge.start()
        except (RuntimeError, asyncio.CancelledError): pass
        assert api_finished.is_set() and not bridge.owns_vm
    asyncio.run(run(False)); asyncio.run(run(True))
