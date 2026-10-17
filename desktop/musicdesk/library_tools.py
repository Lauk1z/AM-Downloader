"""Library filters and album-context metadata editing."""
from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QWidget, QDialog, QHBoxLayout, QVBoxLayout, QFormLayout, QGridLayout, QLineEdit, QTableWidgetItem, QHeaderView, QFileDialog, QAbstractItemView
from .scrolling import SmoothWheel

from .metadata import save_album_edits, find_duplicates
from .widgets import SettingsComboBox, Cover, TableSurface, button, label


def matches_filters(track, filters):
    return all(getattr(track, field) == value for field, value in filters.items() if value is not None)


def filter_bar(owner):
    bar = QWidget(); row = QGridLayout(bar); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(8)
    compact = owner.library_scroll.viewport().width() < 800
    for index, (field, title) in enumerate((("format_name", "格式"), ("rate", "采样率"), ("bits", "位深"), ("year", "年份"))):
        combo = SettingsComboBox(); combo.setMinimumWidth(100); combo.addItem("全部" + title, None)
        values = sorted({getattr(track, field) for track in owner.tracks})
        for value in values:
            text = str(value) if field in {"format_name", "year"} else f"{value / 1000:g} kHz" if field == "rate" else f"{value} bit"
            combo.addItem(text if value else "未知" + title, value)
        combo.setCurrentIndex(max(0, combo.findData(owner.library_filters.get(field))))
        def changed(_, field=field, combo=combo):
            owner.library_filters[field] = combo.currentData()
            owner.render_library()
        combo.currentIndexChanged.connect(changed); row.addWidget(combo, index // 2 if compact else 0, index % 2 if compact else index)
    clear = button("重置", compact=True)
    clear.clicked.connect(lambda: (owner.library_filters.clear(), owner.render_library())); row.addWidget(clear, 0, 2 if compact else 4)
    duplicates = button("查找重复", compact=True); duplicates.clicked.connect(lambda: show_duplicates(owner)); row.addWidget(duplicates, 1 if compact else 0, 2 if compact else 5)
    return bar


class AlbumEditor(QDialog):
    def __init__(self, owner, tracks):
        super().__init__(owner)
        self.owner, self.tracks, self.cover_path, self.saving = owner, list(tracks), "", False
        self.restore = None
        self.setWindowTitle("编辑标签与封面"); self.resize(900, 680)
        layout = QVBoxLayout(self); layout.setSpacing(12)
        top = QHBoxLayout(); self.cover = Cover(tracks[0].cover, 130, 8); top.addWidget(self.cover)
        form = QFormLayout(); self.fields = {}
        for field, title in (("album", "专辑"), ("album_artist", "专辑艺人"), ("year", "年份"), ("edition", "版本 / 分组")):
            values = {getattr(track, field) for track in tracks}
            edit = QLineEdit(str(next(iter(values))) if len(values) == 1 else "")
            edit.setPlaceholderText("多个值，留空保留" if len(values) > 1 else "")
            self.fields[field] = (edit, edit.text()); form.addRow(title, edit)
        top.addLayout(form, 1); layout.addLayout(top)
        actions = QHBoxLayout()
        artwork = button("替换封面", "folder"); artwork.clicked.connect(self.choose_cover); actions.addWidget(artwork)
        self.artist = QLineEdit(); self.artist.setPlaceholderText("批量设置歌曲艺人")
        actions.addWidget(self.artist, 1)
        apply = button("应用到所有曲目"); apply.clicked.connect(self.apply_artist); actions.addWidget(apply)
        layout.addLayout(actions)
        self.table = TableSurface(len(tracks), 4); self.table.setHorizontalHeaderLabels(["歌名", "艺人", "碟号", "曲序"])
        self.table.smooth_wheel = SmoothWheel(self.table)
        self.table.verticalHeader().hide(); self.table.setWordWrap(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(2, 65); self.table.setColumnWidth(3, 65)
        for row, track in enumerate(tracks):
            for column, field in enumerate(("title", "artist", "disc", "number")):
                self.table.setItem(row, column, QTableWidgetItem(str(getattr(track, field))))
        layout.addWidget(self.table, 1)
        note = label("直接编辑表格可逐曲修改；相同专辑艺人和版本名可合并分组。普通音频会写入标签并在原目录保留备份；CUE、SACD ISO 及不支持写入的格式保存到本机资料库。", 10, color="#9999a2")
        note.setWordWrap(True); layout.addWidget(note)
        self.message = label("", 10); self.message.setWordWrap(True); layout.addWidget(self.message)
        footer = QHBoxLayout(); footer.addStretch()
        self.cancel = button("取消"); self.cancel.clicked.connect(self.reject); footer.addWidget(self.cancel)
        self.save = button("保存修改", primary=True); self.save.clicked.connect(self.save_edits); footer.addWidget(self.save)
        layout.addLayout(footer)

    def choose_cover(self):
        path, _ = QFileDialog.getOpenFileName(self, "替换专辑封面", "", "图片 (*.jpg *.jpeg *.png *.webp *.bmp)")
        if path: self.cover_path = path; self.cover.set_source(path)

    def apply_artist(self):
        if not self.artist.text().strip(): return
        for row in range(self.table.rowCount()): self.table.item(row, 1).setText(self.artist.text().strip())

    def save_edits(self):
        from .window import Work
        try:
            shared = {}
            for field, (edit, original) in self.fields.items():
                if edit.text() != original: shared[field] = int(edit.text() or 0) if field == "year" else edit.text().strip()
            changes = []
            for row in range(self.table.rowCount()):
                values = dict(shared)
                for column, field in enumerate(("title", "artist", "disc", "number")):
                    text = self.table.item(row, column).text().strip()
                    values[field] = int(text or 0) if field in {"disc", "number"} else text
                if not values["title"] or not values["artist"]: raise ValueError("歌名和艺人不能为空")
                if any(not 0 <= values.get(field, 0) <= 9999 for field in ("year", "disc", "number")): raise ValueError("年份、碟号和曲序应为 0 至 9999 的整数")
                changes.append(values)
        except ValueError as error: self.message.setText("请检查输入：" + str(error)); return
        # Release the decoder's file handle before replacing a playing file.
        if any(track.path == self.owner.current_path for track in self.tracks):
            self.restore = (self.owner.current_path, self.owner.media.position(), self.owner.media.playbackState())
            self.owner.media.shutdown(); self.owner.media.setSource(QUrl())
        self.saving = True; self.save.setEnabled(False); self.cancel.setEnabled(False)
        self.setEnabled(False)
        self.message.setText("正在保存并备份原始标签…")
        cover_path = self.cover_path
        work = Work(lambda: save_album_edits(self.tracks, changes, self.owner.store.directory, cover_path))
        work.signals.done.connect(self.saved); work.signals.failed.connect(self.failed)
        self.owner.workers.append(work); QThreadPool.globalInstance().start(work)

    def saved(self, result):
        self.saving = False; self.setEnabled(True)
        self.restore_player()
        self.owner.scan()
        self.owner.toast(f"已保存：{result['files']} 个音频文件，{result['local']} 首资料库标签；原文件备份保存在音频目录。")
        self.accept()

    def failed(self, message):
        self.saving = False; self.setEnabled(True); self.save.setEnabled(True); self.cancel.setEnabled(True); self.message.setText("保存失败：" + message)
        self.restore_player()

    def restore_player(self):
        if not self.restore: return
        path, position, state = self.restore; self.restore = None
        if self.owner.current_path != path: return
        # Normal file edits release/reopen the same source and retain position.
        track = next((track for track in self.tracks if track.path == path), None)
        if track and not track.container:
            source = QUrl.fromLocalFile(path)
            self.owner.playback_restore = (source, position, state)
            self.owner.media.setSource(source)
        elif track: self.owner.play_current(autoplay=False)

    def reject(self):
        if not self.saving: super().reject()

    def closeEvent(self, event):
        if self.saving: event.ignore()
        else: super().closeEvent(event)


def show_duplicates(owner):
    from .window import Work
    import threading
    dialog = QDialog(owner); dialog.setWindowTitle("重复文件与相似曲目"); dialog.resize(1000, 620)
    layout = QVBoxLayout(dialog)
    status = label("正在计算文件校验值；不会自动删除任何文件。", 10); layout.addWidget(status)
    table = TableSurface(0, 5); table.setHorizontalHeaderLabels(["识别结果", "歌名", "版本 / 音质", "专辑", "文件位置"])
    table.smooth_wheel = SmoothWheel(table)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch); layout.addWidget(table, 1)
    note = label("完全相同表示文件字节一致；相似曲目可能是不同母带或编码版本，请比较后再到歌曲列表处理。双击可打开所在文件夹。", 10, color="#9999a2"); note.setWordWrap(True); layout.addWidget(note)
    locations = []
    def finished(groups):
        status.setText(f"找到 {len(groups)} 组结果")
        for group_index, (kind, tracks) in enumerate(groups, 1):
            for track in tracks:
                row = table.rowCount(); table.insertRow(row); locations.append(track.file_path)
                for column, text in enumerate((f"{group_index}. {kind}", track.title, track.edition or track.quality, track.album, track.file_path)):
                    item = QTableWidgetItem(text); item.setToolTip(text); table.setItem(row, column, item)
    from pathlib import Path
    table.cellDoubleClicked.connect(lambda row, _: QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(locations[row]).parent))))
    cancel = threading.Event(); dialog.finished.connect(lambda _: cancel.set())
    tracks = list(owner.tracks)
    work = Work(lambda: find_duplicates(tracks, cancel))
    work.signals.done.connect(finished); work.signals.failed.connect(status.setText)
    owner.workers.append(work); QThreadPool.globalInstance().start(work)
    dialog.show()
