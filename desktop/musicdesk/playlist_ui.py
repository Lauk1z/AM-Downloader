"""Custom playlist sidebar, drag targets and ordered song views."""
import json
from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal, QTimer, QUrl, QItemSelectionModel, QSize
from PySide6.QtGui import QColor, QDrag, QPainter, QPen
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QInputDialog, QMenu, QVBoxLayout, QAbstractItemView

from .core import IMPORT_EXTENSIONS, Track, path_key, scan_library
from .playlists import Playlists, entry, move_entries, read_m3u, source_path, write_m3u
from .widgets import MusicButton, RoundedTable, RED, button, icon, label, settle_layout

TRACK_MIME = "application/x-am-dowloader-tracks"


def mime_paths(mime):
    if mime.hasFormat(TRACK_MIME):
        try:
            values = json.loads(bytes(mime.data(TRACK_MIME)))
            if isinstance(values, list) and all(isinstance(value, str) for value in values): return values
        except (ValueError, UnicodeDecodeError): pass
        return []
    return [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]


class PlaylistButton(MusicButton):
    dropped = Signal(object)

    def __init__(self, name):
        super().__init__(name); self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if mime_paths(event.mimeData()):
            self.setDown(True); event.setDropAction(Qt.DropAction.CopyAction); event.accept()
        else: event.ignore()

    def dragLeaveEvent(self, event):
        self.setDown(False); event.accept()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        self.setDown(False)
        paths = mime_paths(event.mimeData())
        if not paths: event.ignore(); return
        self.dropped.emit(paths); event.setDropAction(Qt.DropAction.CopyAction); event.accept()


class TrackTable(RoundedTable):
    filesDropped = Signal(object, int)
    rowsMoved = Signal(object, int)

    def __init__(self, rows, columns, parent=None):
        super().__init__(rows, columns, parent)
        self.track_paths = []
        self.reorder = False
        self.drop_row = -1
        self.drag_rows = []
        self.drop_point = QPoint()
        self.drop_scroll = QTimer(self); self.drop_scroll.setInterval(16)
        self.drop_scroll.setTimerType(Qt.TimerType.PreciseTimer); self.drop_scroll.timeout.connect(self.scroll_drop)
        self.setDragEnabled(True); self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)

    def selected_rows(self):
        return sorted(index.row() for index in self.selectionModel().selectedRows())

    def track_mime(self):
        mime = QMimeData()
        paths = [self.track_paths[row] for row in self.selected_rows()]
        mime.setData(TRACK_MIME, json.dumps(paths).encode("utf-8"))
        # Virtual tracks must not become accidental whole-disc file copies.
        mime.setUrls([QUrl.fromLocalFile(path) for path in paths if path == source_path(path)])
        return mime

    def startDrag(self, actions):
        self.drag_rows = self.selected_rows()
        if not self.drag_rows: return
        drag = QDrag(self); drag.setMimeData(self.track_mime())
        # We perform row moves ourselves; never let Qt delete source songs.
        drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction, Qt.DropAction.CopyAction)
        self.drag_rows = []

    def enable_reorder(self):
        self.reorder = True; self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDragDropOverwriteMode(False)

    def dragEnterEvent(self, event):
        if self.reorder and mime_paths(event.mimeData()): event.acceptProposedAction()
        else: event.ignore()

    def insertion_row(self, point):
        row = self.rowAt(point.y())
        if row < 0: return self.rowCount()
        return row + (point.y() >= self.rowViewportPosition(row) + self.rowHeight(row) / 2)

    def dragMoveEvent(self, event):
        if not self.reorder or not mime_paths(event.mimeData()): event.ignore(); return
        self.drop_point = event.position().toPoint()
        self.drop_row = self.insertion_row(self.drop_point)
        self.viewport().update()
        if self.drop_point.y() < 28 or self.drop_point.y() > self.viewport().height() - 28:
            self.drop_scroll.start()
        else: self.drop_scroll.stop()
        event.setDropAction(Qt.DropAction.MoveAction if event.source() is self else Qt.DropAction.CopyAction); event.accept()

    def scroll_drop(self):
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() + (-8 if self.drop_point.y() < 28 else 8))
        self.drop_row = self.insertion_row(self.drop_point); self.viewport().update()

    def dragLeaveEvent(self, event):
        self.drop_scroll.stop(); self.drop_row = -1; self.viewport().update(); super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self.drop_scroll.stop()
        if not self.reorder: event.ignore(); return
        row = self.insertion_row(event.position().toPoint()); self.drop_row = -1
        if event.source() is self:
            self.rowsMoved.emit(self.drag_rows, row); event.setDropAction(Qt.DropAction.MoveAction)
        else:
            paths = mime_paths(event.mimeData())
            if not paths: event.ignore(); return
            self.filesDropped.emit(paths, row); event.setDropAction(Qt.DropAction.CopyAction)
        self.viewport().update(); event.accept()

    def hideEvent(self, event):
        self.drop_scroll.stop(); super().hideEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.drop_row < 0: return
        y = self.rowViewportPosition(self.drop_row) if self.drop_row < self.rowCount() else (self.rowViewportPosition(self.rowCount() - 1) + self.rowHeight(self.rowCount() - 1) if self.rowCount() else 2)
        painter = QPainter(self.viewport()); painter.setPen(QPen(QColor(RED), 2))
        painter.drawLine(3, y, self.viewport().width() - 3, y); painter.end()


