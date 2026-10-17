import os
import sys
from pathlib import Path
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from . import APP_NAME


def create_application(arguments):
    # Use the bundled decoders rather than OS-installed codec packs.
    os.environ["QT_MEDIA_BACKEND"] = "ffmpeg"
    # Select the rasterizer before Qt creates its platform/font integration.
    if sys.platform == "win32":
        os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=freetype")
    app = QApplication(arguments)
    app.setApplicationName(APP_NAME); app.setOrganizationName("MusicDesk")
    if sys.platform == "win32":
        # Load both installed faces explicitly: the legacy Windows font lookup
        # can otherwise return the regular TTC face for a bold request.
        fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for name in ("msyh.ttc", "msyhbd.ttc"):
            if (fonts / name).is_file(): QFontDatabase.addApplicationFont(str(fonts / name))
    font = QFont("Microsoft YaHei UI", 10)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.NoSubpixelAntialias)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(font)
    return app
