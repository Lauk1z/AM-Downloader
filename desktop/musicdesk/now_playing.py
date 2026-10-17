"""The temporary playback list, separate from saved playlists and downloads."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QHeaderView, QTableWidgetItem, QMenu, QStackedWidget

from .core import duration_text, path_key
from .playlist_ui import TrackTable
from .playlists import move_entries
from .widgets import BlurPanel, RED, button, icon, label


class PlaybackPanels(QStackedWidget):
    def stop_scroll(self):
        # The lyric animation must stop even when switching to the queue.
        self.widget(0).stop_scroll()


class NowPlayingPanel(BlurPanel):
    def __init__(self, owner):
        super().__init__(base="#202022", tint=.08)
        self.owner = owner; self.indices = []
        layout = QVBoxLayout(self); layout.setContentsMargins(16, 18, 16, 16); layout.setSpacing(12)
        heading = QHBoxLayout(); heading.addWidget(label("正在播放", 16, True), 1)
        close = button("", "close", compact=True); close.setToolTip("收起正在播放队列")
        close.clicked.connect(owner.show_now_playing); heading.addWidget(close); layout.addLayout(heading)
        self.summary = label("", 9, color="#a0a0a9"); self.summary.setWordWrap(True); layout.addWidget(self.summary)
        self.table = TrackTable(0, 3); self.table.setHorizontalHeaderLabels(["", "曲目", "时长"])
        self.table.verticalHeader().hide(); self.table.setShowGrid(False)
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(self.table.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(self.table.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False); self.table.enable_reorder()
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 34); self.table.setColumnWidth(2, 76)
        self.table.verticalHeader().setDefaultSectionSize(55)
        self.table.cellDoubleClicked.connect(lambda row, _: owner.play_queue_row(self.indices[row]))
        self.table.rowsMoved.connect(self.move)
        self.table.filesDropped.connect(self.drop_paths)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.menu)
        layout.addWidget(self.table, 1)
        self.empty = label("从歌曲或专辑右键选择「下一首播放」或「最后播放」。", 10, color="#a0a0a9")
        self.empty.setWordWrap(True); layout.addWidget(self.empty)
        self.clear = button("清空播放队列"); self.clear.clicked.connect(owner.clear_playback_queue); layout.addWidget(self.clear)

    def refresh(self):
        owner, table = self.owner, self.table
        if owner.closing: return
        if table.drag_rows:
            QTimer.singleShot(100, self.refresh); return
        selected = {table.track_paths[row] for row in table.selected_rows() if row < len(table.track_paths)}
        position = table.verticalScrollBar().value()
        self.indices = list(range(len(owner.playlist)))
        if owner.shuffle.isChecked() and owner.current_path:
            by_path = {track.path: i for i, track in enumerate(owner.playlist)}
            upcoming = list(dict.fromkeys(owner.shuffle_order.upcoming(list(by_path), owner.current_path)))
            pending = [by_path[path] for path in upcoming if path in by_path and path != owner.current_path]
            self.indices = [i for i in self.indices if i not in pending and i != owner.play_index] + [owner.play_index] + pending
        table.setRowCount(len(self.indices)); table.track_paths = [owner.playlist[i].path for i in self.indices]
        for row, index in enumerate(self.indices):
            track = owner.playlist[index]
            values = [str(row + 1), track.title + "\n" + track.artist, duration_text(track.duration)]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value); item.setToolTip(track.title + " · " + track.artist)
                if index == owner.play_index: item.setForeground(QColor(RED))
                table.setItem(row, column, item)
            if index == owner.play_index:
                table.item(row, 0).setText(""); table.item(row, 0).setIcon(icon("player_play", RED, 14))
            if track.path in selected:
                table.selectionModel().select(table.model().index(row, 0), table.selectionModel().SelectionFlag.Select | table.selectionModel().SelectionFlag.Rows)
        table.verticalScrollBar().setValue(position)
        mode = "随机播放，显示本轮待播顺序；拖动或插入曲目会切回顺序播放" if owner.shuffle.isChecked() else "拖动调整顺序，双击播放"
        self.summary.setText(f"{len(owner.playlist)} 首歌曲 · {mode}")
        self.empty.setVisible(not owner.playlist); self.clear.setEnabled(bool(owner.playlist))

    def move(self, rows, destination):
        self.owner.playlist = move_entries([self.owner.playlist[i] for i in self.indices], rows, destination)
        self.owner.play_index = next((i for i, track in enumerate(self.owner.playlist) if track.path == self.owner.current_path), -1)
        self.owner.shuffle.setChecked(False)
        self.owner.persist_playback_queue()
        # Leave Qt's active drag source intact until dropEvent has returned.
        QTimer.singleShot(0, self.refresh)

    def drop_paths(self, paths, row):
        known = {path_key(track.path): track for track in self.owner.tracks}
        tracks = [known[path_key(path)] for path in paths if path_key(path) in known and known[path_key(path)].path != self.owner.current_path]
        if tracks:
            self.owner.playlist = [self.owner.playlist[i] for i in self.indices]
            self.owner.play_index = next((i for i, track in enumerate(self.owner.playlist) if track.path == self.owner.current_path), -1)
            self.owner.add_to_playback_queue(tracks, row=row)
        else: self.owner.toast("请先将这些音频导入资料库，再添加到播放队列。")

    def menu(self, point):
        row = self.table.rowAt(point.y())
        if row < 0: return
        if row not in self.table.selected_rows(): self.table.selectRow(row)
        rows = self.table.selected_rows(); menu = QMenu(self)
        menu.addAction("播放", lambda: self.owner.play_queue_row(self.indices[row]))
        menu.addAction("上移", lambda: self.move(rows, max(0, min(rows) - 1))).setEnabled(min(rows) > 0)
        menu.addAction("下移", lambda: self.move(rows, max(rows) + 2)).setEnabled(max(rows) < self.table.rowCount() - 1)
        menu.addSeparator(); menu.addAction("从播放队列移除", lambda: self.owner.remove_from_playback_queue([self.indices[i] for i in rows]))
        menu.exec(self.table.viewport().mapToGlobal(point))
