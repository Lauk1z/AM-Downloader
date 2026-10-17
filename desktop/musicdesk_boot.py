"""Checked, per-image direct boot cache. The guest's on-disk kernel stays intact."""
import asyncio
import base64
import gzip
import hashlib
import json
from pathlib import Path
import shlex

VERSION = 1
ROM_SHA256 = "9c49e255340c78fc12e54ed043462bca02fb7fca29b7cfab62ff88a5344b6950"
MARKER = "am_fastboot=1"


def digest(path):
    with Path(path).open("rb") as source: return hashlib.file_digest(source, "sha256").hexdigest()


def patch_initramfs(compressed):
    raw, result, offset, changed = gzip.decompress(compressed), bytearray(), 0, 0
    while offset + 110 <= len(raw):
        header = bytearray(raw[offset:offset + 110])
        if header[:6] != b"070701": raise ValueError("Unsupported initramfs format")
        size, namesize = int(header[54:62], 16), int(header[94:102], 16)
        name = raw[offset + 110:offset + 110 + namesize]
        start = (offset + 110 + namesize + 3) & ~3
        if not name.endswith(b"\0") or start + size > len(raw): raise ValueError("Truncated initramfs")
        content = raw[start:start + size]
        if name.rstrip(b"\0") in (b"init", b"./init"):
            needle = b'\t$MOCK nlplug-findfs $cryptopts -p /sbin/mdev ${KOPT_debug_init:+-d} \\\n\t\t${KOPT_uevent_buf_size:+-U $KOPT_uevent_buf_size} \\\n\t\t$KOPT_root'
            if content.count(needle) != 1: raise ValueError("Unsupported root discovery script")
            replacement = (b'\tmdev -s\n\tif [ -z "$cryptopts" ] && [ "$SINGLEMODE" != "yes" ] && '
                           b'findfs "$KOPT_root" >/dev/null 2>&1; then\n\t\t:\n\telse\n' + needle + b'\n\tfi')
            content = content.replace(needle, replacement)
            header[54:62] = f"{len(content):08x}".encode(); changed += 1
        result.extend(header + name); result.extend(b"\0" * (-len(result) % 4))
        result.extend(content); result.extend(b"\0" * (-len(result) % 4))
        offset = (start + size + 3) & ~3
        if name.rstrip(b"\0") == b"TRAILER!!!": break
    else: raise ValueError("Missing initramfs trailer")
    if changed != 1: raise ValueError("Missing or duplicate init script")
    result.extend(b"\0" * (-len(result) % 512))
    return gzip.compress(result, compresslevel=6, mtime=0)


def kernel_arguments(cmdline):
    parts = [part for part in cmdline.split() if not part.startswith(("BOOT_IMAGE=", "initrd=", "am_fastboot="))]
    roots = [part for part in parts if part.startswith("root=")]
    if len(roots) != 1 or not roots[0].startswith("root=UUID=") or "rootfstype=ext4" not in parts:
        raise ValueError("Unsupported guest root filesystem")
    return " ".join(parts + [MARKER])


async def guest_shell(client, command):
    async with asyncio.timeout(20):
        process = await client.send_cmd("guest-exec", {"path": "/bin/sh", "arg": ["-c", command], "capture-output": True})
        while True:
            result = await client.send_cmd("guest-exec-status", {"pid": process["pid"]})
            if result.get("exited"):
                if result.get("exitcode") != 0: raise RuntimeError("Guest boot preparation failed")
                return base64.b64decode(result.get("out-data", "")).decode()
            await asyncio.sleep(.05)


async def guest_bytes(client, path):
    handle = await client.send_cmd("guest-file-open", {"path": path})
    result = bytearray()
    try:
        while True:
            # A base64 response must fit the QGA client's 64 KiB line buffer.
            chunk = await client.send_cmd("guest-file-read", {"handle": handle, "count": 32768})
            result.extend(base64.b64decode(chunk["buf-b64"]))
            if chunk.get("eof"): return bytes(result)
            if not chunk.get("count") or len(result) > 64 * 1024 * 1024: raise ValueError("Invalid guest boot file")
    finally:
        await client.send_cmd("guest-file-close", {"handle": handle})


def background_dad(original):
    if "AM IPv4 fast boot" in original: return original
    if not original.startswith("#!/bin/sh\n") or "# Block ifup until DAD completion" not in original:
        raise ValueError("Unsupported DAD hook")
    guard = '''# AM IPv4 fast boot: kernel IPv6 DAD continues in the background.
if [ "$IFACE" = eth0 ] && grep -qw am_fastboot=1 /proc/cmdline &&
   ip -4 addr show dev "$IFACE" scope global | grep -q 'inet ' &&
   ip -4 route show default dev "$IFACE" | grep -q '^default '; then
    exit 0
fi
'''
    return original.replace("#!/bin/sh\n", "#!/bin/sh\n" + guard, 1)


