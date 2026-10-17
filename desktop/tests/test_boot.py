import asyncio
import gzip
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
import musicdesk_boot as boot


NEEDLE = b'\t$MOCK nlplug-findfs $cryptopts -p /sbin/mdev ${KOPT_debug_init:+-d} \\\n\t\t${KOPT_uevent_buf_size:+-U $KOPT_uevent_buf_size} \\\n\t\t$KOPT_root'


def archive(entries):
    data = bytearray()
    for name, content in entries + [("TRAILER!!!", b"")]:
        fields = [1, 0o100755, 0, 0, 1, 1234, len(content), 0, 0, 0, 0, len(name) + 1, 0]
        data.extend(b"070701" + b"".join(f"{n:08x}".encode() for n in fields) + name.encode() + b"\0")
        data.extend(b"\0" * (-len(data) % 4)); data.extend(content); data.extend(b"\0" * (-len(data) % 4))
    return gzip.compress(data)


def test_initrd_preserves_original_discovery_and_other_files():
    original = archive([("init", b"#!/bin/sh\n" + NEEDLE), ("untouched", b"binary\0content")])
    updated = gzip.decompress(boot.patch_initramfs(original))
    assert NEEDLE in updated  # Discovery remains the fallback for unresolved/encrypted roots.
    assert b'findfs "$KOPT_root"' in updated and b'"$SINGLEMODE" != "yes"' in updated
    assert b"binary\0content" in updated
    assert updated[:54] == gzip.decompress(original)[:54]  # Mode/owner/mtime unchanged.
    for data in (b"broken", archive([("init", b"different script")]), archive([("other", NEEDLE)]),
                 archive([("init", NEEDLE), ("./init", NEEDLE)])):
        with pytest.raises((ValueError, OSError, EOFError)): boot.patch_initramfs(data)


def test_cmdline_uses_guest_root_and_dad_guard_preserves_normal_boot():
    assert boot.kernel_arguments("BOOT_IMAGE=vmlinuz root=UUID=abc rootfstype=ext4 quiet initrd=initramfs") == "root=UUID=abc rootfstype=ext4 quiet am_fastboot=1"
    for value in ("root=/dev/mapper/crypt rootfstype=ext4", "root=UUID=abc rootfstype=btrfs", "quiet"):
        with pytest.raises(ValueError): boot.kernel_arguments(value)
    original = "#!/bin/sh\n# Block ifup until DAD completion\nwhile pending; do sleep .2; done\n"
    updated = boot.background_dad(original)
    assert "grep -qw am_fastboot=1 /proc/cmdline" in updated and "scope global" in updated and "route show default" in updated
    assert updated.endswith(original.removeprefix("#!/bin/sh\n"))
    assert boot.background_dad(updated) == updated


def cache_fixture(tmp_path):
    cache = boot.BootCache(tmp_path / "runtime", tmp_path / "state")
    cache.image.parent.mkdir(parents=True); cache.image.write_bytes(b"private account")
    cache.rom.parent.mkdir(parents=True)
    cache.rom.write_bytes((Path(__file__).resolve().parents[1] / "boot-assets/linuxboot_dma.bin").read_bytes())
    cache.directory.mkdir()
    files = {}
    for name in ("vmlinuz", "initramfs"):
        (cache.directory / name).write_bytes(name.encode()); files[name] = hashlib.sha256(name.encode()).hexdigest()
    record = {"version": boot.VERSION, "image": cache.identity(), "files": files, "sources": ["a" * 64, "b" * 64],
              "cmdline": "root=UUID=abc rootfstype=ext4 am_fastboot=1"}
    cache.write(record)
    return cache, record


def test_cache_corruption_replacement_and_disabled_cache(tmp_path):
    cache, record = cache_fixture(tmp_path)
    assert cache.select() == record
    (cache.directory / "initramfs").write_bytes(b"corrupt")
    assert cache.select() is None
    (cache.directory / "initramfs").write_bytes(b"initramfs")
    replacement = cache.image.with_suffix(".new"); replacement.write_bytes(b"different account image"); replacement.replace(cache.image)
    assert cache.select() is None
    record["image"] = cache.identity(); cache.write(record)
    cache.disable(record)
    assert cache.select() is None and cache.read()["disabled"]
    assert cache.image.read_bytes() == b"different account image"


def test_direct_boot_retries_original_boot_once_but_not_cancel_or_lock(tmp_path, monkeypatch):
    import musicdesk_backend as backend
    cache, record = cache_fixture(tmp_path)
    instance = object.__new__(backend.BundledInstance)
    instance.state, instance.runtime, instance.proc = cache.image.parents[1], cache.rom.parents[2], object()
    attempts = []
    async def attempt(loop, automatic, active):
        attempts.append(active is not None)
        if active:
            instance.proc = object(); raise RuntimeError("Direct boot failed")
    instance._launch_attempt = attempt
    asyncio.run(instance._launch_instance(None, True))
    assert attempts == [True, False] and cache.read()["disabled"]
    cache.write(record); attempts.clear()
    async def locked(*args): attempts.append(True); raise RuntimeError("Locked")
    instance._launch_attempt = locked
    with pytest.raises(RuntimeError): asyncio.run(instance._launch_instance(None, True))
    assert attempts == [True] and not cache.read().get("disabled")
    async def cancelled(*args): raise asyncio.CancelledError()
    instance._launch_attempt = cancelled
    with pytest.raises(asyncio.CancelledError): asyncio.run(instance._launch_instance(None, True))
    assert not cache.read().get("disabled")


def test_firmware_silent_disk_boot_and_stale_kernel_rejected(tmp_path, monkeypatch):
    cache, record = cache_fixture(tmp_path)
    response = "a" * 64 + "  /boot/vmlinuz-virt\n" + "b" * 64 + "  /boot/initramfs-virt\n"
    async def shell(*args): return response + "root=UUID=abc rootfstype=ext4"
    monkeypatch.setattr(boot, "guest_shell", shell)
    with pytest.raises(RuntimeError): asyncio.run(cache.prepare(None, record))
    async def shell(*args): return response.replace("a" * 64, "c" * 64) + record["cmdline"]
    monkeypatch.setattr(boot, "guest_shell", shell)
    with pytest.raises(RuntimeError): asyncio.run(cache.prepare(None, record))
