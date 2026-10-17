"""Archive the app and pristine runtime, never a user's mutable backend state."""
import json
import hashlib
import lzma
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
from musicdesk import APP_NAME, __version__
from build_backend import digest, SHA256

root = Path(__file__).resolve().parent
package = root / "dist" / APP_NAME
release = root / "release"; release.mkdir(exist_ok=True)
if not (package / (APP_NAME + ".exe")).is_file(): raise SystemExit("Run build.py first")
files = sorted(path for path in package.rglob("*") if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")
bundle = json.loads((package / "backend/bundle.json").read_text())
assert bundle["artifact_sha256"] == SHA256
pristine = package / "backend/assets/wrapper-manager.qcow2.xz"
assert digest(pristine) == bundle["pristine_archive_sha256"]
with lzma.open(pristine, "rb") as image:
    assert hashlib.file_digest(image, "sha256").hexdigest() == bundle["pristine_image_sha256"]
for path in files:
    relative = path.relative_to(package)
    assert path.name not in {"config.toml", "preferences.json", "creds.key", "GPAC.cfg", "instance.lock", ".am-backend"}, relative
    # setuptools ships a public test module named downloads, not downloaded music.
    assert "downloads" not in relative.parts or relative.as_posix().startswith("backend/.venv/Lib/site-packages/setuptools/tests/config/downloads/"), relative
    assert path.suffix != ".qcow2", relative
manifest = {path.relative_to(package).as_posix(): digest(path) for path in files}
(release / f"{APP_NAME}-{__version__}-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
archive = release / f"{APP_NAME}-{__version__}-Windows-x64.zip"
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
    for file in files:
        output.write(file, APP_NAME + "/" + file.relative_to(package).as_posix(),
                     compress_type=zipfile.ZIP_STORED if file == pristine else zipfile.ZIP_DEFLATED)
with zipfile.ZipFile(archive) as output:
    assert output.testzip() is None
checksum = digest(archive)
checksums = [f"{checksum}  {archive.name}"]
if "--7z" in sys.argv:
    compressor = shutil.which("7z") or str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "7-Zip/7z.exe")
    compact_archive = archive.with_suffix(".7z")
    # Use a new archive so removed files cannot survive from an earlier build.
    temporary = release / (compact_archive.name + ".partial")
    temporary.unlink(missing_ok=True)
    file_list = release / "package-files.txt"
    file_list.write_text("\n".join(APP_NAME + "/" + file.relative_to(package).as_posix() for file in files), encoding="utf-8")
    try:
        subprocess.run([compressor, "a", "-t7z", "-mx=7", "-m0=lzma2", "-ms=256m", "-mmt=4", "-scsUTF-8", str(temporary), "@" + str(file_list)], cwd=package.parent, check=True)
        subprocess.run([compressor, "t", str(temporary)], check=True)
        temporary.replace(compact_archive)
    finally:
        file_list.unlink(missing_ok=True)
        temporary.unlink(missing_ok=True)
    checksums.append(f"{digest(compact_archive)}  {compact_archive.name}")
    print(json.dumps({"archive": str(compact_archive), "bytes": compact_archive.stat().st_size}))
(release / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")
print(json.dumps({"archive": str(archive), "bytes": archive.stat().st_size, "files": len(files), "sha256": checksum}))
