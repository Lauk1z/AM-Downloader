import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap

from test_artists import app, window, browser, wait
from musicdesk.widgets import AlbumRail, capture_content


def set_background(window):
    # Exaggerated asymmetric colors expose solid fills, moving backdrops and
    # wrong ancestor coordinates, including on fractional-DPI displays.
    image = QPixmap(240, 240)
    painter = QPainter(image)
    gradient = QLinearGradient(0, 0, 240, 240)
    gradient.setColorAt(0, QColor("#23516d")); gradient.setColorAt(1, QColor("#a75732"))
    painter.fillRect(image.rect(), gradient); painter.end()
    window.content_surface.backdrop = image
    window.content_surface.tint = .7
    window.content_surface.update(); wait(100)


def color_at(image, point):
    ratio = image.devicePixelRatio()
    return image.pixelColor(round(point.x() * ratio), round(point.y() * ratio))


def assert_background(window, transition, point, reference=None):
    surface = window.content_surface
    if reference is None: reference = color_at(surface.panel_cache.toImage(), transition.mapTo(surface, point))
    for progress in (0, .15, .5, .85, 1):
        transition.progress = progress
        frame = transition.grabFramebuffer()
        frame.setDevicePixelRatio(transition.devicePixelRatioF())
        actual = color_at(frame, point)
        assert max(abs(a - b) for a, b in zip(actual.getRgb(), reference.getRgb())) <= 2, (progress, actual.name(), reference.name())


@pytest.mark.parametrize("page", ["home", "artists", "settings"])
def test_page_background_stays_visible_during_navigation_and_interruption(window, page):
    set_background(window)
    window.navigate(page)
    if not window.stack.transition.isVisible():
        window.navigate("home"); window.navigate(page)
    transition = window.stack.transition; transition.clock.invalidate()
    # Page margins contain no foreground widgets, including the incoming offset.
    point = QPoint(8, transition.height() - 40)
    assert_background(window, transition, point)
    transition.progress = .4
    window.navigate("recent" if page != "home" else "artists")
    transition.clock.invalidate()
    assert_background(window, transition, point)


@pytest.mark.parametrize("page", ["home", "artists"])
def test_lyrics_background_stays_visible_when_opening_closing_and_reversing(window, page):
    set_background(window); window.navigate(page); wait(400)
    for progress in (1, 1, .4, 1):
        window.show_lyrics()
        transition = window.body.transition; transition.clock.invalidate()
        assert_background(window, transition, QPoint(8, transition.height() - 40))
        transition.progress = progress
        if progress == 1: transition.clear()


def test_nested_artist_transition_uses_its_own_background_coordinates(window):
    set_background(window)
    view = browser(window)
    view.select_artist("Artist 00")
    transition = view.details.transition; transition.clock.invalidate()
    assert_background(window, transition, QPoint(10, transition.height() - 40))


def test_album_slide_keeps_background_between_cards(window):
    set_background(window); window.navigate("home"); wait(400)
    rail = window.library_scroll.findChild(AlbumRail)
    rail.scroll_page(1)
    transition = rail.transition; transition.clock.invalidate()
    assert transition.isVisible()
    # The rail's bottom margin is transparent, even while its strip moves.
    assert_background(window, transition, QPoint(20, transition.height() - 1))


def test_resize_reflow_uses_current_background_size(window):
    set_background(window); window.navigate("home"); wait(400)
    window.resize(1200, 820)
    window.resize_timer.stop(); window.refresh_content()
    transition = window.stack.transition; transition.clock.invalidate()
    assert transition.isVisible()
    assert_background(window, transition, QPoint(8, transition.height() - 40))


def test_background_follows_cover_changes_and_empty_cover_without_recapturing(window, tmp_path):
    set_background(window); window.navigate("home")
    transition = window.stack.transition; transition.clock.invalidate()
    point = QPoint(8, transition.height() - 40)
    for color in ("#ee5683", "#168ea1", None):
        image = QPixmap()
        if color:
            image = QPixmap(240, 240); image.fill(QColor(color))
        window.content_surface.backdrop = image
        window.content_surface.update(); window.content_surface.repaint()
        base = QColor(window.content_surface.base)
        reference = QColor(*(round(a * .7 + b * .3) for a, b in zip(QColor(color).getRgb()[:3], base.getRgb()[:3]))) if color else base
        assert_background(window, transition, point, reference)
    transition.progress = .5
    transition.grabFramebuffer().save(str(tmp_path / "no-cover-transition.png"))


def test_content_snapshots_preserve_transparency_and_cropped_strip_coordinates(window):
    set_background(window); window.navigate("home"); wait(400)
    image = capture_content(window.stack).toImage()
    assert color_at(image, QPoint(8, window.stack.height() - 40)).alpha() == 0
    rail = window.library_scroll.findChild(AlbumRail)
    full = capture_content(rail.widget())
    # Integer device-pixel origin avoids unrelated subpixel rasterization shifts.
    ratio = full.devicePixelRatioF()
    rect = rail.widget().rect().adjusted(160, 0, -88, 0)
    cropped = capture_content(rail.widget(), rect).toImage()
    expected = full.toImage().copy(round(rect.x() * ratio), 0, cropped.width(), cropped.height())
    assert cropped == expected


def test_lyrics_last_frame_matches_live_background_around_widgets(window, tmp_path):
    set_background(window); window.navigate("home"); wait(400)
    window.show_lyrics()
    transition = window.body.transition; transition.clock.invalidate(); transition.progress = 1
    frame = transition.grabFramebuffer(); frame.setDevicePixelRatio(transition.devicePixelRatioF())
    frame.save(str(tmp_path / "lyrics-last-frame.png"))
    transition.clear(); wait(50)
    live = window.grab().toImage(); live.save(str(tmp_path / "lyrics-live-window.png"))
    for point in (QPoint(8, 200), QPoint(8, transition.height() - 40), QPoint(window.stack.width() - 5, 200)):
        actual = color_at(frame, point)
        expected = color_at(live, transition.mapTo(window, point))
        assert max(abs(a - b) for a, b in zip(actual.getRgb(), expected.getRgb())) <= 2
