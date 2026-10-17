"""Private QEMU lifecycle for the bundled backend; no external instance reuse."""
import asyncio
import hashlib
import json
import lzma
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from musicdesk_boot import BootCache


def prepare_private_image(runtime, state):
    """Restore the public seed once, without ever replacing an account image."""
    image = state / "assets/wrapper-manager.qcow2"
    if image.is_file(): return image
    temporary = image.with_suffix(".partial")
    compressed = runtime / "assets/wrapper-manager.qcow2.xz"
    try:
        if compressed.is_file():
            expected = json.loads((runtime / "bundle.json").read_text(encoding="utf-8"))["pristine_image_sha256"]
            checksum = hashlib.sha256()
            with lzma.open(compressed, "rb") as incoming, temporary.open("wb") as outgoing:
                while chunk := incoming.read(4 * 1024 * 1024):
                    checksum.update(chunk); outgoing.write(chunk)
            if checksum.hexdigest() != expected:
                raise RuntimeError("内置服务镜像校验失败，请重新解压软件安装包。")
        else:
            shutil.copyfile(runtime / "assets/wrapper-manager.qcow2", temporary)
        temporary.replace(image)
    finally:
        temporary.unlink(missing_ok=True)
    return image


def background_time_config(original):
    lines = original.splitlines()
    directives = [line.split("#", 1)[0].split() for line in lines]
    initial = [parts for parts in directives if parts and parts[0] == "initstepslew"]
    if not initial: return original
    sources = {parts[1] for parts in directives if len(parts) > 1 and parts[0] in {"server", "pool", "peer"}}
    result = [line for line, parts in zip(lines, directives) if not parts or parts[0] != "initstepslew"]
    for parts in initial:
        for host in parts[2:]:
            if host not in sources:
                result.append(f"server {host} iburst"); sources.add(host)
    if not any(parts and parts[0] == "makestep" for parts in directives):
        result.append("makestep 1.0 3")
    return "\n".join(result) + "\n"


def whpx_available():
    if os.name != "nt": return False
    import ctypes as c
    try:
        query = c.WinDLL("WinHvPlatform.dll").WHvGetCapability
        query.argtypes = [c.c_uint32, c.c_void_p, c.c_uint32, c.POINTER(c.c_uint32)]
        query.restype = c.c_long
        capability, written = c.c_uint64(), c.c_uint32()
        return query(0, c.byref(capability), c.sizeof(capability), c.byref(written)) == 0 and bool(capability.value)
    except (OSError, AttributeError):
        return False


def protect_process_tree():
    """Keep the handle for the worker lifetime; Windows reaps its children on exit."""
    import ctypes as c
    from ctypes import wintypes as w
    class BasicLimits(c.Structure):
        _fields_ = [("process_time", c.c_int64), ("job_time", c.c_int64), ("flags", w.DWORD),
                    ("min_working_set", c.c_size_t), ("max_working_set", c.c_size_t),
                    ("active_processes", w.DWORD), ("affinity", c.c_size_t),
                    ("priority", w.DWORD), ("scheduling", w.DWORD)]
    class ExtendedLimits(c.Structure):
        _fields_ = [("basic", BasicLimits), ("io", c.c_uint64 * 6),
                    ("process_memory", c.c_size_t), ("job_memory", c.c_size_t),
                    ("peak_process_memory", c.c_size_t), ("peak_job_memory", c.c_size_t)]
    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
    kernel.CreateJobObjectW.restype = w.HANDLE
    kernel.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    if not handle: raise c.WinError(c.get_last_error())
    limits = ExtendedLimits(); limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(handle, 9, c.byref(limits), c.sizeof(limits)) or not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        error = c.get_last_error(); kernel.CloseHandle(handle)
        raise c.WinError(error)
    return handle