class PlaylistUI:
    def __init__(self, owner):
        self.owner = owner
        self.data = Playlists(owner.store)
        self.buttons = {}
        self.busy = False

    def build_sidebar(self, section, navigation):
        add = button("", "plus", compact=True); add.setFixedSize(26, 26); add.setProperty("plain", True)
        add.setIconSize(QSize(14, 14))
        add.setToolTip("新建或导入歌单"); add.setAccessibleName("新建或导入歌单")
        add.clicked.connect(lambda: self.creation_menu(add)); section.addWidget(add)
        self.layout = QVBoxLayout(); self.layout.setSpacing(2); navigation.addLayout(self.layout)
        self.refresh_sidebar()

    def creation_menu(self, anchor):
        menu = QMenu(self.owner)
        menu.addAction("新建歌单", lambda: self.create())
        menu.addAction("导入 M3U 歌单…", self.choose_import)
        menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height())))

    def refresh_sidebar(self):
        for key, item in self.buttons.items():
            self.owner.nav.pop(key, None); self.layout.removeWidget(item); item.deleteLater()
        self.buttons = {}
        for playlist in self.data.items:
            key, name = playlist["id"], playlist["name"]
            item = PlaylistButton("  " + name); item.setIcon(icon("playlist", "#c6c6cd", 18))
            item.setAccessibleName(name); item.setCursor(Qt.CursorShape.PointingHandCursor)
            item.setText("  " + item.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, 146))
            item.setToolTip(name + "\n拖入歌曲以添加；右键重命名或导出")
            item.setMinimumHeight(34); item.setProperty("nav", True); item.setProperty("compact", True); item.setCheckable(True)
            item.setChecked(self.owner.current_page == key)
            item.clicked.connect(lambda _, key=key: self.owner.navigate(key))
            item.dropped.connect(lambda paths, key=key: self.add_paths(key, paths))
            item.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            item.customContextMenuRequested.connect(lambda point, key=key, item=item: self.menu(key, item.mapToGlobal(point)))
            self.layout.addWidget(item); self.buttons[key] = item; self.owner.nav[key] = item

    def create(self, entries=()):
        name, ok = QInputDialog.getText(self.owner, "新建歌单", "歌单名称", text="新建歌单")
        if not ok or not name.strip(): return
        item = self.data.create(name, entries); self.refresh_sidebar(); self.owner.navigate(item["id"])

    def rename(self, key):
        item = self.data.get(key)
        if not item: return
        name, ok = QInputDialog.getText(self.owner, "重命名歌单", "歌单名称", text=item["name"])
        if ok and name.strip():
            item["name"] = name.strip(); self.data.save(); self.refresh_sidebar()
            if self.owner.current_page == key: self.render(key)

    def delete(self, key):
        self.data.items = [item for item in self.data.items if item["id"] != key]
        self.data.save(); self.refresh_sidebar()
        if self.owner.current_page == key: self.owner.navigate("songs")

    def menu(self, key, point):
        menu = QMenu(self.owner)
        menu.addAction("重命名歌单", lambda: self.rename(key))
        menu.addAction("导出 M3U 歌单…", lambda: self.choose_export(key))
        menu.addSeparator(); action = menu.addAction("删除歌单", lambda: self.delete(key))
        action.setToolTip("只删除歌单，保留资料库和本地文件。")
        menu.exec(point)

    def add_menu(self, menu, tracks):
        submenu = menu.addMenu("加入歌单")
        values = [entry(track) for track in tracks]
        submenu.addAction("新建歌单…", lambda: self.create(values))
        for item in self.data.items:
            submenu.addAction(item["name"], lambda _, key=item["id"]: self.append(key, values))

    def append(self, key, values, row=None):
        item = self.data.get(key)
        if not item: return
        row = len(item["entries"]) if row is None else row
        item["entries"][row:row] = list(values); self.data.save()
        if self.owner.current_page == key: self.refresh(key)
        self.owner.toast(f'已添加 {len(values)} 首到「{item["name"]}」')

    def refresh(self, key, selected=()):
        # Keep the drag source alive until the native drop event returns.
        def update():
            if self.owner.closing or self.owner.current_page != key: return
            old = self.owner.library_scroll.findChild(TrackTable)
            position = old.verticalScrollBar().value() if old else 0
            self.render(key); settle_layout(self.owner.library_scroll)
            table = self.owner.library_scroll.findChild(TrackTable)
            table.verticalScrollBar().setValue(position)
            for row in selected:
                table.selectionModel().select(table.model().index(row, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        QTimer.singleShot(0, update)

    def move(self, key, rows, destination):
        item = self.data.get(key)
        if not item: return
        item["entries"] = move_entries(item["entries"], rows, destination); self.data.save()
        start = destination - sum(row < destination for row in set(rows))
        self.refresh(key, range(start, start + len(set(rows))))

    def remove(self, key, rows):
        item = self.data.get(key)
        if not item: return
        item["entries"] = [value for index, value in enumerate(item["entries"]) if index not in rows]
        self.data.save(); self.refresh(key)

    def resolved(self, key):
        known = {path_key(track.path): track for track in self.owner.tracks}
        return [known.get(path_key(value["path"])) for value in self.data.get(key)["entries"]]

    def play(self, key, row=None):
        tracks = self.resolved(key)
        if row is not None and tracks[row] is None:
            self.owner.toast("歌曲不可用，请重新导入，或恢复文件位置后重新扫描资料库。"); return
        available = [track for track in tracks if track is not None]
        if available: self.owner.play_tracks(available, available.index(tracks[row]) if row is not None else 0)

    def song_menu(self, key, table, point):
        row = table.rowAt(point.y())
        if row < 0: return
        if row not in table.selected_rows(): table.selectRow(row)
        rows = table.selected_rows(); menu = QMenu(self.owner)
        menu.addAction("播放", lambda: self.play(key, row)).setEnabled(self.resolved(key)[row] is not None)
        tracks = [track for index, track in enumerate(self.resolved(key)) if index in rows and track is not None]
        if tracks:
            self.owner.playback_queue_menu(menu, tracks)
            self.add_menu(menu, tracks)
        menu.addAction("上移", lambda: self.move(key, rows, max(0, min(rows) - 1))).setEnabled(min(rows) > 0)
        menu.addAction("下移", lambda: self.move(key, rows, max(rows) + 2)).setEnabled(max(rows) < table.rowCount() - 1)
        menu.addSeparator(); menu.addAction("从歌单移除", lambda: self.remove(key, rows))
        menu.exec(table.viewport().mapToGlobal(point))

    def render(self, key):
        item = self.data.get(key)
        if not item: self.owner.navigate("songs"); return
        page, layout = self.owner.page_layout()
        heading = QHBoxLayout(); name = label(item["name"], 28, True); name.setWordWrap(True); heading.addWidget(name, 1)
        play = button("播放全部", "play"); play.clicked.connect(lambda: self.play(key)); heading.addWidget(play)
        more = button("", "more"); more.setToolTip("歌单操作"); more.clicked.connect(lambda: self.menu(key, more.mapToGlobal(QPoint(0, more.height())))); heading.addWidget(more); layout.addLayout(heading)
        resolved = self.resolved(key); missing = sum(track is None for track in resolved)
        layout.addWidget(label(f'{len(resolved)} 首歌曲' + (f' · {missing} 首文件不可用' if missing else ''), 11, color="#9898a1"))
        hint = label("从歌曲列表拖到左侧歌单以添加；在下方拖动排序。支持 Ctrl / Shift 多选。", 10, color="#9898a1")
        hint.setWordWrap(True); layout.addWidget(hint)
        shown = [track or Track(value["path"], value.get("title", Path(value["path"]).stem), value.get("artist", ""), "", value.get("duration", 0)) for value, track in zip(item["entries"], resolved)]
        table = self.owner.track_table(shown, playlist_key=key); table.enable_reorder()
        table.setMinimumHeight(250)
        for row, track in enumerate(resolved):
            if track is None:
                table.item(row, 4).setText("文件不可用")
                for column in range(table.columnCount()): table.item(row, column).setForeground(QColor("#909098"))
        table.rowsMoved.connect(lambda rows, destination: self.move(key, rows, destination))
        table.filesDropped.connect(lambda paths, row: self.add_paths(key, paths, row))
        layout.addWidget(table, 1)
        if not resolved:
            table.setToolTip("把歌曲或本地音频文件拖到这里")
            layout.addWidget(label("歌单还是空的，把喜欢的歌曲拖进来吧。", 12, color="#9898a1"))
        play.setEnabled(any(track is not None for track in resolved))
        previous = self.owner.library_scroll.takeWidget()
        if previous: previous.deleteLater()
        self.owner.library_scroll.setWidget(page)

    def choose_import(self):
        filename, _ = QFileDialog.getOpenFileName(self.owner, "导入 M3U 歌单", "", "M3U 歌单 (*.m3u *.m3u8)")
        if filename: self.import_file(filename)

    def choose_export(self, key):
        item = self.data.get(key)
        safe_name = "".join("_" if char in '<>:"/\\|?*' else char for char in item["name"]).strip(" .") or "歌单"
        filename, chosen = QFileDialog.getSaveFileName(self.owner, "导出歌单（只保存引用，不复制音频）", safe_name + ".m3u8", "UTF-8 M3U8 (*.m3u8);;M3U 歌单 (*.m3u)")
        if not filename: return
        if not Path(filename).suffix: filename += ".m3u8" if "m3u8" in chosen else ".m3u"
        known = {path_key(track.path): track for track in self.owner.tracks}
        values = [entry(known[path_key(value["path"])]) if path_key(value["path"]) in known else value for value in item["entries"]]
        try: write_m3u(filename, item["name"], values)
        except (OSError, ValueError) as error: self.owner.toast("导出失败：" + str(error)); return
        self.owner.toast("歌单已导出：" + filename)

    def add_paths(self, key, paths, row=None):
        paths = [path for path in paths if Path(source_path(path)).suffix.lower() in IMPORT_EXTENSIONS]
        if not paths: self.owner.toast("请拖入歌曲或受支持的本地音频文件。"); return
        known = {path_key(track.path): track for track in self.owner.tracks}
        if all(path_key(path) in known for path in paths):
            self.append(key, [entry(known[path_key(path)]) for path in paths], row); return
        self.load(lambda: ("", [{"path": path, "title": Path(source_path(path)).stem, "artist": "", "duration": 0} for path in paths], []), key, row)

    def import_file(self, filename):
        self.load(lambda: read_m3u(filename))

    def load(self, read, key=None, row=None):
        if self.busy: self.owner.toast("正在导入歌单，请稍候…"); return
        from .window import Work
        from PySide6.QtCore import QThreadPool
        self.busy = True
        cache = self.owner.store.directory / "covers"
        def run():
            name, values, warnings = read()
            sources = list(dict.fromkeys(source_path(value["path"]) for value in values))
            tracks, errors = scan_library(None, cache, sources)
            by_path = {path_key(track.path): track for track in tracks}
            expanded = []
            for value in values:
                found = by_path.get(path_key(value["path"]))
                if found: expanded.append(entry(found)); continue
                segments = sorted((track for track in tracks if track.container and path_key(track.container) == path_key(value["path"])), key=lambda track: track.order)
                if segments: expanded.extend(entry(track) for track in segments)
                else: expanded.append(value)
            return name, expanded, tracks, warnings + errors
        def done(result):
            self.busy = False
            name, values, tracks, errors = result
            if not values and errors: self.owner.toast("未找到可导入的本地音乐引用。"); return
            if key is not None and not self.data.get(key): return
            for error in errors: self.owner.log(error)
            imported = list(self.owner.store.get("imported_files", []))
            self.owner.removed_files.difference_update(path_key(value["path"]) for value in values)
            self.owner.store.update({"imported_files": list(dict.fromkeys(imported + [source_path(value["path"]) for value in values])), "removed_files": sorted(self.owner.removed_files)})
            if key is None:
                item = self.data.create(name, values); self.refresh_sidebar(); self.owner.navigate(item["id"])
            else: self.append(key, values, row)
            self.owner.import_notice = f"歌单导入完成：{len(values)} 首" + (f"，{len(errors)} 项提示（详见日志）" if errors else "")
            self.owner.scan()
        def failed(message):
            self.busy = False; self.owner.toast("歌单导入失败：" + message)
        work = Work(run); work.signals.done.connect(done); work.signals.failed.connect(failed)
        self.owner.workers.append(work); QThreadPool.globalInstance().start(work)
