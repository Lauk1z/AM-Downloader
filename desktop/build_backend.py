"""Stage only public files from the checksum-pinned upstream Windows artifact."""
import hashlib
import json
import lzma
from pathlib import Path, PurePosixPath
import shutil
import urllib.request
import zipfile
import backend_patches
from musicdesk_boot import ROM_SHA256

ROOT = Path(__file__).resolve().parent
COMMIT = "d1a9a10079a72a454ce013589a5a47d5c17c8aee"
UPSTREAM_ARTIFACT_URL = "https://nightly.link/WorldObservationLog/AppleMusicDecrypt/actions/artifacts/8095733521.zip"
URL = "https://github.com/Lauk1z/AM-Downloader/releases/download/v1.5.2/AppleMusicDecrypt-v2-runtime.zip"
SHA256 = "0d2b7b21b2cb9a6ad3f411ad88519de68a94f345c8b56b25ae1b61cc015bc428"
FILES = {"main.py", "config.example.toml", "pyproject.toml", "poetry.lock", "README.md", "LICENSE.txt", ".github/workflows/win-build.yml", "tools/install-deps.sh", "tools/login.py", "tools/logout.py"}
ASSETS = {"device.wvd", "storefronts.json", "storefront_ids.json", "wrapper-manager.qcow2"}
TOOLS = {"ffmpeg.exe", "gpac.exe", "mp4box.exe", "mp4decrypt.exe", "mp4edit.exe", "mp4extract.exe", "qemu-system-x86_64.exe"}
# These belong to the upstream development environment, not the desktop worker.
# Keep setuptools: Python 3.12's distutils compatibility is used by src.utils.
BUILD_PACKAGES = {"pip", "poetry", "poetry_core", "virtualenv", "build", "installer", "pbs_installer",
                  "findpython", "python_discovery", "distlib", "cleo", "crashtest", "rapidfuzz",
                  "fastjsonschema", "dulwich", "cachecontrol", "msgpack", "keyring", "pyproject_hooks",
                  "pkginfo", "requests_toolbelt", "shellingham", "trove_classifiers", "wheel",
                  "winpython", "sqlite_bro", "sv_ttk", "grpc_tools", "grpcio_tools"}


def runtime_python_file(path):
    parts = path.parts[1:]  # Relative to .venv.
    if parts[0] in {"Doc", "include", "libs", "tcl", "Scripts"} or parts == ("NEWS.txt",): return False
    if len(parts) > 1 and parts[0] == "Lib" and parts[1] in {"idlelib", "ensurepip", "tkinter", "turtledemo", "test"}: return False
    if parts[0] == "DLLs" and (parts[-1].startswith(("tcl", "tk", "_tkinter", "_test"))): return False
    if len(parts) > 2 and parts[:2] == ("Lib", "site-packages"):
        package = parts[2].split("-", 1)[0].lower()
        if package in BUILD_PACKAGES or parts[2:4] == ("setuptools", "tests"): return False
    return True


def digest(path):
    with Path(path).open("rb") as source: return hashlib.file_digest(source, "sha256").hexdigest()


def stage(target=None, *, compact=False):
    vendor = ROOT / "vendor"; vendor.mkdir(exist_ok=True)
    archive, target = vendor / "v2-clean.zip", Path(target) if target else vendor / "backend"
    marker = target / "bundle.json"
    if compact and target.exists() and any(target.iterdir()):
        raise RuntimeError("Compact staging requires an empty destination")
    if not archive.is_file():
        partial = archive.with_suffix(".partial")
        urllib.request.urlretrieve(URL, partial)
        if digest(partial) != SHA256: raise RuntimeError("Upstream artifact checksum mismatch")
        partial.replace(archive)
    if digest(archive) != SHA256: raise RuntimeError("Upstream artifact checksum mismatch")
    target.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        for entry in source.infolist():
            path = PurePosixPath(entry.filename)
            if path.is_absolute() or ".." in path.parts: raise ValueError("Unsafe archive path")
            if entry.is_dir() or "__pycache__" in path.parts or path.suffix == ".pyc": continue
            allowed = entry.filename in FILES or path.parts[0] in {"src", ".venv"}
            allowed |= path.parts[0] == "assets" and path.name in ASSETS and len(path.parts) == 2
            allowed |= path.parts[0] == "deps" and (path.suffix.lower() == ".dll" or path.name.lower() in TOOLS or "share" in path.parts)
            if compact and path.parts[0] == ".venv": allowed &= runtime_python_file(path)
            if allowed:
                destination = target.joinpath(*path.parts); destination.parent.mkdir(parents=True, exist_ok=True)
                if compact and entry.filename == "assets/wrapper-manager.qcow2":
                    destination = destination.with_suffix(".qcow2.xz")
                    image_hash = hashlib.sha256()
                    with source.open(entry) as incoming, lzma.open(destination, "wb", preset=6) as outgoing:
                        while chunk := incoming.read(4 * 1024 * 1024):
                            image_hash.update(chunk); outgoing.write(chunk)
                    continue
                with source.open(entry) as incoming, destination.open("wb") as outgoing: shutil.copyfileobj(incoming, outgoing)
    for name in TOOLS:
        if not (target / "deps" / name).is_file(): raise RuntimeError("Missing bundled tool: " + name)
    backend_patches.apply(target)
    rom = ROOT / "boot-assets/linuxboot_dma.bin"
    if digest(rom) != ROM_SHA256: raise RuntimeError("Direct boot ROM checksum mismatch")
    shutil.copy2(rom, target / "deps/share/linuxboot_dma.bin")
    info = {"upstream": "https://github.com/WorldObservationLog/AppleMusicDecrypt", "commit": COMMIT,
            "artifact_url": URL, "upstream_artifact_url": UPSTREAM_ARTIFACT_URL, "artifact_sha256": SHA256,
            "patch_version": backend_patches.PATCH_VERSION,
            "pristine_image_sha256": image_hash.hexdigest() if compact else digest(target / "assets/wrapper-manager.qcow2")}
    if compact:
        info["pristine_archive_sha256"] = digest(target / "assets/wrapper-manager.qcow2.xz")
        info["image_compression"] = "xz"
    marker.write_text(json.dumps(info, indent=2), encoding="utf-8")
    return target


if __name__ == "__main__": print(stage())