class BundledInstance:
    def __init__(self, runtime, state, config):
        from src.qemu import QGAClient
        self.runtime, self.state, self.config = Path(runtime), Path(state), config
        self.client = QGAClient()
        self.proc, self.lock, self.log_file = None, None, None
        self.port = 0
        self.accelerator = "TCG"
        self.acceleration_fallback = False

    def acquire(self):
        import msvcrt
        self.lock = (self.state / "instance.lock").open("a+b")
        if self.lock.tell() == 0: self.lock.write(b"0"); self.lock.flush()
        self.lock.seek(0)
        try: msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.lock.close(); self.lock = None
            raise RuntimeError("内置下载服务已在另一个窗口运行，请先关闭该窗口。") from None

    async def launch_instance(self, loop):
        automatic = not self.config.localInstance.enableHardwareAcceleration and whpx_available()
        previous = self.proc
        try:
            await self._launch_instance(loop, automatic)
        except (RuntimeError, asyncio.TimeoutError):
            if not automatic or self.proc is previous: raise
            self.acceleration_fallback = True
            await self._launch_instance(loop, False)

    async def _launch_instance(self, loop, automatic):
        self.boot_cache = BootCache(self.runtime, self.state)
        boot = self.boot_cache.select()
        previous = self.proc
        try:
            await self._launch_attempt(loop, automatic, boot)
        except Exception:
            if not boot or self.proc is previous: raise
            self.boot_cache.disable(boot)
            await self._launch_attempt(loop, automatic, None)

    async def _launch_attempt(self, loop, automatic, boot):
        self.acquire()
        try:
            image = prepare_private_image(self.runtime, self.state)
            # Bind both ports together to avoid choosing the same ephemeral port twice.
            with socket.socket() as guest, socket.socket() as service:
                guest.bind(("127.0.0.1", 0)); service.bind(("127.0.0.1", 0))
                guest_port, self.port = guest.getsockname()[1], service.getsockname()[1]
            local = self.config.localInstance
            args = [str(self.runtime / "deps/qemu-system-x86_64.exe"), "-L", str(self.runtime / "deps/share"),
                    "-machine", "q35", "-cpu", "qemu64-v1" if automatic else local.cpuModel, "-m", local.memorySize,
                    "-hda", str(image), "-rtc", "base=utc", "-display", "none", "-device", "virtio-net-pci,netdev=net0",
                    "-chardev", f"socket,id=qga0,host=127.0.0.1,port={guest_port},server=on,wait=off",
                    "-device", "virtio-serial-pci", "-device", "virtserialport,chardev=qga0,name=org.qemu.guest_agent.0",
                    "-netdev", f"user,id=net0,hostfwd=tcp:127.0.0.1:{self.port}-:32767"]
            self.accelerator = "WHPX" if automatic else local.hardwareAccelerator if local.enableHardwareAcceleration else "TCG"
            if automatic: args.extend(["-accel", "whpx,kernel-irqchip=off", "-smp", str(min(2, os.cpu_count() or 1))])
            elif local.enableHardwareAcceleration: args.extend(["-accel", local.hardwareAccelerator])
            self.boot_mode = "direct" if boot else "disk"
            if boot:
                args.extend(["-kernel", str(self.boot_cache.directory / "vmlinuz"),
                             "-initrd", str(self.boot_cache.directory / "initramfs"),
                             "-append", boot["cmdline"], "-vga", "none"])
            self.log_file = (self.state / "qemu.log").open("wb")
            self.proc = await asyncio.create_subprocess_exec(*args, stdout=self.log_file, stderr=self.log_file,
                                                            creationflags=subprocess.CREATE_NO_WINDOW, cwd=self.state)
            async def connect():
                while True:
                    if self.proc.returncode is not None: raise RuntimeError("内置登录服务启动失败，请查看运行数据目录中的 qemu.log。")
                    try:
                        self.client.reader, self.client.writer = await asyncio.open_connection("127.0.0.1", guest_port)
                        await self.client.ping()
                        return
                    except (ConnectionError, OSError, asyncio.IncompleteReadError, ValueError):
                        if hasattr(self.client, "writer"): self.client.writer.close()
                        await asyncio.sleep(.5)
            await asyncio.wait_for(connect(), 45 if boot and automatic else 150)
            await self.prepare_guest_time()
            if boot:
                await self.boot_cache.prepare(self.client, boot)
            await self.client.write_file("/etc/wm-args", "-host 0.0.0.0 -port 32767")
            await self.client.execute("/sbin/rc-service", ["wrapper-manager", "start"])
            if not boot:
                try: await self.boot_cache.prepare(self.client, None)
                except Exception as error:
                    self.boot_cache.note = "快速引导缓存暂不可用，保留原引导方式：" + (str(error) or type(error).__name__)
        except BaseException:
            await self.terminate()
            raise

    async def prepare_guest_time(self):
        # Set time before starting account services; chronyd keeps synchronizing
        # in the background on subsequent boots, including after network recovery.
        await self.client.send_cmd("guest-set-time", {"time": time.time_ns()})
        original = await self.client.read_file("/etc/chrony/chrony.conf")
        updated = background_time_config(original)
        if updated == original: return
        await self.client.write_file("/etc/chrony/chrony.conf.am-new", updated)
        process = await self.client.execute("/bin/sh", ["-c",
            "set -e; cd /etc/chrony; test -e chrony.conf.am-backup || cp -p chrony.conf chrony.conf.am-backup; "
            "mv chrony.conf.am-new chrony.conf"])
        async def completed():
            while True:
                result = await self.client.send_cmd("guest-exec-status", {"pid": process["pid"]})
                if result.get("exited"):
                    if result.get("exitcode") != 0: raise RuntimeError("无法更新内置服务的时间同步配置。")
                    return
                await asyncio.sleep(.1)
        await asyncio.wait_for(completed(), 5)

    async def terminate(self):
        try:
            if self.proc and self.proc.returncode is None:
                try:
                    await asyncio.wait_for(self.client.execute("/sbin/poweroff", []), 3)
                    await asyncio.wait_for(self.proc.wait(), 10)
                except (Exception, asyncio.CancelledError):
                    if self.proc.returncode is None:
                        self.proc.terminate()
                        await self.proc.wait()
        finally:
            if hasattr(self.client, "writer"): self.client.writer.close()
            if self.log_file: self.log_file.close(); self.log_file = None
            if self.lock:
                import msvcrt
                self.lock.seek(0); msvcrt.locking(self.lock.fileno(), msvcrt.LK_UNLCK, 1)
                self.lock.close(); self.lock = None

    async def logs(self):
        return await self.client.read_file("/var/run/wrapper-manager/wrapper-manager.log")