class BootCache:
    def __init__(self, runtime, state):
        self.directory = Path(state) / "boot"
        self.image = Path(state) / "assets/wrapper-manager.qcow2"
        self.rom = Path(runtime) / "deps/share/linuxboot_dma.bin"
        self.note = ""

    def identity(self):
        stat = self.image.stat()
        return [stat.st_dev, stat.st_ino]

    def read(self):
        try:
            value = json.loads((self.directory / "boot.json").read_text(encoding="utf-8"))
            if value["version"] == VERSION and value["image"] == self.identity(): return value
        except (OSError, ValueError, KeyError, TypeError): pass
        return None

    def select(self):
        value = self.read()
        try:
            if not value or value.get("disabled"): return None
            if digest(self.rom) != ROM_SHA256: return None
            if any(digest(self.directory / name) != value["files"][name] for name in ("vmlinuz", "initramfs")): return None
            if kernel_arguments(value["cmdline"]) != value["cmdline"]: return None
            return value
        except (OSError, ValueError, KeyError, TypeError): return None

    def write(self, value):
        self.directory.mkdir(exist_ok=True)
        temporary = self.directory / "boot.json.partial"
        temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
        temporary.replace(self.directory / "boot.json")

    def disable(self, value):
        # Do not retry a known failing cache on every launch. A new image,
        # guest kernel or cache format causes preparation to run again.
        self.write(dict(value, disabled=True))
        self.note = "快速引导未成功，已回退原引导方式。"

    async def prepare(self, client, active):
        information = (await guest_shell(client, "sha256sum /boot/vmlinuz-virt /boot/initramfs-virt; cat /proc/cmdline")).splitlines()
        if len(information) != 3: raise ValueError("Unsupported guest boot files")
        sources = [line.split()[0] for line in information[:2]]
        if any(len(value) != 64 for value in sources): raise ValueError("Invalid guest boot hashes")
        cmdline = kernel_arguments(information[2])
        if active:
            if MARKER not in information[2].split() or sources != active["sources"] or cmdline != active["cmdline"]:
                raise RuntimeError("Guest boot cache no longer matches the image")
            return
        previous = self.read()
        if previous and previous.get("sources") == sources and previous.get("cmdline") == cmdline and (previous.get("disabled") or self.select()): return
        if not self.rom.is_file() or digest(self.rom) != ROM_SHA256: return
        kernel = await guest_bytes(client, "/boot/vmlinuz-virt")
        initrd = await guest_bytes(client, "/boot/initramfs-virt")
        if [hashlib.sha256(data).hexdigest() for data in (kernel, initrd)] != sources:
            raise ValueError("Guest boot files changed during export")
        initrd = await asyncio.to_thread(patch_initramfs, initrd)
        path = (await guest_shell(client, "for p in /etc/network/if-up.d/*; do if grep -q 'Block ifup until DAD completion' \"$p\"; then printf '%s\\n' \"$p\"; fi; done")).strip()
        if not path.startswith("/etc/network/if-up.d/") or "\n" in path: raise ValueError("Unsupported guest network hooks")
        original = await client.read_file(path)
        updated = background_dad(original)
        if updated != original:
            await client.write_file("/tmp/am-dad-new", updated)
            quoted = shlex.quote(path)
            temporary = shlex.quote(str(Path(path).parent).replace("\\", "/") + "/.am-dad-install")
            await guest_shell(client, "set -e; mkdir -p /var/lib/am-dowloader; "
                f"test -e /var/lib/am-dowloader/dad-original || cp -p {quoted} /var/lib/am-dowloader/dad-original; "
                f"cp -p {quoted} {temporary}; cat /tmp/am-dad-new > {temporary}; mv {temporary} {quoted}; rm /tmp/am-dad-new")
        self.directory.mkdir(exist_ok=True)
        files = {}
        for name, data in (("vmlinuz", kernel), ("initramfs", initrd)):
            temporary = self.directory / (name + ".partial")
            temporary.write_bytes(data); temporary.replace(self.directory / name)
            files[name] = hashlib.sha256(data).hexdigest()
        self.write({"version": VERSION, "image": self.identity(), "sources": sources, "files": files, "cmdline": cmdline})
        self.note = "已准备快速引导缓存，下次启动生效。"
