import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication
from musicdesk.appearance import create_application
from musicdesk.widgets import FeatureCard, cover_brand_style


@pytest.fixture(scope="module")
def app(): return QApplication.instance() or create_application([])


def luminance(rgb):
    linear = [v / 3294.6 if v <= 10 else ((v / 255 + .055) / 1.055) ** 2.4 for v in rgb]
    return sum(v * weight for v, weight in zip(linear, (.2126, .7152, .0722)))


@pytest.mark.parametrize("colors", [
    ["white"], ["black"], ["#808080"], ["#e6f1c7"], ["#142039"],
    ["black", "white"], ["#ff00b8", "#00ffff", "yellow", "#111111"],
    [f"#{v:02x}{v:02x}{v:02x}" for v in range(256)],
])
def test_brand_remains_legible_on_light_dark_and_mixed_pixels(colors):
    patch = QImage(len(colors), 1, QImage.Format.Format_RGB32)
    for x, color in enumerate(colors): patch.setPixelColor(x, 0, QColor(color))
    ink, backing = cover_brand_style(patch)
    if colors == ["white"]: assert ink == "#000000" and backing is None
    if colors == ["black"]: assert ink == "#ffffff" and backing is None
    if colors == ["black", "white"]: assert backing is not None
    text_light = luminance(QColor(ink).getRgb()[:3])
    for hover in (False, True):
        for color in colors:
            rgb = QColor(color).getRgb()[:3]
            if hover: rgb = [round(v * 240 / 255 + 15) for v in rgb]
            if backing:
                alpha = backing.alphaF()
                rgb = [round(v * (1 - alpha) + b * alpha) for v, b in zip(rgb, backing.getRgb()[:3])]
            background = luminance(rgb)
            contrast = (max(text_light, background) + .05) / (min(text_light, background) + .05)
            assert contrast >= 4.5, (color, hover, contrast)


@pytest.mark.parametrize("width", (184, 205, 240))
def test_brand_samples_local_cropped_cover_and_caches_hover(app, tmp_path, monkeypatch, width):
    import musicdesk.widgets as widgets
    calls = []
    original = widgets.cover_brand_style
    def record(image):
        result = original(image); calls.append(result); return result
    monkeypatch.setattr(widgets, "cover_brand_style", record)
    # A wide cover is center-cropped. The visible top strip is bright even
    # though most of the file, including its original top-right corner, is dark.
    source = QImage(1280, 640, QImage.Format.Format_RGB32); source.fill(QColor("#101010"))
    painter = QPainter(source); painter.fillRect(320, 0, 640, 150, QColor("#f8f8f8")); painter.end()
    path = tmp_path / "wide.png"; assert source.save(str(path))
    before = path.read_bytes()
    card = FeatureCard("Album", "Artist", str(path), width=width); card.show(); app.processEvents()
    try:
        card.grab(); app.processEvents(); card.grab()
        assert "color:#000000" in card.brand_text.styleSheet() and card.brand_backing is None
        count = len(calls)
        card.hovered = True; card.grab(); card.hovered = False; card.grab()
        assert len(calls) == count
        assert card.brand_icon.geometry().right() < card.brand_text.geometry().left()
        assert card.rect().contains(card.brand_text.geometry())
        card.clicked.connect(lambda: calls.append("clicked"))
        from PySide6.QtTest import QTest
        QTest.mouseClick(card.brand_text, Qt.MouseButton.LeftButton)
        assert calls[-1] == "clicked" and path.read_bytes() == before
    finally: card.close()


def test_brand_handles_missing_and_transparent_artwork(app, tmp_path):
    source = QImage(640, 640, QImage.Format.Format_ARGB32); source.fill(Qt.GlobalColor.transparent)
    path = tmp_path / "transparent.png"; assert source.save(str(path))
    for name in ("", str(path)):
        card = FeatureCard("No artwork", "Artist", name); card.show(); app.processEvents()
        try:
            assert not card.grab().isNull()
            assert "color:#ffffff" in card.brand_text.styleSheet()
        finally: card.close()
