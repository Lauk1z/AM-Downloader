"""Build the Windows WASAPI / ASIO host using the installed MSVC toolchain."""
from pathlib import Path
import os
import subprocess

ROOT = Path(__file__).resolve().parent


def build():
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio/Installer/vswhere.exe"
    install = subprocess.check_output([str(vswhere), "-latest", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"], text=True).strip()
    vcvars = Path(install) / "VC/Auxiliary/Build/vcvars64.bat"
    if not vcvars.is_file():
        raise RuntimeError("Install Visual Studio C++ x64 build tools and Windows SDK")
    output = ROOT / "native/bin"; output.mkdir(exist_ok=True)
    command = f'"{vcvars}" >nul && cl /nologo /std:c++17 /O2 /EHsc /MT /utf-8 /DUNICODE /D_UNICODE "{ROOT / "native/audio_engine.cpp"}" /Fe:"{output / "am_audio.exe"}" /Fo:"{output / "audio_engine.obj"}" /link ole32.lib uuid.lib avrt.lib advapi32.lib user32.lib'
    subprocess.run('cmd.exe /d /s /c "' + command + '"', cwd=ROOT, check=True)
    return output / "am_audio.exe"


if __name__ == "__main__":
    print(build())
