"""Real local gRPC login protocol, synthetic accounts only; never contacts Apple."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "vendor/backend"
if not RUNTIME.exists(): RUNTIME = ROOT.parent / "backend"
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(RUNTIME))
import musicdesk_worker as worker


class LoginProtocolTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        shutil.copyfile(RUNTIME / "config.example.toml", Path(cls.directory.name) / "config.toml")
        previous = Path.cwd()
        try:
            os.chdir(cls.directory.name)
            import main
            main.loop.close()
            from src.grpc.manager import WrapperManager
            from src.grpc import manager_pb2 as pb, manager_pb2_grpc as rpc
            cls.Manager, cls.pb, cls.rpc = WrapperManager, pb, rpc
        finally: os.chdir(previous)

    @classmethod
    def tearDownClass(cls): cls.directory.cleanup()

    async def asyncSetUp(self):
        import grpc
        pb = self.pb
        class Service(self.rpc.WrapperManagerServiceServicer):
            authenticated = False
            async def Status(self, request, context):
                return pb.StatusReply(header=pb.ReplyHeader(code=0), data=pb.StatusData(ready=True, regions=["CN"] if self.authenticated else []))

            async def Login(self, incoming, context):
                try:
                    async for reply in self.replies(incoming): yield reply
                except StopAsyncIteration: return

            async def replies(self, incoming):
                request = await anext(incoming)
                if request.data.username == "eof@example.test": return
                if request.data.password == "wrong-synthetic":
                    yield pb.LoginReply(header=pb.ReplyHeader(code=-1, msg="Wrong password " + request.data.password)); return
                yield pb.LoginReply(header=pb.ReplyHeader(code=2))
                request = await anext(incoming)
                if request.data.two_step_code == "111111":
                    yield pb.LoginReply(header=pb.ReplyHeader(code=2)); request = await anext(incoming)
                if request.data.two_step_code != "654321":
                    yield pb.LoginReply(header=pb.ReplyHeader(code=-1, msg="Invalid verification code " + request.data.two_step_code)); return
                self.authenticated = True
                yield pb.LoginReply(header=pb.ReplyHeader(code=0))
        self.server = grpc.aio.server(); self.rpc.add_WrapperManagerServiceServicer_to_server(Service(), self.server)
        port = self.server.add_insecure_port("127.0.0.1:0"); await self.server.start()
        self.manager = self.Manager(); await self.manager.init(f"127.0.0.1:{port}", False)
        self.bridge = worker.Bridge(ROOT); self.bridge.wm = self.manager; self.bridge.start = AsyncMock()
        self.events = []
        self.patcher = patch.object(worker, "send", lambda event, **values: self.events.append(dict(event=event, **values)))
        self.patcher.start()

    async def asyncTearDown(self):
        if self.bridge.login_task and not self.bridge.login_task.done():
            self.bridge.login_task.cancel(); await asyncio.gather(self.bridge.login_task, return_exceptions=True)
        await self.manager._channel.close(); await self.server.stop(None); self.patcher.stop()

    def start_login(self, identifier, password="valid-synthetic", username="first@example.test"):
        self.bridge.login_action(dict(action="login", request_id=identifier, username=username, password=password))

    async def challenge(self, after=0):
        async with asyncio.timeout(5):
            while True:
                found = [item for item in self.events if item["event"] == "twofa"]
                if len(found) > after: return found[-1]
                await asyncio.sleep(.005)

    def code(self, event, value): self.bridge.login_action(dict(event, action="twofa", code=value))

    async def test_first_login_repeated_challenge_stale_code_then_success(self):
        self.start_login("first"); first = await self.challenge()
        self.code(first, "111111"); second = await self.challenge(1)
        self.assertNotEqual(first["challenge_id"], second["challenge_id"])
        self.code(first, "654321"); self.assertFalse(self.bridge.twofa.done())
        self.code(second, "654321"); await self.bridge.login_task
        self.assertEqual(self.events[-1]["regions"], ["CN"]); self.assertTrue(self.events[-1]["ok"])
        self.assertFalse(self.manager._login_lock.locked())
        for secret in ("valid-synthetic", "654321", "111111"): self.assertNotIn(secret, json.dumps(self.events))

    async def test_bad_password_and_code_allow_new_login(self):
        self.start_login("bad", "wrong-synthetic"); await self.bridge.login_task
        self.assertFalse(self.events[-1]["ok"]); self.assertNotIn("wrong-synthetic", self.events[-1]["error"])
        self.start_login("bad-code"); event = await self.challenge(); self.code(event, "123456"); await self.bridge.login_task
        self.assertFalse(self.events[-1]["ok"]); self.assertNotIn("123456", self.events[-1]["error"])
        self.start_login("good"); event = await self.challenge(1); self.code(event, "654321"); await self.bridge.login_task
        self.assertTrue(self.events[-1]["ok"])

    async def test_cancel_and_timeout_release_lock_and_clear_challenge(self):
        self.start_login("cancel"); event = await self.challenge()
        self.bridge.login_action(dict(action="cancel_login", request_id="cancel")); await self.bridge.login_task
        self.assertFalse(self.manager._login_lock.locked()); self.assertIsNone(self.bridge.twofa)
        self.assertTrue(self.events[-1]["cancelled"])
        original = asyncio.wait_for
        async def short_timeout(awaitable, timeout): return await original(awaitable, .02 if timeout == 180 else timeout)
        with patch.object(worker.asyncio, "wait_for", short_timeout):
            self.start_login("timeout"); await self.bridge.login_task
        self.assertFalse(self.events[-1]["ok"]); self.assertIn("超时", self.events[-1]["error"])
        self.assertFalse(self.manager._login_lock.locked()); self.assertIsNone(self.bridge.twofa)

    async def test_unconfirmed_stream_end_is_not_success_and_immediate_cancel(self):
        self.start_login("eof", username="eof@example.test"); await self.bridge.login_task
        self.assertFalse(self.events[-1]["ok"]); self.assertFalse(self.manager._login_lock.locked())
        self.start_login("instant"); self.bridge.login_action(dict(action="cancel_login", request_id="instant"))
        await asyncio.gather(self.bridge.login_task, return_exceptions=True); await asyncio.sleep(0)
        self.assertTrue(self.events[-1]["cancelled"]); self.assertEqual(self.events[-1]["request_id"], "instant")


if __name__ == "__main__": unittest.main(verbosity=2)
