import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QDialog, QTableWidgetItem, QVBoxLayout

from test_artists import app, window, browser, wait
from musicdesk.library_tools import AlbumEditor, show_duplicates
from musicdesk.playlists import entry
from musicdesk.widgets import BlurPanel, RoundedTable, TableSurface, STYLE, capture_content


def corners(widget):
    return [QPoint(1, 1), QPoint(widget.width() - 2, 1),
            QPoint(1, widget.height() - 2), QPoint(widget.width() - 2, widget.height() - 2)]


def pixel(image, point):
    ratio = image.devicePixelRatio()
    return image.pixelColor(round(point.x() * ratio), round(point.y() * ratio))


@pytest.mark.parametrize("rows", [0, 2, 40])
@pytest.mark.parametrize("table_class", [TableSurface, RoundedTable])
def test_table_outer_corners_clip_header_rows_scrollbars_and_snapshots(app, rows, table_class, tmp_path):
    panel = BlurPanel(base="#476576", tint=0); panel.setStyleSheet(STYLE)
    layout = QVBoxLayout(panel); layout.setContentsMargins(20, 20, 20, 20)
    table = table_class(rows, 4); table.verticalHeader().hide()
    table.setHorizontalHeaderLabels(["Title", "Artist", "Album", "Quality"])
    for column in range(4): table.setColumnWidth(column, 160)
    for row in range(rows):
        for column in range(4): table.setItem(row, column, QTableWidgetItem(f"Track {row} / {column}"))
    table.setShowGrid(False); layout.addWidget(table); panel.resize(600, 350); panel.show(); wait(80)
    try:
        for width, height in ((600, 350), (760, 280)):
            panel.resize(width, height); wait(40)
            for bottom in (False, True):
                if rows: table.selectRow(rows - 1 if bottom else 0)
                table.verticalScrollBar().setValue(table.verticalScrollBar().maximum() if bottom else 0)
                table.horizontalScrollBar().setValue(table.horizontalScrollBar().maximum() if bottom else 0)
                wait(30)
                live = panel.grab().toImage(); content = capture_content(table).toImage()
                for point in corners(table):
                    assert pixel(live, table.mapTo(panel, point)).name() == panel.base
                    assert pixel(content, point).alpha() == 0
                assert pixel(content, QPoint(table.width() // 2, 2)).alpha() == 255
        panel.grab().save(str(tmp_path / "rounded-table.png"))
    finally: panel.close()


@pytest.mark.parametrize("page", ["songs", "favourites", "album", "queue", "artists", "playlist"])
def test_library_and_queue_tables_share_outer_corners(window, page, tmp_path):
    if page == "album": page = next(iter(window.album_pages))
    if page == "playlist": page = window.custom_playlists.data.create("Corners", [entry(track) for track in window.tracks[:3]])["id"]
    if page == "favourites": window.favourites = {track.path for track in window.tracks[:2]}
    window.navigate(page); wait(400)
    tables = [window.queue_table] if page == "queue" else browser(window).album_tables[:1] if page == "artists" else window.library_scroll.findChildren(RoundedTable)
    assert tables
    for table in tables:
        image = capture_content(table).toImage()
        assert all(pixel(image, point).alpha() == 0 for point in corners(table))
    window.grab().save(str(tmp_path / (page.split(":")[0] + ".png")))
    window.show_lyrics(); wait(400)
    window.show_lyrics(); wait(400)
    tables = [window.queue_table] if page == "queue" else browser(window).album_tables[:1] if page == "artists" else window.library_scroll.findChildren(RoundedTable)
    for table in tables:
        image = capture_content(table).toImage()
        assert all(pixel(image, point).alpha() == 0 for point in corners(table))


def test_editor_and_duplicate_tables_keep_editing_and_round_corners(window, monkeypatch, tmp_path):
    editor = AlbumEditor(window, window.tracks[:2]); editor.show(); wait(80)
    editor.table.editItem(editor.table.item(0, 0)); wait(20)
    editor.table.item(0, 0).setText("Local unsaved edit")
    assert editor.table.item(0, 0).text() == "Local unsaved edit"
    try:
        image = capture_content(editor.table).toImage()
        assert all(pixel(image, point).alpha() == 0 for point in corners(editor.table))
        editor.grab().save(str(tmp_path / "editor.png"))
    finally: editor.reject()
    monkeypatch.setattr("musicdesk.library_tools.find_duplicates", lambda tracks, cancel: [("相似曲目", tracks[:2])])
    show_duplicates(window); wait(150)
    dialog = next(item for item in window.findChildren(QDialog) if item.isVisible() and item.windowTitle() == "重复文件与相似曲目")
    try:
        table = dialog.findChild(TableSurface)
        assert table.rowCount() == 2
        image = capture_content(table).toImage()
        assert all(pixel(image, point).alpha() == 0 for point in corners(table))
        dialog.grab().save(str(tmp_path / "duplicates.png"))
    finally: dialog.reject()
