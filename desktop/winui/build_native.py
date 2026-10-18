"""Build the WinUI native output host separately from the installed Qt release."""
from pathlib import Path
import os
import subprocess

root = Path(__file__).resolve().parent.parent
vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio/Installer/vswhere.exe"
install = subprocess.check_output([str(vswhere), "-latest", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"], text=True).strip()
vcvars = Path(install) / "VC/Auxiliary/Build/vcvars64.bat"
if not vcvars.is_file():
    raise RuntimeError("MSVC x64 build tools and Windows SDK are required")
output = root / "winui/artifacts/native"
output.mkdir(parents=True, exist_ok=True)
command = f'"{vcvars}" >nul && cl /nologo /std:c++17 /O2 /EHsc /MT /utf-8 /DUNICODE /D_UNICODE "{root / "native/audio_engine.cpp"}" /Fe:"{output / "am_audio.exe"}" /Fo:"{output / "audio_engine.obj"}" /link ole32.lib uuid.lib avrt.lib advapi32.lib user32.lib'
subprocess.run('cmd.exe /d /s /c "' + command + '"', cwd=root, check=True)
print(output / "am_audio.exe")
