import ctypes
from ctypes import wintypes
import os
import subprocess
import sys

import pytest
import tomlkit

from musicdesk import runtime
from musicdesk.core import python_path, valid_backend


def test_whpx_capability_detection(monkeypatch):
    from musicdesk_backend import whpx_available
    from types import SimpleNamespace
    def query(code, buffer, size, written):
        assert code == 0 and size == 8
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_uint64))[0] = 1
        return 0
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_: SimpleNamespace(WHvGetCapability=query))
    assert whpx_available()
    def missing(*_): raise OSError("API unavailable")
    monkeypatch.setattr(ctypes, "WinDLL", missing)
    assert not whpx_available()


def test_acceleration_failure_falls_back_but_cancellation_does_not(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    import musicdesk_backend as backend
    monkeypatch.setattr(backend, "whpx_available", lambda: True)
    instance = object.__new__(backend.BundledInstance)
    instance.config = SimpleNamespace(localInstance=SimpleNamespace(enableHardwareAcceleration=False))
    instance.proc = object(); instance.acceleration_fallback = False
    modes = []
    async def launch(loop, automatic):
        modes.append(automatic)
        if automatic:
            instance.proc = object()
            raise RuntimeError("Accelerator failed")
    instance._launch_instance = launch
    asyncio.run(instance.launch_instance(None))
    assert modes == [True, False] and instance.acceleration_fallback
    modes.clear()
    async def locked(loop, automatic):
        modes.append(automatic); raise RuntimeError("Account image locked")
    instance._launch_instance = locked
    with pytest.raises(RuntimeError): asyncio.run(instance.launch_instance(None))
    assert modes == [True]  # A locked account image must not be retried.
    async def cancelled(*_): raise asyncio.CancelledError()
    instance._launch_instance = cancelled
    with pytest.raises(asyncio.CancelledError): asyncio.run(instance.launch_instance(None))
    modes.clear(); instance._launch_instance = launch
    instance.config.localInstance.enableHardwareAcceleration = True
    asyncio.run(instance.launch_instance(None))
    assert modes == [False]  # Honor explicitly configured accelerator parameters.


def test_vm_acceleration_arguments_preserve_account_image(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    import musicdesk_backend as backend
    state = tmp_path / "state"; (state / "assets").mkdir(parents=True)
    image = state / "assets/wrapper-manager.qcow2"; image.write_bytes(b"existing account image")
    config = SimpleNamespace(localInstance=SimpleNamespace(enableHardwareAcceleration=False,
                             hardwareAccelerator="", cpuModel="Cascadelake-Server-v5", memorySize="512M"))
    commands = []
    class Process:
        returncode = None
        async def wait(self): self.returncode = 0
    class Guest:
        async def ping(self): pass
        async def write_file(self, *_): pass
        async def execute(self, *_): pass
    async def spawn(*args, **kwargs): commands.append(args); return Process()
    async def connect(*_): return None, SimpleNamespace(close=lambda: None)
    async def prepare(*_): pass
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(asyncio, "open_connection", connect)
    monkeypatch.setattr(backend, "whpx_available", lambda: True)
    monkeypatch.setattr(backend.BundledInstance, "prepare_guest_time", prepare)
    instance = object.__new__(backend.BundledInstance)
    instance.runtime, instance.state, instance.config = tmp_path / "runtime", state, config
    instance.client = Guest(); instance.proc = instance.lock = instance.log_file = None
    async def run():
        await instance.launch_instance(None); await instance.terminate()
    asyncio.run(run())
    command = commands[-1]
    assert command[command.index("-accel") + 1] == "whpx,kernel-irqchip=off"
    assert command[command.index("-cpu") + 1] == "qemu64-v1"
    assert "-smp" in command and instance.accelerator == "WHPX"
    assert image.read_bytes() == b"existing account image"
    assert config.localInstance.cpuModel == "Cascadelake-Server-v5" and not config.localInstance.enableHardwareAcceleration
    monkeypatch.setattr(backend, "whpx_available", lambda: False)
    asyncio.run(run())
    assert "-accel" not in commands[-1] and instance.accelerator == "TCG"


def test_time_migration_preserves_sources_and_custom_settings():
    from musicdesk_backend import background_time_config
    original = "# local settings\npool pool.ntp.org iburst\ninitstepslew 10 pool.ntp.org clock.local\nrtcsync\ncmdport 0\n"
    updated = background_time_config(original)
    assert "initstepslew" not in updated and "makestep 1.0 3" in updated
    assert "server clock.local iburst" in updated and updated.count("pool.ntp.org") == 1
    assert "# local settings" in updated and "rtcsync\ncmdport 0" in updated
    assert background_time_config(updated) == updated
    custom = original + "makestep 2 5\n"
    assert "makestep 2 5" in background_time_config(custom) and "makestep 1.0 3" not in background_time_config(custom)


def test_guest_clock_is_set_before_atomic_config_migration(monkeypatch):
    import asyncio
    from musicdesk_backend import BundledInstance
    events = []
    class Guest:
        async def send_cmd(self, command, arguments):
            events.append((command, arguments))
            return {"exited": True, "exitcode": 0}
        async def read_file(self, path): return "pool pool.ntp.org iburst\ninitstepslew 10 pool.ntp.org\nrtcsync\n"
        async def write_file(self, path, value): events.append((path, value))
        async def execute(self, path, arguments):
            events.append((path, arguments)); return {"pid": 10}
    instance = object.__new__(BundledInstance); instance.client = Guest()
    asyncio.run(instance.prepare_guest_time())
    assert events[0][0] == "guest-set-time" and events[0][1]["time"] > 10**18
    assert events[1][0].endswith(".am-new") and "makestep 1.0 3" in events[1][1]
    assert "cp -p chrony.conf chrony.conf.am-backup" in events[2][1][1]
    assert "mv chrony.conf.am-new chrony.conf" in events[2][1][1]


def test_managed_state_preserves_account_and_settings(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"; (bundle / "assets").mkdir(parents=True)
    (bundle / "src").mkdir(); (bundle / "src/rip.py").touch(); (bundle / "main.py").touch()
    (bundle / ".venv").mkdir(); (bundle / ".venv/python.exe").touch()
    for name in ("device.wvd", "storefronts.json", "storefront_ids.json"):
        (bundle / "assets" / name).write_bytes(b"public")
    (bundle / "config.example.toml").write_text('[localInstance]\nenable=false\n[region]\nlanguage="en-US"\n[download]\nmaxBitDepth=24\n')
    monkeypatch.setattr(runtime, "bundled_backend", lambda: bundle)
    state = runtime.prepare_backend(tmp_path / "用户 profile")
    config = state / "config.toml"
    assert tomlkit.parse(config.read_text())["localInstance"]["enable"]
    assert not (state / "assets/wrapper-manager.qcow2").exists()
    config.write_text(config.read_text() + "# user setting\n")
    previous = config.read_bytes()
    image = state / "assets/wrapper-manager.qcow2"; image.write_bytes(b"user account image")
    runtime.prepare_backend(state.parent)
    assert config.read_bytes() == previous and image.read_bytes() == b"user account image"
    assert runtime.code_root(state) == bundle and valid_backend(state)
    assert python_path(state) == bundle / ".venv/python.exe"


@pytest.mark.skipif(os.name != "nt", reason="Windows process ownership")
def test_worker_crash_reaps_its_child():
    script = "from musicdesk_backend import protect_process_tree; import subprocess,sys,time; job=protect_process_tree(); child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); print(child.pid,flush=True); time.sleep(30)"
    worker = subprocess.Popen([sys.executable, "-u", "-c", script], stdout=subprocess.PIPE, text=True,
                              creationflags=subprocess.CREATE_NO_WINDOW)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = None
    try:
        child_pid = int(worker.stdout.readline())
        handle = kernel.OpenProcess(0x100000, False, child_pid)
        assert handle
        worker.kill(); worker.wait(timeout=5)
        assert kernel.WaitForSingleObject(handle, 5000) == 0
    finally:
        if worker.poll() is None: worker.kill(); worker.wait(timeout=5)
        if handle: kernel.CloseHandle(handle)
