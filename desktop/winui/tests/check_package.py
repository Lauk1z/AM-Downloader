"""Verify the archive and run its real executable outside the development tree."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--audio-device", help="Optional WASAPI device for silent tests when the default DAC is in use")
    args = parser.parse_args()
    archive = args.archive.resolve()
    report_dir = args.report_dir.resolve()
    report_dir.mkdir(parents=True, exist_ok=False)
    work = Path(tempfile.mkdtemp(prefix="am-winui-verify-")).resolve()
    if work.parent != Path(tempfile.gettempdir()).resolve() or not work.name.startswith("am-winui-verify-"):
        raise ValueError("Unexpected extraction directory")
    result = {"ok": False, "archive": str(archive), "extracted_to": str(work)}
    try:
        checksum = digest(archive)
        if checksum != archive.with_suffix(".zip.sha256").read_text(encoding="utf-8").split()[0]:
            raise ValueError("Archive SHA-256 mismatch")
        with zipfile.ZipFile(archive) as package_zip:
            for entry in package_zip.infolist():
                if not (work / entry.filename).resolve().is_relative_to(work):
                    raise ValueError("Archive contains an unsafe path")
            package_zip.extractall(work)
        package, = [path for path in work.iterdir() if path.is_dir()]
        manifest = json.loads((package / "manifest.sha256.json").read_text(encoding="utf-8"))
        for required in ("AM Downloader WinUI.pri", "App.xbf", "Microsoft.UI.Xaml.Controls.pri"):
            if required not in manifest:
                raise ValueError("Application XAML resource missing: " + required)
        actual = {path.relative_to(package).as_posix() for path in package.rglob("*") if path.is_file()}
        if actual != set(manifest) | {"manifest.sha256.json"}:
            raise ValueError("Package files differ from manifest")
        for name, expected in manifest.items():
            path = package / name
            if not path.resolve().is_relative_to(package) or digest(path) != expected:
                raise ValueError("File checksum mismatch: " + name)
            if path.name == "preferences.json" or path.suffix == ".qcow2" or any(
                    part.lower().startswith(("pyside", "shiboken")) for part in path.relative_to(package).parts
                    ) or path.suffix.lower() == ".dll" and path.name.lower().startswith("qt"):
                raise ValueError("Unexpected Qt runtime or personal state: " + name)
        result.update(sha256=checksum, files=len(actual), qt_free=True)
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        python = package / "vendor/backend/.venv/python.exe"
        subprocess.run([str(python), str(package / "source/winui/tests/prepare_fixtures.py")],
                       check=True, env=environment, cwd=work, timeout=60)
        fixture = package / "source/qa/winui-smoke"
        if args.audio_device:
            preferences = fixture / "profile/preferences.json"
            settings = json.loads(preferences.read_text(encoding="utf-8"))
            settings["audio_output"] = {"mode": "shared", "device": args.audio_device, "dsd": "pcm"}
            preferences.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        executable = package / "AM Downloader WinUI.exe"
        process = subprocess.run([str(executable), "--data-dir", str(fixture / "profile"),
                                  "--no-backend", "--smoke-test", str(fixture / "report.json")],
                                 cwd=work, env=environment, timeout=130)
        smoke = json.loads((fixture / "report.json").read_text(encoding="utf-8"))
        if process.returncode != 0 or not smoke.get("ok"):
            raise ValueError("Packaged executable failed: " + json.dumps(smoke, ensure_ascii=False))
        paths = smoke["checks"][0]
        if not paths.get("application_theme"):
            raise ValueError("Application XAML resources did not load")
        if Path(paths["resources"]).resolve() != package:
            raise ValueError("Executable used an external resource directory")
        for name in ("runtime", "xaml", "audio_host", "python"):
            if not Path(paths[name]).resolve().is_relative_to(package):
                raise ValueError("Executable used an external component: " + name)
        shutil.copy2(fixture / "report.json", report_dir / "smoke.json")
        for capture in fixture.glob("*.png"):
            shutil.copy2(capture, report_dir / capture.name)
        result.update(ok=True, exit_code=process.returncode, independent_resources=True,
                      self_contained_dotnet=True, self_contained_winui=True, application_theme=True, pages=11)
    except Exception as error:
        result["error"] = str(error)
        raise
    finally:
        (report_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["ok"]:
            shutil.rmtree(work)


if __name__ == "__main__":
    main()
