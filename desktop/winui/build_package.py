"""Build an isolated, self-contained WinUI preview; never update the installed app."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import build_backend
import build_sacd


def copy_tree(source, target):
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(
        "bin", "obj", "artifacts", "__pycache__", "*.pyc", ".vs", ".git"))


def stage_backend(source, target):
    if source is None:
        build_backend.stage(target, compact=True)
        return
    source = source.resolve()
    metadata = json.loads((source / "bundle.json").read_text(encoding="utf-8"))
    if metadata["commit"] != build_backend.COMMIT or metadata["artifact_sha256"] != build_backend.SHA256:
        raise ValueError("Backend provenance does not match the pinned upstream artifact")
    if metadata.get("patch_version") != build_backend.backend_patches.PATCH_VERSION:
        raise ValueError("Stage the current backend patches before packaging")
    image = source / "assets/wrapper-manager.qcow2.xz"
    if metadata.get("image_compression") != "xz" or build_backend.digest(image) != metadata.get("pristine_archive_sha256"):
        raise ValueError("Pristine compressed backend image checksum mismatch")
    if metadata.get("pristine_image_sha256") != "15f154159ea191197b7d1859a104c6b140480ac0ed320d8076e4a48d3224ddda":
        raise ValueError("Unexpected pristine backend image")
    for file in source.rglob("*"):
        if not file.is_file():
            continue
        relative = file.relative_to(source)
        parts = relative.parts
        if "__pycache__" in parts or file.suffix == ".pyc":
            continue
        allowed = relative.as_posix() in build_backend.FILES | {"bundle.json", "PATCHES.md"}
        allowed |= parts[0] in {"src", ".venv"}
        allowed |= len(parts) == 2 and parts[0] == "assets" and file.name in {
            "device.wvd", "storefronts.json", "storefront_ids.json", "wrapper-manager.qcow2.xz"}
        allowed |= parts[0] == "deps" and (file.suffix.lower() == ".dll" or file.name.lower() in build_backend.TOOLS or "share" in parts)
        if parts[0] == ".venv":
            allowed &= build_backend.runtime_python_file(relative)
        if allowed:
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dotnet", default="dotnet")
    parser.add_argument("--backend", type=Path, help="Optional verified compact public backend to reuse")
    parser.add_argument("--output", type=Path, default=ROOT / "winui/artifacts/AM-Downloader-WinUI-preview-win-x64")
    args = parser.parse_args()
    target = args.output.resolve()
    if target.exists() or target.with_suffix(".zip").exists():
        raise FileExistsError("Use a new output path; existing packages are never replaced")
    packages = ROOT / "qa/winui-tools/packages"
    environment = os.environ.copy()
    environment.update(DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1",
        DOTNET_CLI_HOME=str(ROOT / "qa/winui-tools/cli"), NUGET_PACKAGES=str(packages), PYTHONDONTWRITEBYTECODE="1")
    subprocess.run([sys.executable, str(ROOT / "winui/build_native.py")], check=True, env=environment)
    subprocess.run([args.dotnet, "publish", str(ROOT / "winui/AMDownloader.WinUI/AMDownloader.WinUI.csproj"),
        "--configuration", "Release", "--output", str(target), "--verbosity", "minimal"], check=True, env=environment)
    stage_backend(args.backend, target / "vendor/backend")
    for name in ("musicdesk_worker.py", "musicdesk_backend.py", "musicdesk_boot.py", "LICENSE.txt"):
        shutil.copy2(ROOT / name, target / name)
    (target / "musicdesk").mkdir()
    for name in ("__init__.py", "core.py", "runtime.py", "discs.py", "metadata.py"):
        shutil.copy2(ROOT / "musicdesk" / name, target / "musicdesk" / name)
    copy_tree(ROOT / "winui/engine", target / "engine")
    (target / "native/bin").mkdir(parents=True)
    shutil.copy2(build_sacd.build(), target / "native/bin/sacd_extract.exe")
    shutil.copy2(ROOT / "winui/README.md", target / "README.md")
    shutil.copy2(ROOT / "winui/THIRD_PARTY_NOTICES.md", target / "THIRD_PARTY_NOTICES.md")
    licenses = target / "licenses"
    licenses.mkdir()
    for name in ("Python", "Mutagen", "Pillow", "tomlkit", "GPL-2.0", "GPL-3.0", "LGPL-2.1", "FFmpeg", "Bento4"):
        shutil.copy2(ROOT / "licenses" / (name + ".txt"), licenses / (name + ".txt"))
    dotnet_folder = Path(shutil.which(args.dotnet) or args.dotnet).resolve().parent
    for name in ("LICENSE.txt", "ThirdPartyNotices.txt"):
        source = dotnet_folder / name
        if source.is_file():
            shutil.copy2(source, licenses / ("dotnet-" + name))
    for dependency in json.loads((ROOT / "winui/AMDownloader.WinUI/obj/project.assets.json").read_text(encoding="utf-8"))["libraries"].values():
        if dependency.get("type") != "package":
            continue
        folder = packages / dependency["path"]
        for pattern in ("*license*", "*LICENSE*", "*NOTICE*", "*ThirdPartyNotices*"):
            for notice in folder.glob(pattern):
                if notice.is_file():
                    destination = licenses / dependency["path"] / notice.name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(notice, destination)
    source = target / "source"
    source.mkdir()
    copy_tree(ROOT / "winui", source / "winui")
    copy_tree(ROOT / "native", source / "native")
    copy_tree(ROOT / "boot-assets", source / "boot-assets")
    copy_tree(target / "musicdesk", source / "musicdesk")
    copy_tree(ROOT / "artwork", source / "artwork")
    (source / "tests").mkdir()
    for name in ("audio_fixtures.py", "disc_fixtures.py"):
        shutil.copy2(ROOT / "tests" / name, source / "tests" / name)
    for name in ("musicdesk_worker.py", "musicdesk_backend.py", "musicdesk_boot.py", "build_backend.py", "backend_patches.py", "build_sacd.py", "LICENSE.txt"):
        shutil.copy2(ROOT / name, source / name)
    copy_tree(licenses, source / "licenses")
    forbidden = [file.relative_to(target).as_posix() for file in target.rglob("*") if file.is_file()
        and (file.name == "preferences.json" or file.name.endswith(".qcow2") or
             any(part.lower().startswith(("pyside", "shiboken")) for part in file.relative_to(target).parts) or
             file.suffix.lower() == ".dll" and file.name.lower().startswith("qt"))]
    if forbidden:
        raise ValueError("Unexpected state or Qt runtime in package: " + ", ".join(forbidden))
    files = sorted(file for file in target.rglob("*") if file.is_file())
    hashes = {file.relative_to(target).as_posix(): build_backend.digest(file) for file in files}
    (target / "manifest.sha256.json").write_text(json.dumps(hashes, indent=2), encoding="utf-8")
    archive = target.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for file in sorted(target.rglob("*")):
            if file.is_file():
                output.write(file, str(Path(target.name) / file.relative_to(target)),
                    compress_type=zipfile.ZIP_STORED if file.suffix == ".xz" else zipfile.ZIP_DEFLATED)
    archive.with_suffix(".zip.sha256").write_text(build_backend.digest(archive) + "  " + archive.name + "\n", encoding="utf-8")
    print(json.dumps({"folder": str(target), "archive": str(archive), "files": len(hashes) + 1,
        "unpacked_bytes": sum(file.stat().st_size for file in target.rglob("*") if file.is_file()), "zip_bytes": archive.stat().st_size}, indent=2))


if __name__ == "__main__":
    main()
