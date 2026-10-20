"""Wrap a verified, self-contained WinUI package in a per-user Inno Setup installer."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--iscc", type=Path, required=True)
    parser.add_argument("--version", required=True, help="For example: 2.0.0-preview.3")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    version = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)-preview\.(\d+)", args.version)
    if not version:
        parser.error("Use a numeric preview version, such as 2.0.0-preview.3")
    package = args.package.resolve(strict=True)
    manifest = json.loads((package / "manifest.sha256.json").read_text(encoding="utf-8"))
    actual = {p.relative_to(package).as_posix() for p in package.rglob("*") if p.is_file()}
    if actual != set(manifest) | {"manifest.sha256.json"}:
        raise ValueError("Package contents differ from its manifest")
    for relative, expected in manifest.items():
        path = (package / relative).resolve(strict=True)
        if not path.is_relative_to(package) or digest(path) != expected:
            raise ValueError("Package checksum mismatch: " + relative)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"AM-Downloader-{args.version}-WinUI3-Windows-x64-Setup.exe"
    if output.exists():
        raise FileExistsError("Use a new output path; existing installers are never replaced")
    script = Path(__file__).resolve().parent / "installer/AMDownloader.iss"
    subprocess.run([str(args.iscc.resolve(strict=True)), "/Qp", f"/DPackageDir={package}",
        f"/DReleaseVersion={args.version}", f"/DNumericVersion={'.'.join(version.groups())}",
        f"/DInstallerOutput={output_dir}", str(script)], check=True)
    checksum = digest(output)
    output.with_suffix(".exe.sha256").write_text(checksum + "  " + output.name + "\n", encoding="utf-8")
    print(json.dumps(dict(installer=str(output), bytes=output.stat().st_size, sha256=checksum), indent=2))


if __name__ == "__main__":
    main()
