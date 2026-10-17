import json
import threading
import time
import uuid
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QTimer, QRunnable, QObject, Signal, QThreadPool, QSize, QPoint, QEvent
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QKeySequence, QPalette, QShortcut
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWidgets import (QApplication, QWidget, QFrame, QVBoxLayout,
    QHBoxLayout, QGridLayout, QLineEdit, QComboBox,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QSlider, QDialog, QTextEdit, QFormLayout,
    QFileDialog, QPlainTextEdit, QMenu, QToolTip)

from . import APP_NAME, __version__
from .core import Store, CODECS, STAGES, IMPORT_EXTENSIONS, path_key, trash_audio, duration_text, read_config, update_config, scan_library, validate_links, valid_backend, redact
from .client import BackendClient
from .accounts import Accounts
from .shuffle import ShuffleOrder
from .playlist_ui import PlaylistUI, TrackTable
from .scrolling import SmoothScrollArea
from .library_tools import AlbumEditor, filter_bar, matches_filters
from .discs import prepare_track
from .runtime import code_root
from .login import LoginDialog
from .playback import PlaybackEngine
from .audio_settings import AudioSettings
from .now_playing import NowPlayingPanel, PlaybackPanels
from .output_chain import OutputChainDialog
from .tray import SystemTray
from .artists import ArtistBrowser
from .chrome import AlbumWindow
from .icons import IconLabel
from .lyrics import LyricsPanel, LyricsArea
from .runtime import is_managed
from .widgets import AlbumCard, AlbumRail, AnimatedPageStack, BlurPanel, FeatureCard, Cover, RoundedTable, PlayerLabel, PlaybackSlider, VolumeSlider, VolumePopup, SettingsComboBox, RED, STYLE, button, icon, label, settle_layout


def album_page_key(track):
    return "album:" + json.dumps(track.album_key, ensure_ascii=False)


class ResultSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class Work(QRunnable):
    def __init__(self, fn):
        super().__init__(); self.fn = fn; self.signals = ResultSignals()

    def run(self):
        try:
            self.signals.done.emit(self.fn())
        except Exception as error:
            self.signals.failed.emit(str(error))


class MusicWindow(AlbumWindow):
    def __init__(self, root, data_dir, parent=None):
        super().__init__(parent)
        QApplication.setStyle("Fusion")
        palette = QPalette()
        for role, color in ((QPalette.ColorRole.Window, "#202022"), (QPalette.ColorRole.Base, "#27272c"), (QPalette.ColorRole.WindowText, "#eeeeF2"), (QPalette.ColorRole.Text, "#eeeeF2"), (QPalette.ColorRole.Button, "#333338"), (QPalette.ColorRole.ButtonText, "#eeeeF2"), (QPalette.ColorRole.Highlight, "#6a3a4b"), (QPalette.ColorRole.HighlightedText, "#ffffff"), (QPalette.ColorRole.PlaceholderText, "#909098")):
            palette.setColor(role, QColor(color))
        QApplication.setPalette(palette)
        self.root = Path(root)
        self.store = Store(data_dir)
        self.accounts = Accounts(self.store)
        self.login_window = None
        self.auto_login_attempted = False
        self.tracks, self.playlist, self.albums = [], [], {}
        self.sidebar_albums = {}
        self.album_pages = {}
        self.artist_state = {}
        self.shuffle_order = ShuffleOrder()
        self.library_filters = {}
        self.custom_playlists = PlaylistUI(self)
        self.play_request = 0
        self.preparing = False
        self.gap_waiting = False
        self.gap_timer = QTimer(self); self.gap_timer.setSingleShot(True); self.gap_timer.setInterval(2000)
        self.gap_timer.setTimerType(Qt.TimerType.PreciseTimer); self.gap_timer.timeout.connect(self.finish_track_gap)
        self.restore_queue = self.store.get("playback_queue")
        self.output_dialog = None
        self.play_index, self.current_path = -1, ""
        self.current_page = "home"
        self.recently_played = self.store.get("recently_played", [])
        self.restore_path = self.store.get("last_track") or (next(iter(self.recently_played), "") if self.restore_queue is None else "")
        self.favourites = set(self.store.get("favourites", []))
        self.removed_files = {path_key(path) for path in self.store.get("removed_files", [])}
        self.jobs = self.store.get("jobs", [])
        for job in self.jobs:
            if job.get("state") not in {"DONE", "FAILED", "cancelled"}:
                job["state"] = "queued"
        self.active_job = None
        self.format_dialog = None
        self.queue_paused = bool(self.jobs)
        self.closing = False
        self.restart_requested = False
        self.scanning = False
        self.scan_again, self.importing, self.import_notice = False, False, ""
        self.workers = []
        self.search_serial = 0
        self.search_results, self.search_message = [], ""
        self.network = QNetworkAccessManager(self)
        self.art_cache = {}
        self.client = BackendClient(self.root, self)
        self.client.event.connect(self.backend_event)
        self.client.message.connect(self.log)
        self.setWindowTitle(f"{APP_NAME} · 音乐")
        self.setWindowIcon(icon("app", RED, 64))
        self.resize(1440, 900)
        self.setMinimumSize(1100, 720)
        self.setStyleSheet(STYLE)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(self.store.get("volume", 65) / 100)
        self.media = PlaybackEngine(self.audio, self.root, self.store.get("audio_output"), self)
        self.playback_restore = None
        self.media.positionChanged.connect(self.position_changed)
        self.media.durationChanged.connect(self.duration_changed)
        self.media.playbackStateChanged.connect(self.playback_changed)
        self.media.mediaStatusChanged.connect(self.media_status)
        self.media.errorOccurred.connect(lambda *_: self.toast("播放失败：" + self.media.errorString()))
        self.build_ui()
        self.media.outputChanged.connect(self.update_output_details)
        self.update_output_details()
        self.refresh_queue()
        self.resize_timer = QTimer(self); self.resize_timer.setSingleShot(True); self.resize_timer.timeout.connect(self.refresh_content)
        self.search_timer = QTimer(self); self.search_timer.setSingleShot(True); self.search_timer.timeout.connect(self.search_changed)
        self.search.textChanged.connect(lambda _: self.search_timer.start(280))
        self.search.returnPressed.connect(self.search_changed)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.add_dialog)
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.choose_audio_files)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.search.setFocus)
        QShortcut(QKeySequence("Ctrl+Right"), self, activated=lambda: self.skip(1))
        QShortcut(QKeySequence("Ctrl+Left"), self, activated=lambda: self.skip(-1))
        QTimer.singleShot(0, self.scan)
        self.setAcceptDrops(True)
        self.init_chrome(self.player_bar, self.now_playing, self.brand_icon)
        self.tray = SystemTray(self)
        if hasattr(self, "minimize_button"):
            self.minimize_button.clicked.disconnect(self.showMinimized)
            self.minimize_button.clicked.connect(self.tray.minimize)
            self.minimize_button.setToolTip("最小化到系统托盘")
            self.close_button.setToolTip("关闭主窗口（可选择收起到托盘）")

    def build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        outer = QHBoxLayout(central); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        self.sidebar = BlurPanel(base="#202025", tint=.10); self.sidebar.setObjectName("sidebar"); self.sidebar.setFixedWidth(224)
        side = QVBoxLayout(self.sidebar); side.setContentsMargins(8, 13, 8, 12); side.setSpacing(10)
        branding = QHBoxLayout(); branding.setContentsMargins(10, 0, 7, 0); branding.setSpacing(8)
        self.brand_icon = IconLabel("app", RED, 23); branding.addWidget(self.brand_icon)
        branding.addWidget(label(APP_NAME, 12, True)); branding.addStretch()
        refresh = button("", "refresh", compact=True); refresh.setFixedSize(28, 28); refresh.setProperty("plain", True); refresh.setToolTip("重新扫描资料库"); refresh.clicked.connect(self.scan); branding.addWidget(refresh); side.addLayout(branding)
        self.search = QLineEdit(); self.search.setObjectName("sidebarSearch"); self.search.setPlaceholderText("搜索")
        catalog_search = self.search.addAction(icon("search", "#a0a0aa", 16), QLineEdit.ActionPosition.TrailingPosition)
        catalog_search.setToolTip("搜索 Apple Music 曲库"); catalog_search.triggered.connect(self.open_catalog_search)
        self.search.setFixedHeight(34); side.addWidget(self.search)
        navigation = SmoothScrollArea(); navigation.setWidgetResizable(True); navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        nav_body = QWidget(); nav_layout = QVBoxLayout(nav_body); nav_layout.setContentsMargins(0, 0, 0, 0); nav_layout.setSpacing(3)
        self.nav = {}
        def add_nav(key, symbol, title, indented=False):
            item = button("  " + title, symbol, compact=True); item.setMinimumHeight(34)
            item.setProperty("nav", True); item.setProperty("indented", indented); item.setCheckable(True)
            item.clicked.connect(lambda _, page=key: self.navigate(page)); nav_layout.addWidget(item); self.nav[key] = item
        add_nav("home", "home", "主页")
        library_heading = QHBoxLayout(); library_heading.setContentsMargins(12, 17, 0, 7); library_heading.setSpacing(10)
        library_heading.addWidget(IconLabel("library", "#a7a7b0", 18)); library_heading.addWidget(label("资料库", 10, True, "#a7a7b0")); library_heading.addStretch(); nav_layout.addLayout(library_heading)
        for key, symbol, title in (("recent", "recent", "最近添加"), ("artists", "artist", "艺人"), ("albums", "album", "专辑"), ("songs", "songs", "歌曲")):
            add_nav(key, symbol, title, True)
        section = QHBoxLayout(); section.setContentsMargins(12, 17, 0, 7); section.setSpacing(10)
        section.addWidget(IconLabel("playlist", "#a7a7b0", 18)); section.addWidget(label("播放列表", 10, True, "#a7a7b0")); section.addStretch(); nav_layout.addLayout(section)
        add_nav("favourites", "favourites", "喜爱的歌曲", True)
        add_nav("queue", "download", "下载队列", True)
        self.custom_playlists.build_sidebar(section, nav_layout)
        self.album_shortcuts = QVBoxLayout(); self.album_shortcuts.setSpacing(2); nav_layout.addLayout(self.album_shortcuts)
        nav_layout.addStretch(); navigation.setWidget(nav_body); side.addWidget(navigation, 1)
        self.notice = label("", 9, color="#92929e"); self.notice.setContentsMargins(12, 0, 0, 0); self.notice.setMaximumWidth(203); side.addWidget(self.notice)
        self.backend_dot = label("●  后端待命", 8, color="#92929e"); self.backend_dot.setContentsMargins(12, 0, 0, 0); side.addWidget(self.backend_dot)
        footer = QHBoxLayout(); settings = button("  设置", "settings", compact=True); settings.setProperty("nav", True); settings.setCheckable(True); settings.clicked.connect(lambda: self.navigate("settings")); self.nav["settings"] = settings; footer.addWidget(settings, 1)
        add = button("", "plus", compact=True); add.setProperty("plain", True); add.setFixedWidth(32); add.setToolTip("添加音乐 · Ctrl+L"); add.clicked.connect(self.add_dialog); footer.addWidget(add); side.addLayout(footer)
        outer.addWidget(self.sidebar)
        self.content_surface = BlurPanel(base="#202022", tint=.045)
        main = QVBoxLayout(self.content_surface); main.setContentsMargins(0, 0, 0, 0); main.setSpacing(0); outer.addWidget(self.content_surface, 1)
        self.player_bar = self.build_player(); main.addWidget(self.player_bar)
        self.stack = AnimatedPageStack()
        self.lyrics = LyricsPanel(); self.playback_queue = NowPlayingPanel(self)
        self.panels = PlaybackPanels(); self.panels.addWidget(self.lyrics); self.panels.addWidget(self.playback_queue)
        self.body = LyricsArea(self.stack, self.panels); main.addWidget(self.body, 1)
        self.lyrics.seek_requested.connect(self.seek_lyrics)
        self.body.transition.finished.connect(lambda: self.position_changed(self.media.position()))
        self.library_scroll = SmoothScrollArea(); self.library_scroll.setWidgetResizable(True); self.library_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); self.stack.addWidget(self.library_scroll)
        self.queue_page = self.build_queue(); self.stack.addWidget(self.queue_page)
        self.settings_page = self.build_settings(); self.stack.addWidget(self.settings_page)
        self.search_scroll = SmoothScrollArea(); self.search_scroll.setWidgetResizable(True); self.search_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); self.stack.addWidget(self.search_scroll)
        self.navigate("home")

    def build_player(self):
        player = BlurPanel(base="#252527", tint=.02); player.setObjectName("player"); player.setFixedHeight(64)
        layout = QHBoxLayout(player); layout.setContentsMargins(12, 6, 14, 6); layout.setSpacing(6)
        transport = QWidget(); controls = QHBoxLayout(transport); controls.setContentsMargins(0, 0, 0, 0); controls.setSpacing(4); controls.addStretch()
        self.shuffle = button("", "player_shuffle", compact=True); self.shuffle.setCheckable(True); self.shuffle.setToolTip("随机播放 · 每轮不重复"); self.shuffle.toggled.connect(self.shuffle_changed)
        previous = button("", "player_prev", compact=True); previous.clicked.connect(lambda: self.skip(-1)); previous.setToolTip("上一首")
        self.play_button = button("", "player_play", compact=True); self.play_button.clicked.connect(self.toggle_play); self.play_button.setToolTip("播放 / 暂停")
        next_button = button("", "player_next", compact=True); next_button.clicked.connect(lambda: self.skip(1)); next_button.setToolTip("下一首")
        self.repeat = button("", "player_repeat", compact=True); self.repeat.setCheckable(True); self.repeat.setToolTip("循环播放列表")
        for control, size in ((self.shuffle, 20), (previous, 26), (self.play_button, 28), (next_button, 26), (self.repeat, 20)):
            control.setProperty("plain", True); control.setFixedSize(36, 38); control.setIconSize(QSize(size, size)); controls.addWidget(control)
        controls.addStretch(); layout.addWidget(transport, 4)
        self.now_playing = BlurPanel(base="#363638", tint=.015, radius=4); self.now_playing.setMinimumWidth(310); self.now_playing.setFixedHeight(52)
        now = QHBoxLayout(self.now_playing); now.setContentsMargins(0, 0, 0, 0); now.setSpacing(0)
        self.play_cover = Cover(size=52, radius=3); now.addWidget(self.play_cover)
        info = QWidget(); meta = QGridLayout(info); meta.setContentsMargins(0, 1, 0, 0); meta.setHorizontalSpacing(0); meta.setVerticalSpacing(0)
        meta.setColumnMinimumWidth(0, 42); meta.setColumnStretch(1, 1); meta.setColumnMinimumWidth(2, 42)
        self.quality_button = button("", "player_lossless", compact=True); self.quality_button.setProperty("plain", True); self.quality_button.setFixedSize(28, 22); self.quality_button.setEnabled(False)
        self.quality_button.setIcon(icon("player_lossless", "#99999c")); self.quality_button.setIconSize(QSize(20, 20))
        self.quality_button.clicked.connect(self.show_output_chain)
        meta.addWidget(self.quality_button, 0, 0, Qt.AlignmentFlag.AlignLeft)
        title_row = QHBoxLayout(); title_row.setContentsMargins(0, 0, 0, 0); title_row.setSpacing(5); title_row.addStretch()
        self.play_title = PlayerLabel(APP_NAME, True, "#dedee0"); title_row.addWidget(self.play_title)
        self.more_button = button("", "player_more", compact=True); self.more_button.setIcon(icon("player_more", RED)); self.more_button.setProperty("plain", True); self.more_button.setFixedSize(22, 22); self.more_button.setToolTip("当前歌曲的更多操作"); self.more_button.setEnabled(False); self.more_button.clicked.connect(self.show_player_menu); title_row.addWidget(self.more_button)
        title_row.addStretch(); meta.addLayout(title_row, 0, 1)
        self.like_button = button("", "player_star", compact=True); self.like_button.setProperty("plain", True); self.like_button.setFixedSize(28, 22); self.like_button.setIconSize(QSize(13, 13)); self.like_button.setToolTip("加入喜爱"); self.like_button.clicked.connect(self.toggle_current_favourite); meta.addWidget(self.like_button, 0, 2, Qt.AlignmentFlag.AlignRight)
        self.play_artist = PlayerLabel("选择一首音乐开始播放", color="#a9a9ad"); self.play_artist.setContentsMargins(45, 0, 45, 0); self.play_artist.setFixedHeight(21); meta.addWidget(self.play_artist, 1, 0, 1, 3)
        self.elapsed = label("0:00", 8, color="#b8b8bb"); self.remaining = label("-0:00", 8, color="#b8b8bb")
        self.elapsed.setContentsMargins(5, 0, 0, 0); self.remaining.setContentsMargins(0, 0, 5, 0)
        for detail, column, alignment in ((self.elapsed, 0, Qt.AlignmentFlag.AlignLeft), (self.remaining, 2, Qt.AlignmentFlag.AlignRight)):
            policy = detail.sizePolicy(); policy.setRetainSizeWhenHidden(True); detail.setSizePolicy(policy)
            meta.addWidget(detail, 1, column, alignment | Qt.AlignmentFlag.AlignBottom); detail.hide()
        self.seek = PlaybackSlider(Qt.Orientation.Horizontal); self.seek.setObjectName("playbackProgress"); self.seek.setRange(0, 0); self.seek.setFixedHeight(8); self.seek.sliderMoved.connect(self.seek_to); meta.addWidget(self.seek, 2, 0, 1, 3)
        now.addWidget(info, 1); self.now_playing.installEventFilter(self); layout.addWidget(self.now_playing, 6)
        extras = QWidget(); right = QHBoxLayout(extras); right.setContentsMargins(0, 0, 0, 0); right.setSpacing(10); right.addStretch()
        self.volume_button = button("", "player_volume", compact=True); self.volume_button.setToolTip("音量"); self.volume_button.clicked.connect(self.show_volume); right.addWidget(self.volume_button)
        self.lyric_button = button("", "player_lyrics", compact=True); self.lyric_button.setObjectName("lyricsToggle"); self.lyric_button.setCheckable(True); self.lyric_button.setToolTip("显示歌词"); self.lyric_button.clicked.connect(self.show_lyrics); right.addWidget(self.lyric_button)
        queue = self.now_queue_button = button("", "player_queue", compact=True); queue.setCheckable(True); queue.setToolTip("显示正在播放队列"); queue.clicked.connect(self.show_now_playing); right.addWidget(queue)
        for control, size in ((self.volume_button, 22), (self.lyric_button, 25), (queue, 25)):
            control.setProperty("plain", True); control.setFixedSize(34, 36); control.setIconSize(QSize(size, size))
        right.addStretch(); layout.addWidget(extras, 3)
        self.volume_popup = VolumePopup(self); self.volume_popup.setObjectName("volumePopup")
        volume_row = QHBoxLayout(self.volume_popup); volume_row.setContentsMargins(12, 9, 12, 9); volume_row.setSpacing(10)
        self.volume_level_icon = IconLabel("player_volume", "#dedee0", 20); volume_row.addWidget(self.volume_level_icon)
        self.volume = VolumeSlider(); self.volume.setRange(0, 100); self.volume.setValue(round(self.audio.volume() * 100)); self.volume.setAccessibleName("音量"); self.volume.valueChanged.connect(self.set_volume); volume_row.addWidget(self.volume, 1)
        self.volume.sliderReleased.connect(self.volume_popup.leave_timer.start)
        volume_row.addWidget(IconLabel("player_volume_high", "#dedee0", 24))
        self.update_volume_icons(self.volume.value())
        self.quality = label("本地音乐", 8); self.quality.hide()
        return player

    def eventFilter(self, watched, event):
        if watched is getattr(self, "now_playing", None) and event.type() in (QEvent.Type.Enter, QEvent.Type.Leave):
            visible = event.type() == QEvent.Type.Enter and bool(self.current_path)
            self.elapsed.setVisible(visible); self.remaining.setVisible(visible)
        return super().eventFilter(watched, event)

    def show_volume(self):
        if self.media.direct:
            QToolTip.showText(self.volume_button.mapToGlobal(QPoint(0, 35)), "直通输出旁路软件音量，请用 DAC 调节音量。", self.volume_button)
            return
        if self.volume_popup.isVisible(): self.volume_popup.hide(); return
        self.elapsed.hide(); self.remaining.hide()
        QToolTip.hideText()
        anchor = self.volume_button.mapToGlobal(self.volume_button.rect().center())
        screen = self.screen().availableGeometry()
        right = min(screen.right() - 4, self.player_bar.mapToGlobal(QPoint(self.player_bar.width() - 12, 0)).x())
        x = max(screen.left() + 4, min(anchor.x() - 22, right - self.volume_popup.width()))
        self.volume_popup.background = QColor(self.player_bar.base)
        self.volume_popup.move(x, anchor.y() - self.volume_popup.height() // 2); self.volume_popup.show(); self.volume.setFocus()

    def show_player_menu(self):
        if not self.current_path: return
        track = self.playlist[self.play_index]
        menu = QMenu(self)
        menu.addAction("取消喜爱" if track.path in self.favourites else "加入喜爱", self.toggle_current_favourite)
        menu.addAction("查看专辑", lambda: self.open_album(self.albums.get(track.album_key, [track])))
        menu.addAction("音频输出链路", self.show_output_chain)
        menu.addAction("打开所在文件夹", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(track.file_path).parent))))
        menu.exec(self.more_button.mapToGlobal(QPoint(0, self.more_button.height())))

    def page_layout(self):
        widget = QWidget(); layout = QVBoxLayout(widget); layout.setContentsMargins(32, 28, 32, 30); layout.setSpacing(18)
        return widget, layout

    def build_queue(self):
        page, layout = self.page_layout()
        head = QHBoxLayout(); head.addWidget(label("下载队列", 26, True)); head.addStretch()
        self.resume_button = button("暂停队列", "pause"); self.resume_button.clicked.connect(self.toggle_queue); head.addWidget(self.resume_button)
        retry = button("重试失败", "refresh"); retry.clicked.connect(self.retry_failed); head.addWidget(retry)
        clear = button("清理已完成"); clear.clicked.connect(self.clear_completed); head.addWidget(clear); layout.addLayout(head)
        self.queue_summary = label("添加 Apple Music 链接，选择音质，开始下载。", 11, color="#8c8c95"); layout.addWidget(self.queue_summary)
        self.queue_table = self.table(["曲目 / 链接", "音质", "状态", "进度", "操作"])
        self.queue_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.queue_table.customContextMenuRequested.connect(self.queue_menu)
        self.queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for index, width in ((1, 125), (2, 140), (3, 105), (4, 80)): self.queue_table.setColumnWidth(index, width)
        layout.addWidget(self.queue_table, 1)
        info = QHBoxLayout(); self.speeds = label("下载 0 kB/s  ·  解密 0 kB/s", 10, color="#9999a1"); info.addWidget(self.speeds); info.addStretch()
        export = button("导出诊断日志", "download", compact=True); export.clicked.connect(self.export_logs); info.addWidget(export); layout.addLayout(info)
        self.logs = QPlainTextEdit(); self.logs.setReadOnly(True); self.logs.setMaximumBlockCount(700); self.logs.setFixedHeight(155); self.logs.setPlaceholderText("任务日志会显示在这里。程序不会记录账号密码。")
        layout.addWidget(self.logs)
        return page

    def build_settings(self):
        managed = is_managed(self.root)
        page, layout = self.page_layout(); layout.addWidget(label("设置", 26, True)); layout.addWidget(label("下载歌曲，按你的习惯管理音乐。" if managed else "连接已有下载器，按你的习惯管理音乐。", 11, color="#909099"))
        form_widget = QWidget(); form = QFormLayout(form_widget); form.setContentsMargins(0, 12, 0, 0); form.setVerticalSpacing(21); form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        if managed:
            form.addRow("下载工具", label("内置 AppleMusicDecrypt · 已集成运行环境", 11, color="#aaaaB2"))
        else:
            self.root_field = QLineEdit(str(self.root)); self.root_field.setReadOnly(True)
            root_row = QHBoxLayout(); root_row.addWidget(self.root_field); browse_root = button("选择目录"); browse_root.clicked.connect(self.choose_root); root_row.addWidget(browse_root); form.addRow("下载器安装目录", root_row)
        self.library_field = QLineEdit(str(self.library_folder())); self.library_field.setReadOnly(True)
        library_row = QHBoxLayout(); library_row.addWidget(self.library_field); browse_library = button("选择文件夹"); browse_library.clicked.connect(self.choose_library); library_row.addWidget(browse_library); form.addRow("音乐资料库", library_row)
        self.default_codec = SettingsComboBox()
        for value, text in CODECS.items(): self.default_codec.addItem(text, value)
        self.default_codec.setCurrentIndex(max(0, self.default_codec.findData(self.store.get("codec", "alac")))); form.addRow("默认下载音质", self.default_codec)
        self.language_combo = SettingsComboBox()
        for text, code in (("简体中文", "zh-Hans-CN"), ("繁體中文（香港）", "zh-Hant-HK"), ("English", "en-US"), ("日本語", "ja")):
            self.language_combo.addItem(text, code)
        self.rate_combo = SettingsComboBox()
        for value in (44100, 48000, 96000, 192000): self.rate_combo.addItem(f"{value / 1000:g} kHz", value)
        self.bits_combo = SettingsComboBox(); self.bits_combo.addItem("16 bit", 16); self.bits_combo.addItem("24 bit", 24)
        try:
            config = read_config(self.root)
            self.language_combo.setCurrentIndex(max(0, self.language_combo.findData(config["region"]["language"])))
            self.rate_combo.setCurrentIndex(max(0, self.rate_combo.findData(int(config["download"]["maxSampleRate"]))))
            self.bits_combo.setCurrentIndex(max(0, self.bits_combo.findData(int(config["download"]["maxBitDepth"]))))
            local = config["localInstance"]["enable"]
            backend_text = "内置本地服务 · 登录后即可下载" if managed else "本地 QEMU · 使用原安装的账号状态" if local else "远程 wrapper-manager"
        except Exception:
            backend_text = "请选择有效的 AppleMusicDecrypt 安装目录"
        form.addRow("元数据语言", self.language_combo); form.addRow("最高采样率", self.rate_combo); form.addRow("最高位深", self.bits_combo)
        backend = label(backend_text, 11, color="#7c7c87"); form.addRow("下载后端", backend); layout.addWidget(form_widget)
        actions = QHBoxLayout(); save = button("保存设置", primary=True); save.clicked.connect(self.save_settings); actions.addWidget(save)
        account = button("登录 Apple 账号"); account.clicked.connect(self.login_dialog); actions.addWidget(account)
        restart = button("重新连接后端", "refresh"); restart.clicked.connect(self.restart_backend); actions.addWidget(restart); actions.addStretch(); layout.addLayout(actions)
        self.settings_note = label("修改设置会保留原配置中的其他内容，并自动创建备份。", 10, color="#92929c"); self.settings_note.setWordWrap(True); layout.addWidget(self.settings_note)
        close_form = QFormLayout(); self.close_action = SettingsComboBox()
        for text, action in (("每次询问", "ask"), ("最小化到托盘", "tray"), ("关闭程序", "exit")): self.close_action.addItem(text, action)
        self.close_action.setCurrentIndex(max(0, self.close_action.findData(self.store.get("close_action", "ask"))))
        self.close_action.activated.connect(lambda _: self.store.set("close_action", self.close_action.currentData()))
        close_form.addRow("关闭主窗口时", self.close_action); layout.addLayout(close_form)
        self.audio_settings = AudioSettings(self.media, self.store)
        self.audio_settings.applied.connect(lambda _: self.update_output_details())
        self.audio_settings.applied.connect(lambda _: self.cancel_track_gap())
        layout.addWidget(self.audio_settings)
        chain = button("查看音频输出链路"); chain.clicked.connect(self.show_output_chain); layout.addWidget(chain, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(label("歌曲自然结束后，等待 2 秒再播放下一首；手动切歌立即响应。", 10, color="#92929c"))
        playback_note = label(
            "本地音频支持：\n"
            "AAC（.aac）、AAC／ALAC（.m4a、.m4b）、MP3（.mp3）、MP2（.mp2）、FLAC（.flac）、WAV（.wav）、AIFF／AIFC（.aif、.aiff、.aifc）。\n"
            "Ogg Vorbis／Opus／FLAC（.ogg、.oga）、Opus（.opus）、Speex（.spx）、WMA（.wma）、Musepack（.mpc、.mpp、.mp+）、AC-3（.ac3）、E-AC-3（.eac3、.ec3）。\n"
            "DSD（.dsf、.dff、.dsdiff）、APE（.ape）、WavPack（.wv）、TAK（.tak）、TTA（.tta）。\n"
            "CUE 整轨（.cue）和 SACD ISO（.iso）：按曲目导入、按需准备播放缓存。SACD 保留 DSD，可选择原生 / DoP；CUE 解码为 PCM。\n"
            "共享模式兼容所有现有解码格式；独占输出按设备实际能力选择。", 10, color="#92929c")
        playback_note.setWordWrap(True); layout.addWidget(playback_note)
        cache_row = QHBoxLayout()
        cache_note = label("CUE / SACD 的播放缓存按需生成，清理后会在下次播放时重新准备。", 10, color="#92929c"); cache_note.setWordWrap(True)
        cache_row.addWidget(cache_note, 1)
        clear_cache = button("清理播放缓存"); clear_cache.clicked.connect(self.clear_audio_cache); cache_row.addWidget(clear_cache)
        layout.addLayout(cache_row)
        layout.addStretch(); layout.addWidget(label(f"{APP_NAME} {__version__}  ·  基于 AppleMusicDecrypt 的桌面界面", 9, color="#aaaaB2"))
        scroll = SmoothScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(page)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return scroll

    def clear_audio_cache(self):
        if self.preparing: self.toast("正在准备曲目，请完成后再清理缓存。"); return
        folder = (self.store.directory / "audio-cache").resolve()
        active = self.media.source().toLocalFile()
        count = 0
        try:
            for path in folder.glob("*"):
                if path.is_file() and path.suffix in {".dsf", ".wav"} and path.resolve().parent == folder and path_key(path) != path_key(active):
                    path.unlink(); count += 1
            self.toast(f"已清理 {count} 个曲目缓存；当前曲目保留。")
        except OSError as error: self.toast("部分缓存未能清理：" + str(error))

    def library_folder(self):
        fallback = Path.home() / "Music" / APP_NAME if is_managed(self.root) else self.root / "downloads"
        return Path(self.store.get("library", str(fallback)))

    def table(self, headings, table_class=RoundedTable):
        table = table_class(0, len(headings)); table.setHorizontalHeaderLabels(headings)
        table.verticalHeader().hide(); table.verticalHeader().setDefaultSectionSize(56)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setShowGrid(False); table.horizontalHeader().setStretchLastSection(False)
        table.setAlternatingRowColors(False)
        return table

    def open_catalog_search(self):
        self.navigate("search")
        self.search_changed()

    def navigate(self, page):
        self.body.transition.clear()
        before = self.stack.capture_page() if page != self.current_page else None
        self.current_page = page
        for key, item in self.nav.items(): item.setChecked(key == page)
        self.search.setPlaceholderText("搜索 Apple Music" if page == "search" else "搜索资料库")
        if page == "queue": self.stack.setCurrentWidget(self.queue_page)
        elif page == "settings": self.stack.setCurrentWidget(self.settings_page)
        elif page == "search":
            self.stack.setCurrentWidget(self.search_scroll)
            if self.search_scroll.widget() is None: self.render_search([], animate=False)
            self.search.setFocus()
        else:
            self.stack.setCurrentWidget(self.library_scroll); self.render_library()
        if before is not None: self.stack.reveal_page(before)

    def scan(self):
        if self.scanning:
            self.scan_again = True; return
        self.scanning = True; self.notice.setText("正在读取音乐…")
        folder, cache = self.library_folder(), self.store.directory / "covers"
        imported, restore_path = list(self.store.get("imported_files", [])), self.restore_path
        excluded = self.removed_files.copy()
        if restore_path and path_key(restore_path) in excluded: restore_path = ""
        def read():
            tracks, errors = scan_library(folder, cache, imported, excluded)
            restored = next((track for track in tracks if restore_path and path_key(track.path) == path_key(restore_path)), None)
            if restore_path and restored is None:
                found, _ = scan_library(None, cache, [restore_path])
                restored = next(iter(found), None)
            return tracks, errors, restored
        work = Work(read)
        work.signals.done.connect(self.scan_finished); work.signals.failed.connect(self.scan_failed); self.workers.append(work); QThreadPool.globalInstance().start(work)

    def scan_finished(self, result):
        self.scanning = False
        if self.scan_again:
            self.scan_again = False; self.scan(); return
        self.tracks, errors, restored = result
        updated = {track.path: track for track in self.tracks}
        self.playlist = [updated.get(track.path, track) for track in self.playlist]
        current = updated.get(self.current_path)
        if current:
            self.play_cover.set_source(current.cover); self.set_backdrop(current.cover)
            self.play_title.setText(current.title); self.play_artist.setText(current.artist + " — " + current.album)
            self.play_title.setToolTip(current.title + " · " + current.quality)
        self.albums = {}
        for track in self.tracks: self.albums.setdefault(track.album_key, []).append(track)
        self.album_pages = {album_page_key(tracks[0]): sorted(tracks, key=lambda track: track.order) for tracks in self.albums.values()}
        self.notice.setText(f"{len(self.tracks)} 首歌曲")
        for error in errors: self.log(error)
        while self.album_shortcuts.count():
            item = self.album_shortcuts.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        for key in self.sidebar_albums: self.nav.pop(key, None)
        self.sidebar_albums = {}
        for key, tracks in list(self.album_pages.items())[:4]:
            shortcut = button("", compact=True); shortcut.setText("  " + shortcut.fontMetrics().elidedText(tracks[0].album, Qt.TextElideMode.ElideRight, 149)); shortcut.setProperty("nav", True); shortcut.setMinimumHeight(34); shortcut.setToolTip(tracks[0].album)
            if tracks[0].cover: shortcut.setIcon(QIcon(tracks[0].cover))
            self.sidebar_albums[key] = tracks; self.nav[key] = shortcut
            self.bind_album_menu(shortcut, tracks)
            shortcut.setCheckable(True); shortcut.setChecked(self.current_page == key)
            shortcut.setIconSize(QSize(21, 21)); shortcut.clicked.connect(lambda _, page=key: self.navigate(page)); self.album_shortcuts.addWidget(shortcut)
        if self.tracks and not self.current_path: self.set_backdrop(self.tracks[0].cover)
        if self.current_page.startswith("album:") and self.current_page not in self.album_pages:
            self.navigate("songs")
        else: self.render_library()
        if self.restore_queue is not None and not self.current_path:
            saved, self.restore_queue = self.restore_queue, None
            self.playlist = list({path: updated[path] for path in saved if path in updated}.values())
            if restored and restored.path not in [track.path for track in self.playlist]: self.playlist.append(restored)
            self.restore_path = ""
            if self.playlist:
                self.play_index = next((i for i, track in enumerate(self.playlist) if restored and track.path == restored.path), 0)
                self.play_current(autoplay=False)
        if self.restore_path:
            self.restore_path = ""
            if restored and not self.current_path:
                self.playlist = list(self.tracks) if restored in self.tracks else [restored]
                self.play_index = self.playlist.index(restored); self.play_current(autoplay=False)
        self.persist_playback_queue(); self.playback_queue.refresh()
        if self.output_dialog: self.output_dialog.refresh()
        if self.import_notice:
            message, self.import_notice = self.import_notice, ""
            self.toast(message)

    def scan_failed(self, message):
        self.scanning = False; self.toast(message)
        if self.scan_again:
            self.scan_again = False; self.scan()

    def filtered_tracks(self):
        query = self.search.text().strip().casefold()
        tracks = [track for track in self.tracks if not query or query in f"{track.title} {track.artist} {track.album}".casefold()]
        if self.current_page == "favourites": tracks = [track for track in tracks if track.path in self.favourites]
        return tracks if self.current_page == "home" else [track for track in tracks if matches_filters(track, self.library_filters)]

    def album_caption(self, track):
        artist = track.album_artist or track.artist
        versions = [key for key in self.albums if key[:2] == track.album_key[:2]]
        version = track.edition or (Path(track.file_path).parent.name if len(versions) > 1 else "")
        return artist + (" · " + version if version else "")

    def render_library(self):
        if self.current_page.startswith("playlist:"):
            self.custom_playlists.render(self.current_page); return
        if self.current_page in self.album_pages:
            tracks = self.album_pages[self.current_page]
            if not tracks: self.navigate("songs"); return
            widget, layout = self.page_layout(); layout.addWidget(self.hero(tracks)); layout.addWidget(self.track_table(tracks), 1)
            previous = self.library_scroll.takeWidget()
            if previous: previous.deleteLater()
            self.library_scroll.setWidget(widget)
            return
        if self.current_page not in {"home", "recent", "songs", "albums", "artists", "favourites"}: return
        if self.current_page == "home": self.render_home(); return
        widget, layout = self.page_layout()
        title = {"recent": "最近添加", "songs": "歌曲", "albums": "专辑", "artists": "艺人", "favourites": "喜爱的歌曲"}[self.current_page]
        header = QHBoxLayout(); header.addWidget(label(title, 28, True)); header.addStretch()
        play_all = button("播放全部", "play"); play_all.clicked.connect(lambda: self.play_tracks(self.filtered_tracks())); header.addWidget(play_all); layout.addLayout(header)
        tracks = self.filtered_tracks()
        subtitle = f"{len(tracks)} 首歌曲 · {len({track.album_key for track in tracks})} 张专辑"
        layout.addWidget(label(subtitle if tracks else "音乐会在这里，慢慢成为你的收藏。", 11, color="#9898a1"))
        layout.addWidget(filter_bar(self))
        if not tracks:
            empty = QVBoxLayout(); empty.setContentsMargins(0, 70, 0, 80); empty.addWidget(IconLabel("note", "#e8a0ac", 70), 0, Qt.AlignmentFlag.AlignCenter)
            hint = label("还没有匹配的音乐" if self.search.text() or any(value is not None for value in self.library_filters.values()) else "把喜爱的音乐留在这里", 18, True); hint.setAlignment(Qt.AlignmentFlag.AlignCenter); empty.addWidget(hint)
            text = label("粘贴 Apple Music 链接，或在设置中选择已有的音乐文件夹。", 11, color="#9999a2"); text.setAlignment(Qt.AlignmentFlag.AlignCenter); empty.addWidget(text)
            row = QHBoxLayout(); row.addStretch(); add = button("添加音乐", "plus", True); add.clicked.connect(self.add_dialog); row.addWidget(add); row.addStretch(); empty.addLayout(row)
            if self.current_page == "favourites":
                empty.setContentsMargins(0, 0, 0, 0)
                layout.addStretch()
            layout.addLayout(empty)
            layout.addStretch()
        elif self.current_page in {"songs", "favourites"}:
            layout.addWidget(self.track_table(tracks), 1)
        elif self.current_page == "artists":
            browser = ArtistBrowser(self, tracks, self.artist_state)
            layout.addWidget(browser, 1)
        else:
            albums = {}
            for track in tracks: albums.setdefault(track.album_key, []).append(track)
            available = max(340 if self.body.opened else 680, self.library_scroll.viewport().width() - 68)
            columns = max(2 if self.body.opened else 3, min(6, available // 195)); size = min(225, int((available - (columns - 1) * 22) / columns))
            grid = QGridLayout(); grid.setHorizontalSpacing(22); grid.setVerticalSpacing(22)
            for index, songs in enumerate(albums.values()):
                title = songs[0].album
                card = AlbumCard(title, self.album_caption(songs[0]), songs[0].cover, size)
                self.bind_album_menu(card, songs); card.clicked.connect(lambda songs=songs: self.open_album(songs)); grid.addWidget(card, index // columns, index % columns, Qt.AlignmentFlag.AlignTop)
            grid.setColumnStretch(columns, 1); layout.addLayout(grid); layout.addStretch()
        previous = self.library_scroll.takeWidget()
        if previous: previous.deleteLater()
        self.library_scroll.setWidget(widget)
        if self.current_page == "artists" and tracks:
            settle_layout(self.library_scroll); browser.restore_scroll()

    def render_home(self):
        page, layout = self.page_layout(); layout.setSpacing(16)
        heading = QHBoxLayout(); heading.addWidget(label("主页", 24, True)); heading.addStretch()
        add = button("添加音乐", "plus", compact=True); add.setProperty("accent", True); add.setIcon(icon("plus", RED, 16)); add.clicked.connect(self.add_dialog); heading.addWidget(add); layout.addLayout(heading)
        tracks = self.filtered_tracks()
        albums = {}
        for track in tracks: albums.setdefault(track.album_key, []).append(track)
        available = max(720, self.library_scroll.viewport().width() - 84)
        if albums:
            width = max(184, min(240, int((available - 64) / 5)))
            cards = []
            for songs in list(albums.values())[:12]:
                card = FeatureCard(songs[0].album, self.album_caption(songs[0]), songs[0].cover, width)
                self.bind_album_menu(card, songs); card.clicked.connect(lambda songs=songs: self.open_album(songs)); cards.append(card)
            self.add_rail(layout, "为你精选", cards)
            layout.addSpacing(22)
            by_path = {track.path: track for track in tracks}
            history = [by_path[path] for path in self.recently_played if path in by_path]
            recent = history or tracks
            seen, cards = set(), []
            size = max(155, min(210, int((available - 80) / 6)))
            for track in recent:
                key = track.album_key
                if key in seen: continue
                seen.add(key); songs = albums.get(key, [track])
                card = AlbumCard(track.album, self.album_caption(track), track.cover, size)
                self.bind_album_menu(card, songs); card.clicked.connect(lambda songs=songs: self.open_album(songs)); cards.append(card)
                if len(cards) == 14: break
            self.add_rail(layout, "最近播放" if history else "最近添加", cards)
            layout.addSpacing(8)
            title = label("你的音乐资料库", 15, True); layout.addWidget(title)
            layout.addWidget(label(f"{len(tracks)} 首歌曲  ·  {len(albums)} 张专辑", 10, color="#a5a5ad"))
        else:
            layout.addSpacing(70)
            empty = label("把喜欢的音乐，留在这里。", 23, True); empty.setAlignment(Qt.AlignmentFlag.AlignCenter); layout.addWidget(empty)
            hint = label("添加 Apple Music 链接，或在设置中选择音乐文件夹。", 11, color="#a5a5af"); hint.setAlignment(Qt.AlignmentFlag.AlignCenter); layout.addWidget(hint)
        layout.addStretch()
        previous = self.library_scroll.takeWidget()
        if previous: previous.deleteLater()
        self.library_scroll.setWidget(page)

    def add_rail(self, layout, title, cards):
        rail = AlbumRail(); rail.setWidgetResizable(False); rail.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); rail.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget(); row = QHBoxLayout(body); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(16)
        for card in cards: row.addWidget(card, 0, Qt.AlignmentFlag.AlignTop)
        body.setFixedSize(sum(card.width() for card in cards) + max(0, len(cards) - 1) * 16, max(card.sizeHint().height() if not card.minimumHeight() else card.height() for card in cards) + 4)
        rail.setWidget(body); rail.setFixedHeight(body.height() + 2)
        heading = QHBoxLayout(); heading.addWidget(label(title, 12, True)); heading.addStretch()
        for symbol, direction in (("back", -1), ("forward", 1)):
            arrow = button("", symbol, compact=True); arrow.setProperty("plain", True); arrow.setFixedSize(26, 25); arrow.setToolTip("向左滚动" if direction < 0 else "向右滚动")
            arrow.clicked.connect(lambda _, amount=direction: rail.scroll_page(amount)); heading.addWidget(arrow)
        layout.addLayout(heading); layout.addWidget(rail)

    def set_backdrop(self, source):
        for panel in (self.sidebar, self.player_bar, self.now_playing, self.content_surface, self.playback_queue): panel.set_source(source)

    def hero(self, tracks):
        track = tracks[0]
        frame = BlurPanel(base="#303034", tint=.23, radius=10); frame.setObjectName("hero"); frame.set_source(track.cover); self.bind_album_menu(frame, tracks)
        row = QHBoxLayout(frame); row.setContentsMargins(24, 24, 26, 24); row.setSpacing(26)
        row.addWidget(Cover(track.cover, 166, 10))
        text = QVBoxLayout(); text.setSpacing(8); text.addWidget(label("专辑", 10, True, "#b0b0b8")); text.addSpacing(4)
        name = label(track.album, 24, True); name.setWordWrap(True); text.addWidget(name)
        text.addWidget(label(track.album_artist or track.artist, 13, color=RED)); text.addWidget(label(" · ".join(value for value in (track.edition, str(track.year) if track.year else "", track.quality) if value), 10, color="#b8b8c1")); text.addStretch()
        controls = QHBoxLayout(); play = button("播放", "play", True); play.setFixedWidth(115); play.clicked.connect(lambda: self.play_tracks(tracks)); controls.addWidget(play)
        controls.addStretch(); text.addLayout(controls); row.addLayout(text, 1)
        return frame

    def track_table(self, tracks, playlist_key=None):
        table = self.table(["", "标题", "艺人", "专辑", "音质", "时长"], TrackTable)
        table.track_paths = [track.path for track in tracks]
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setRowCount(len(tracks)); table.setColumnWidth(0, 48); table.setColumnWidth(2, 135); table.setColumnWidth(3, 170); table.setColumnWidth(4, 160); table.setColumnWidth(5, 63); table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        if self.body.opened:
            scale = min(1, max(.45, (self.stack.width() - 310) / 465))
            table.setColumnWidth(0, 36)
            for column, width in ((2, 135), (3, 170), (4, 160)): table.setColumnWidth(column, round(width * scale))
        for row, track in enumerate(tracks):
            values = ["" if track.path in self.favourites else str(row + 1), track.title, track.artist, track.album, track.quality, duration_text(track.duration)]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text); item.setToolTip(text); table.setItem(row, col, item)
            if track.path in self.favourites:
                table.item(row, 0).setIcon(icon("star_fill", RED)); table.item(row, 0).setToolTip("喜爱的歌曲")
        table.cellDoubleClicked.connect(lambda row, _: self.custom_playlists.play(playlist_key, row) if playlist_key else self.play_tracks(tracks, row))
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(lambda point: self.custom_playlists.song_menu(playlist_key, table, point) if playlist_key else self.track_menu(table, tracks, point))
        return table

    def track_menu(self, table, tracks, point):
        row = table.rowAt(point.y())
        if row < 0: return
        track = tracks[row]; menu = QMenu(self)
        if row not in table.selected_rows(): table.selectRow(row)
        menu.addAction("播放", lambda: self.play_tracks(tracks, row))
        self.playback_queue_menu(menu, [tracks[index] for index in table.selected_rows()])
        self.custom_playlists.add_menu(menu, [tracks[index] for index in table.selected_rows()])
        menu.addAction("取消喜爱" if track.path in self.favourites else "加入喜爱", lambda: self.toggle_favourite(track.path))
        menu.addAction("打开所在文件夹", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(track.file_path).parent))))
        menu.addSeparator(); menu.setToolTipsVisible(True)
        def remove(delete_file=False):
            if not self.remove_track(track, delete_file): return
            tracks.pop(row); table.removeRow(row); table.track_paths = [item.path for item in tracks]
            for index, item in enumerate(tracks):
                table.item(index, 0).setText("" if item.path in self.favourites else str(index + 1))
            if not tracks and isinstance(table.window(), QDialog): table.window().close()
        action = menu.addAction("从列表中删除", lambda: remove())
        action.setToolTip("从资料库隐藏，保留本地音频；重新导入可恢复。")
        action = menu.addAction("删除本地文件", lambda: remove(True))
        action.setEnabled(not track.container)
        action.setToolTip("整轨 / 镜像内曲目请从列表中删除，原文件包含其他歌曲。" if track.container else "将这首音频移入回收站，保留旁边的歌词和封面。")
        menu.exec(table.viewport().mapToGlobal(point))

    def remove_track(self, track, delete_file=False):
        if delete_file and track.container:
            self.toast("这首曲目属于整轨或镜像，请使用从列表中删除。"); return False
        key = path_key(track.path)
        current = bool(self.current_path) and path_key(self.current_path) == key
        if delete_file:
            position, state = self.media.position(), self.media.playbackState()
            source = self.media.source()
            if current: self.media.shutdown(); self.media.setSource(QUrl())
            try: trash_audio(track.path)
            except (OSError, ValueError) as error:
                if current:
                    self.playback_restore = (source, position, state)
                    self.media.setSource(source)
                self.toast("删除失败：" + str(error)); return False
            self.removed_files.discard(key)
        else: self.removed_files.add(key)
        self.favourites = {path for path in self.favourites if path_key(path) != key}
        self.recently_played = [path for path in self.recently_played if path_key(path) != key]
        imported = [path for path in self.store.get("imported_files", []) if path_key(path) != key]
        last = self.store.get("last_track", "")
        if last and path_key(last) == key: last = ""
        if self.restore_path and path_key(self.restore_path) == key: self.restore_path = ""
        self.store.update({"removed_files": sorted(self.removed_files), "favourites": sorted(self.favourites),
                           "recently_played": self.recently_played, "imported_files": imported, "last_track": last})
        if current: self.clear_player()
        else:
            self.playlist = [item for item in self.playlist if path_key(item.path) != key]
            self.play_index = next((index for index, item in enumerate(self.playlist) if item.path == self.current_path), -1)
        self.persist_playback_queue(); self.playback_queue.refresh()
        self.scan(); self.toast("音频已移入回收站" if delete_file else "已从列表中删除，本地音频已保留")
        return True

    def clear_player(self):
        self.cancel_track_gap()
        self.play_request += 1
        if hasattr(self, "prepare_cancel"): self.prepare_cancel.set()
        self.preparing = False
        self.playback_restore = None
        self.current_path, self.playlist, self.play_index = "", [], -1
        self.media.stop(); self.media.setSource(QUrl()); self.lyrics.set_track("")
        self.play_cover.set_source(""); self.play_title.setText(APP_NAME); self.play_title.setToolTip("")
        self.play_artist.setText("选择一首音乐开始播放"); self.quality.setText("")
        self.quality_button.setToolTip(""); self.quality_button.setEnabled(False); self.quality_button.hide()
        self.more_button.setEnabled(False); self.update_like_icon(); self.set_backdrop("")
        self.seek.setRange(0, 0); self.elapsed.setText("0:00"); self.remaining.setText("-0:00")
        self.persist_playback_queue(); self.playback_queue.refresh()

    def bind_album_menu(self, widget, tracks):
        widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        widget.customContextMenuRequested.connect(lambda point: self.album_menu(widget, tracks, point))

    def album_menu(self, widget, tracks, point):
        menu = QMenu(self)
        menu.addAction("播放专辑", lambda: self.play_tracks(tracks))
        self.playback_queue_menu(menu, sorted(tracks, key=lambda track: track.order))
        self.custom_playlists.add_menu(menu, sorted(tracks, key=lambda track: track.order))
        menu.addAction("编辑标签与封面", lambda: AlbumEditor(self, tracks).open())
        menu.addAction("打开所在文件夹", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(tracks[0].file_path).parent))))
        menu.exec(widget.mapToGlobal(point))

    def open_album(self, tracks):
        if not tracks: return
        key = album_page_key(tracks[0])
        self.album_pages[key] = sorted(tracks, key=lambda track: track.order)
        self.navigate(key)

    def play_tracks(self, tracks, index=0):
        if not tracks: return
        selected = tracks[index]
        remaining = [track for track in tracks if path_key(track.path) not in self.removed_files]
        if not remaining: return
        self.playlist = list({track.path: track for track in remaining}.values())
        self.shuffle_order.reset()
        self.play_index = self.playlist.index(selected) if selected in self.playlist else 0; self.play_current()

    def play_current(self, autoplay=True):
        self.cancel_track_gap()
        self.play_request += 1
        request = self.play_request
        if hasattr(self, "prepare_cancel"): self.prepare_cancel.set()
        self.prepare_cancel = threading.Event()
        self.preparing = False
        self.playback_restore = None
        track = self.playlist[self.play_index]; self.current_path = track.path
        self.play_cover.set_source(track.cover)
        self.play_title.setText(track.title); self.play_title.setToolTip(track.title + " · " + track.quality)
        self.play_artist.setText(track.artist + " — " + track.album); self.quality.setText(track.quality)
        self.quality_button.setToolTip(track.playback_details); self.quality_button.setEnabled(True); self.quality_button.setVisible(track.is_lossless); self.more_button.setEnabled(True); self.set_backdrop(track.cover)
        self.store.set("last_track", track.path)
        if autoplay:
            self.recently_played = [track.path] + [path for path in self.recently_played if path != track.path][:49]; self.store.set("recently_played", self.recently_played)
        self.update_like_icon()
        self.lyrics.set_track(track.path if not track.container else "", track.cover); self.lyrics.set_position(0)
        if track.container:
            self.media.stop(); self.media.setSource(QUrl())
            self.preparing = True; self.prepare_autoplay = autoplay
            self.play_artist.setText("正在准备曲目… " + track.artist)
            cache = self.store.directory / "audio-cache"
            cancel = self.prepare_cancel
            work = Work(lambda: prepare_track(track, cache, code_root(self.root) / "deps/ffmpeg.exe", cancel))
            def ready(path):
                if request != self.play_request or self.closing: return
                self.preparing = False
                self.play_artist.setText(track.artist + " — " + track.album)
                self.media.setSource(QUrl.fromLocalFile(path))
                if self.prepare_autoplay: self.media.play()
            def failed(message):
                if request != self.play_request or self.closing: return
                self.preparing = False; self.play_artist.setText(track.artist + " — " + track.album)
                self.toast(message)
            work.signals.done.connect(ready); work.signals.failed.connect(failed)
            self.workers.append(work); QThreadPool.globalInstance().start(work)
        else:
            self.media.setSource(QUrl.fromLocalFile(track.path))
            if autoplay: self.media.play()
        self.persist_playback_queue(); self.playback_queue.refresh()
        self.update_output_details()
        if hasattr(self, "tray"): self.tray.refresh()

    def toggle_play(self):
        if self.closing: return
        if self.gap_waiting:
            if self.gap_timer.isActive(): self.gap_timer.stop()
            else: self.gap_timer.start()
            self.playback_changed(self.media.playbackState()); return
        if self.preparing:
            self.prepare_autoplay = not self.prepare_autoplay
            self.playback_changed(self.media.playbackState()); return
        if self.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState: self.media.pause()
        elif self.current_path: self.media.play()
        elif self.tracks: self.play_tracks(self.filtered_tracks())

    def skip(self, step):
        if not self.playlist or self.closing: return
        if self.shuffle.isChecked():
            path = self.shuffle_order.step([track.path for track in self.playlist], self.current_path, step)
            self.play_index = next(index for index, track in enumerate(self.playlist) if track.path == path)
        else: self.play_index = (self.play_index + step) % len(self.playlist)
        self.play_current()

    def media_status(self, state):
        if self.playback_restore and state in {QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.InvalidMedia}:
            (source, position, playback), self.playback_restore = self.playback_restore, None
            if state == QMediaPlayer.MediaStatus.LoadedMedia and self.media.source() == source:
                self.media.setPosition(position)
                if playback == QMediaPlayer.PlaybackState.PlayingState: self.media.play()
                elif playback == QMediaPlayer.PlaybackState.PausedState: self.media.pause()
                self.position_changed(position)
        if state == QMediaPlayer.MediaStatus.EndOfMedia:
            if self.has_next_track() and not self.gap_waiting and not self.closing:
                self.gap_waiting = True; self.gap_timer.start()
                self.playback_changed(self.media.playbackState())
        elif state == QMediaPlayer.MediaStatus.InvalidMedia: self.cancel_track_gap()

    def playback_changed(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState or self.gap_timer.isActive() or (self.preparing and self.prepare_autoplay)
        self.play_button.setIcon(icon("player_pause" if playing else "player_play", "#dedee0"))
        self.play_button.setToolTip("暂停（正在等待下一首）" if self.gap_timer.isActive() else "继续播放下一首" if self.gap_waiting else "播放 / 暂停")
        if hasattr(self, "tray"): self.tray.refresh()

    def has_next_track(self):
        return bool(self.playlist and self.current_path) and (self.play_index + 1 < len(self.playlist) or self.shuffle.isChecked() or self.repeat.isChecked())

    def cancel_track_gap(self):
        self.gap_timer.stop(); self.gap_waiting = False
        if hasattr(self, "play_button"): self.playback_changed(self.media.playbackState())

    def finish_track_gap(self):
        waiting = self.gap_waiting; self.gap_waiting = False
        if waiting and not self.closing and self.has_next_track(): self.skip(1)
        else: self.playback_changed(self.media.playbackState())

    def seek_to(self, position):
        resume = self.gap_timer.isActive(); self.cancel_track_gap()
        self.media.setPosition(position)
        if resume: self.media.play()

    def shuffle_changed(self, *_):
        self.shuffle_order.reset()
        if hasattr(self, "playback_queue"): self.playback_queue.refresh()

    def persist_playback_queue(self):
        self.store.set("playback_queue", [track.path for track in self.playlist])

    def playback_queue_menu(self, menu, tracks):
        menu.addAction("下一首播放", lambda: self.add_to_playback_queue(tracks, next_up=True))
        menu.addAction("最后播放", lambda: self.add_to_playback_queue(tracks))

    def add_to_playback_queue(self, tracks, next_up=False, row=None):
        values = list({path_key(track.path): track for track in tracks if path_key(track.path) not in self.removed_files and track.path != self.current_path}.values())
        if not values: return
        destination = row if row is not None else self.play_index + 1 if next_up else len(self.playlist)
        keys = {path_key(track.path) for track in values}
        destination -= sum(i < destination and path_key(track.path) in keys for i, track in enumerate(self.playlist))
        self.playlist = [track for track in self.playlist if path_key(track.path) not in keys]
        destination = max(0, min(destination, len(self.playlist)))
        self.playlist[destination:destination] = values
        self.play_index = next((i for i, track in enumerate(self.playlist) if track.path == self.current_path), 0)
        self.shuffle.setChecked(False)
        if not self.current_path: self.play_current(autoplay=False)
        self.persist_playback_queue(); self.playback_queue.refresh()
        self.toast(f"已添加 {len(values)} 首到播放队列")

    def play_queue_row(self, row):
        if 0 <= row < len(self.playlist): self.play_index = row; self.shuffle_order.reset(); self.play_current()

    def remove_from_playback_queue(self, rows):
        current_removed = self.play_index in rows
        playing = self.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState or self.gap_timer.isActive() or (self.preparing and self.prepare_autoplay)
        index = self.play_index - sum(row < self.play_index for row in set(rows))
        self.playlist = [track for i, track in enumerate(self.playlist) if i not in rows]
        if not self.playlist: self.clear_playback_queue(); return
        self.play_index = min(max(0, index), len(self.playlist) - 1)
        if current_removed and self.shuffle.isChecked():
            path = self.shuffle_order.step([track.path for track in self.playlist], self.current_path)
            self.play_index = next(i for i, track in enumerate(self.playlist) if track.path == path)
        if current_removed: self.play_current(autoplay=playing)
        self.persist_playback_queue(); self.playback_queue.refresh()

    def clear_playback_queue(self):
        self.restore_path = ""; self.restore_queue = None; self.store.set("last_track", "")
        self.clear_player(); self.shuffle_order.reset()

    def duration_changed(self, value):
        self.seek.setRange(0, value); self.remaining.setText("-" + duration_text(max(0, value - self.media.position()) / 1000))

    def position_changed(self, value):
        # Coalesce progress repaints while the 300 ms sidebar frame is on the GPU.
        if self.body.transition.clock.isValid(): return
        if not self.seek.isSliderDown(): self.seek.setValue(value)
        self.elapsed.setText(duration_text(value / 1000))
        self.remaining.setText("-" + duration_text(max(0, self.media.duration() - value) / 1000))
        self.lyrics.set_position(value)

    def set_volume(self, value):
        self.audio.setVolume(value / 100); self.store.set("volume", value)
        self.update_volume_icons(value)

    def update_output_details(self, *_):
        direct = self.media.direct
        self.volume.setEnabled(not direct)
        self.volume_button.setToolTip("直通输出 · 请用 DAC 调节音量" if direct else f"音量 {self.volume.value()}%")
        if direct: self.volume_popup.hide()
        track = next((track for track in self.playlist if track.path == self.current_path), None)
        self.quality_button.setToolTip((track.quality + "\n" if track else "") + self.media.output_description)
        if self.output_dialog: self.output_dialog.refresh()

    def show_output_chain(self):
        if self.output_dialog is None: self.output_dialog = OutputChainDialog(self)
        self.output_dialog.refresh(); self.output_dialog.show(); self.output_dialog.raise_(); self.output_dialog.activateWindow()

    def update_volume_icons(self, value):
        symbol = "player_volume" if value == 0 else "player_volume_low" if value <= 33 else "player_volume_medium" if value <= 66 else "player_volume_high"
        self.volume_button.setIcon(icon(symbol, "#c6c6cd")); self.volume_button.setToolTip(f"音量 {value}%")
        self.volume_level_icon.symbol = icon(symbol, "#dedee0"); self.volume_level_icon.update()

    def toggle_favourite(self, path):
        if path in self.favourites: self.favourites.remove(path)
        else: self.favourites.add(path)
        self.store.set("favourites", sorted(self.favourites)); self.update_like_icon(); self.render_library()

    def toggle_current_favourite(self):
        if self.current_path: self.toggle_favourite(self.current_path)

    def update_like_icon(self):
        favourite = self.current_path in self.favourites
        self.like_button.setIcon(icon("player_star", RED if favourite else "#a5a5a9"))
        self.like_button.setToolTip("取消喜爱" if favourite else "加入喜爱")

    def seek_lyrics(self, position):
        if not self.media.isSeekable(): return
        self.seek_to(min(position, self.media.duration()))
        self.position_changed(self.media.position())
        self.lyrics.set_position(self.media.position(), force=True)

    def show_lyrics(self):
        self.show_playback_panel(self.lyrics)

    def show_now_playing(self):
        self.playback_queue.refresh(); self.show_playback_panel(self.playback_queue)

    def show_playback_panel(self, panel):
        self.resize_timer.stop()
        opened = not (self.body.opened and self.panels.currentWidget() is panel)
        lyrics_open = opened and panel is self.lyrics
        queue_open = opened and panel is self.playback_queue
        self.lyric_button.setChecked(lyrics_open); self.now_queue_button.setChecked(queue_open)
        self.lyric_button.setIcon(icon("player_lyrics", "#ffffff" if lyrics_open else "#c6c6cd"))
        self.now_queue_button.setIcon(icon("player_queue", "#ffffff" if queue_open else "#c6c6cd"))
        self.lyric_button.setToolTip("隐藏歌词" if lyrics_open else "显示歌词")
        self.now_queue_button.setToolTip("隐藏正在播放队列" if queue_open else "显示正在播放队列")
        def refresh():
            self.panels.setCurrentWidget(panel); self.refresh_content()
        self.body.set_open(opened, refresh)

    def refresh_content(self):
        scroll = self.search_scroll if self.current_page == "search" else self.library_scroll
        position = scroll.verticalScrollBar().value()
        rail_positions = []
        for rail in scroll.findChildren(AlbumRail):
            rail.transition.clear()
            step = rail.widget().layout().itemAt(0).widget().width() + 16
            rail_positions.append(rail.horizontalScrollBar().value() / step)
        if self.current_page == "search": self.render_search(self.search_results, self.search_message, animate=False)
        else: self.render_library()
        settle_layout(scroll)
        scroll.verticalScrollBar().setValue(position)
        for rail, position in zip(scroll.findChildren(AlbumRail), rail_positions):
            step = rail.widget().layout().itemAt(0).widget().width() + 16
            rail.horizontalScrollBar().setValue(round(position * step))
        if self.body.opened: self.lyrics.set_position(self.media.position(), follow=True)
        self.stack.finish_resize()

    def add_dialog(self, urls=None):
        dialog = QDialog(self); dialog.setWindowTitle("添加音乐"); dialog.resize(700, 390)
        layout = QVBoxLayout(dialog); layout.setContentsMargins(26, 24, 26, 24); layout.setSpacing(15)
        layout.addWidget(label("把喜欢的音乐加入资料库", 20, True))
        layout.addWidget(label("粘贴 Apple Music 链接，或导入本地音频。", 11, color="#94949e"))
        text = QTextEdit(); text.setPlaceholderText("https://music.apple.com/…"); text.setMaximumHeight(135)
        if urls: text.setPlainText("\n".join(urls))
        else:
            clipboard = QApplication.clipboard().text().strip()
            if clipboard.startswith("https://music.apple.com/"): text.setPlainText(clipboard)
        layout.addWidget(text)
        choices = QHBoxLayout(); choices.addWidget(label("下载音质", 11)); combo = QComboBox()
        for key, name in CODECS.items(): combo.addItem(name, key)
        combo.setCurrentIndex(max(0, combo.findData(self.store.get("codec", "alac")))); choices.addWidget(combo, 1); layout.addLayout(choices)
        message = label("", 10, color=RED); message.setWordWrap(True); layout.addWidget(message)
        buttons = QHBoxLayout()
        local = button("导入本地音频", "folder"); local.setToolTip("保留文件原位置 · 支持多选 · Ctrl+O")
        local.clicked.connect(lambda: self.choose_audio_files(dialog)); buttons.addWidget(local)
        folder = button("导入文件夹", "folder"); folder.setToolTip("包含子文件夹 · 保留文件原位置 · 自动去重")
        folder.clicked.connect(lambda: self.choose_audio_folder(dialog)); buttons.addWidget(folder)
        buttons.addStretch(); cancel = button("取消"); cancel.clicked.connect(dialog.reject); buttons.addWidget(cancel)
        add = button("加入下载队列", "download", True); buttons.addWidget(add); layout.addLayout(buttons)
        def submit():
            try: links = validate_links(text.toPlainText())
            except ValueError as error: message.setText(str(error)); return
            if not valid_backend(self.root): message.setText("请先在设置中选择原下载器安装目录。"); return
            self.enqueue(links, combo.currentData()); dialog.accept()
        add.clicked.connect(submit); dialog.exec()

    def choose_audio_files(self, dialog=None):
        if self.importing: self.toast("正在导入音频，请稍候…"); return
        patterns = " ".join("*" + suffix for suffix in sorted(IMPORT_EXTENSIONS))
        paths, _ = QFileDialog.getOpenFileNames(dialog if isinstance(dialog, QDialog) else self, "导入本地音频（保留文件原位置）", str(self.library_folder()), f"音频文件 ({patterns});;所有文件 (*)")
        if paths:
            if isinstance(dialog, QDialog): dialog.accept()
            self.import_audio_files(paths)

    def choose_audio_folder(self, dialog=None):
        if self.importing: self.toast("正在导入音频，请稍候…"); return
        folder = QFileDialog.getExistingDirectory(dialog if isinstance(dialog, QDialog) else self, "导入音乐文件夹（包含子文件夹）", str(self.library_folder()))
        if folder:
            if isinstance(dialog, QDialog): dialog.accept()
            self.import_audio_files([], folder=folder)

    def import_audio_files(self, paths, folder=None):
        if self.importing: self.toast("正在导入音频，请稍候…"); return
        paths = list({path_key(path): str(Path(path).resolve()) for path in paths}.values())
        if not paths and not folder: return
        folder = str(Path(folder).resolve()) if folder else None
        self.importing = True; self.notice.setText("正在扫描文件夹及子文件夹…" if folder else "正在读取本地音频…")
        cache = self.store.directory / "covers"
        work = Work(lambda: scan_library(folder, cache, paths))
        work.signals.done.connect(lambda result: self.import_finished(result, len({track.file_path for track in result[0]}) + len(result[1]) if folder else len(paths)))
        work.signals.failed.connect(self.import_failed)
        self.workers.append(work); QThreadPool.globalInstance().start(work)

    def import_finished(self, result, selected):
        self.importing = False
        tracks, errors = result
        if not selected: self.toast("未找到支持的音频文件"); return
        for error in errors: self.log(error)
        imported = list(self.store.get("imported_files", []))
        known = {path_key(path) for path in imported} | {path_key(track.path) for track in self.tracks}
        known -= self.removed_files
        added = [track.path for track in tracks if path_key(track.path) not in known]
        skipped, duplicate = max(len(errors), selected - len({track.file_path for track in tracks})), len(tracks) - len(added)
        summary = f"已导入 {len(added)} 首本地音频"
        if duplicate: summary += f"，{duplicate} 首已在资料库"
        if skipped: summary += f"，跳过 {skipped} 个无法读取或不支持的文件"
        if not added: self.toast(summary); return
        self.removed_files.difference_update(path_key(track.path) for track in tracks)
        self.store.update({"imported_files": list(dict.fromkeys(imported + [track.file_path for track in tracks if track.path in added])), "removed_files": sorted(self.removed_files)})
        self.import_notice = summary
        self.search.clear(); self.navigate("songs"); self.scan()

    def import_failed(self, message):
        self.importing = False; self.toast("导入失败：" + message)

    def enqueue(self, links, codec):
        for url in links:
            if any(job["url"] == url and job["codec"] == codec and job["state"] not in {"DONE", "FAILED", "cancelled"} for job in self.jobs): continue
            self.jobs.append({"id": uuid.uuid4().hex, "url": url, "codec": codec, "state": "queued", "title": url, "artist": "", "created": time.time(), "completed": 0, "total": 0})
        self.queue_paused = False; self.persist_jobs(); self.navigate("queue"); self.refresh_queue(); self.next_job()

    def persist_jobs(self):
        self.store.set("jobs", self.jobs)

    def next_job(self):
        if self.active_job or self.queue_paused or self.closing: return
        if self.client.stopping and self.client.process.state() != self.client.process.ProcessState.NotRunning: return
        job = next((item for item in self.jobs if item["state"] == "queued"), None)
        if job is None: return
        job.pop("actual_codec", None); job.pop("quality", None)
        self.active_job = job["id"]; job["state"] = "starting"; self.refresh_queue(); self.persist_jobs()
        self.client.send({"action": "download", "id": job["id"], "url": job["url"], "codec": job["codec"], "output_dir": str(self.library_folder())})

    def refresh_queue(self):
        if not hasattr(self, "queue_table"): return
        self.queue_table.setRowCount(len(self.jobs))
        for row, job in enumerate(self.jobs):
            title = job.get("title") or job["url"]
            if job.get("artist"): title += "  ·  " + job["artist"]
            total = job.get("total", 0); progress = f"{job.get('completed', 0)} / {total}" if total else "—"
            values = [title, job.get("quality") or CODECS.get(job["codec"], job["codec"]), STAGES.get(job["state"], job["state"]), progress]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value); item.setToolTip(job.get("error") or job["url"]); self.queue_table.setItem(row, column, item)
            self.queue_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, job["id"])
            action = button("重试" if job["state"] in {"FAILED", "cancelled"} else "取消", compact=True)
            action.setEnabled(job["state"] != "DONE")
            action.clicked.connect(lambda _, identifier=job["id"]: self.job_action(identifier))
            action.setFixedHeight(36)
            cell = QWidget(); cell_layout = QHBoxLayout(cell); cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.addWidget(action, 0, Qt.AlignmentFlag.AlignVCenter)
            self.queue_table.setCellWidget(row, 4, cell)
        done = sum(job["state"] == "DONE" for job in self.jobs)
        self.queue_summary.setText(f"{len(self.jobs)} 个任务 · {done} 个已完成" + (" · 队列已暂停，当前任务会继续完成" if self.queue_paused else ""))
        self.resume_button.setText("继续队列" if self.queue_paused else "暂停队列")
        self.resume_button.setIcon(icon("play" if self.queue_paused else "pause", "#c6c6cd", 18))
        self.nav["queue"].setText("  下载队列" + (f"   {len(self.jobs) - done}" if len(self.jobs) - done else ""))

    def queue_menu(self, point):
        row = self.queue_table.rowAt(point.y())
        if row < 0: return
        identifier = self.queue_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        self.queue_table.selectRow(row)
        menu = QMenu(self); menu.setToolTipsVisible(True)
        action = menu.addAction("从队列删除", lambda: self.remove_job(identifier))
        action.setToolTip("移除任务记录；正在下载的任务会取消，已下载的本地文件保留。")
        menu.exec(self.queue_table.viewport().mapToGlobal(point))

    def remove_job(self, identifier):
        job = next((item for item in self.jobs if item["id"] == identifier), None)
        if not job: return
        self.jobs.remove(job); self.refresh_queue(); self.persist_jobs()
        if self.active_job == identifier:
            self.dismiss_format_dialog(); self.client.send({"action": "cancel"})

    def job_action(self, identifier):
        job = next((item for item in self.jobs if item["id"] == identifier), None)
        if not job: return
        if job["state"] in {"FAILED", "cancelled"}:
            job.update(state="queued", error=""); self.queue_paused = False; self.next_job()
        elif self.active_job == identifier:
            self.dismiss_format_dialog(); self.client.send({"action": "cancel"})
        else: job["state"] = "cancelled"
        self.refresh_queue(); self.persist_jobs()

    def toggle_queue(self):
        self.queue_paused = not self.queue_paused; self.refresh_queue(); self.next_job()

    def retry_failed(self):
        for job in self.jobs:
            if job["state"] in {"FAILED", "cancelled"}: job.update(state="queued", error="")
        self.queue_paused = False; self.refresh_queue(); self.persist_jobs(); self.next_job()

    def clear_completed(self):
        self.jobs = [job for job in self.jobs if job["state"] != "DONE"]; self.refresh_queue(); self.persist_jobs()

    def dismiss_format_dialog(self):
        dialog, self.format_dialog = self.format_dialog, None
        if dialog:
            dialog.finished.disconnect(); dialog.reject(); dialog.deleteLater()

    def confirm_download_format(self, event):
        if self.closing or event.get("job_id") != self.active_job: return
        if self.format_dialog and self.format_dialog.property("request_id") == event["request_id"]: return
        self.dismiss_format_dialog()
        dialog = QDialog(self); self.format_dialog = dialog
        dialog.setWindowTitle("下载格式不可用"); dialog.setFixedWidth(560)
        dialog.setProperty("request_id", event["request_id"])
        layout = QVBoxLayout(dialog); layout.setContentsMargins(28, 24, 28, 24); layout.setSpacing(16)
        heading = label("是否下载最高规格可用格式？", 18, True); layout.addWidget(heading)
        text = label(f"《{event.get('title', '')}》{(' · ' + event['artist']) if event.get('artist') else ''}\n"
                     f"没有符合当前设置的 {event['requested']}。\n\n"
                     f"可用格式：{event['quality']}\n\n"
                     "确定后继续当前任务；取消则取消当前下载任务，已下载的歌曲保留。")
        text.setTextFormat(Qt.TextFormat.PlainText); text.setWordWrap(True)
        text.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop); layout.addWidget(text)
        actions = QHBoxLayout(); actions.addStretch()
        cancel = button("取消下载"); cancel.setObjectName("cancelFormat")
        confirm = button("确定下载", primary=True); confirm.setObjectName("confirmFormat")
        actions.addWidget(cancel); actions.addWidget(confirm); layout.addLayout(actions)
        cancel.clicked.connect(dialog.reject); confirm.clicked.connect(dialog.accept)
        def answered(result):
            if self.format_dialog is not dialog: return
            self.format_dialog = None
            if not self.closing and event["job_id"] == self.active_job:
                self.client.send({"action": "format_response", "job_id": event["job_id"],
                                  "request_id": event["request_id"], "accepted": result == QDialog.DialogCode.Accepted})
            dialog.deleteLater()
        dialog.finished.connect(answered)
        dialog.ensurePolished(); text.setMinimumHeight(text.heightForWidth(dialog.width() - 56))
        dialog.adjustSize(); dialog.open()

    def backend_event(self, event):
        kind = event.get("event")
        job = next((item for item in self.jobs if item["id"] == event.get("job_id")), None)
        if kind == "backend":
            state = event["state"]; self.backend_dot.setText({"starting": "●  后端启动中", "ready": "●  后端已连接", "error": "●  连接失败"}.get(state, state))
            self.backend_dot.setStyleSheet(f"color:{'#449679' if state == 'ready' else '#92929c'};")
            self.backend_dot.setToolTip("")
            if state == "ready":
                regions = event.get("regions", [])
                self.set_account_status(regions); self.try_auto_login(regions)
                if is_managed(self.root) and not regions and not self.login_window:
                    self.toast("内置下载器已就绪，请在设置中登录 Apple 账号。")
            self.log(event.get("message", ""))
        elif kind in {"stage", "track"} and job:
            if event.get("stage") not in {None, "DONE", "FAILED"}: job["state"] = event["stage"]
            for key in ("title", "artist", "completed", "total", "error"):
                if event.get(key) not in (None, ""): job[key] = redact(event[key]) if key == "error" else event[key]
            self.refresh_queue()
        elif kind == "format_fallback" and job and event.get("job_id") == self.active_job:
            job["state"] = "awaiting_format"
            for key in ("title", "artist", "completed", "total"):
                if key in event: job[key] = event[key]
            self.persist_jobs(); self.refresh_queue(); self.confirm_download_format(event)
        elif kind == "format_selected" and job and event.get("job_id") == self.active_job:
            self.dismiss_format_dialog()
            job.update(actual_codec=event["codec"], quality=event["quality"], state="WAITING")
            self.persist_jobs(); self.refresh_queue()
        elif kind == "finished" and (job or (self.active_job and event.get("job_id") == self.active_job)):
            if event.get("job_id") == self.active_job: self.dismiss_format_dialog()
            if job:
                job["state"] = event["state"]
                for key in ("completed", "total", "error"):
                    if key in event: job[key] = redact(event[key]) if key == "error" else event[key]
            if event.get("job_id") == self.active_job: self.active_job = None
            self.persist_jobs(); self.refresh_queue()
            if job and job["state"] == "DONE": self.scan(); self.toast("下载完成，已更新资料库")
            elif event.get("error"): self.log(event["error"])
            QTimer.singleShot(350, self.next_job)
        elif kind == "log": self.log(event.get("text", ""))
        elif kind == "catalog" and event.get("serial") == self.search_serial:
            results = event.get("results", [])
            self.render_search(results, "搜索暂不可用：" + event["error"] if event.get("error") else ("没有找到匹配的歌曲" if not results else ""))
        elif kind == "speed": self.speeds.setText(f"下载 {event['download']}  ·  解密 {event['decrypt']}")
        elif kind in {"fatal", "error"}:
            self.log(event.get("message", "")); self.toast(event.get("message", "后端异常"))
            if kind == "fatal": self.fail_active(event.get("message", "后端启动失败"))
            if kind == "fatal" and self.login_window: self.login_window.backend_failed(event.get("message", "后端启动失败"))
            if kind == "fatal" and self.current_page == "search": self.render_search([], "搜索暂不可用：" + event.get("message", "后端启动失败"))
        elif kind == "disconnected":
            if self.login_window: self.login_window.backend_failed("后端连接已断开，请重新登录。")
            self.backend_dot.setText("●  后端待命")
            self.backend_dot.setToolTip("")
            if self.active_job: self.fail_active("后端连接已关闭；可以重新启动并重试。")
            if self.closing: self.close()
            elif self.restart_requested:
                self.restart_requested = False; self.client.send({"action": "start"})
            elif event.get("expected"): QTimer.singleShot(100, self.next_job)
        elif kind in {"twofa", "login"}:
            if not self.login_window or event.get("request_id") != self.login_window.request_id: return
            if kind == "login":
                self.toast("账号登录成功" if event.get("ok") else "登录失败：" + redact(event.get("error", "")))
                if event.get("ok"): self.set_account_status(event.get("regions", []))
            self.login_window.handle(event)
        elif kind == "exported": self.toast("诊断日志已保存"); QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(event["path"]).parent)))

    def fail_active(self, message):
        self.dismiss_format_dialog()
        job = next((item for item in self.jobs if item["id"] == self.active_job), None)
        if job: job.update(state="FAILED", error=message)
        self.active_job = None; self.queue_paused = True; self.persist_jobs(); self.refresh_queue()

    def log(self, text):
        if hasattr(self, "logs") and text: self.logs.appendPlainText(redact(text))

    def export_logs(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存诊断日志", str(self.store.directory / f"wrapper-{time.strftime('%Y%m%d-%H%M%S')}.txt"), "文本文件 (*.txt)")
        if path: self.client.send({"action": "export", "path": path})

    def search_changed(self):
        self.search_timer.stop()
        self.body.transition.clear()
        if self.current_page != "search":
            if self.stack.currentWidget() != self.library_scroll: return
            if self.current_page.startswith("playlist:") and self.search.text().strip():
                self.navigate("songs"); return
            before = self.stack.capture_page(); self.render_library(); self.stack.reveal_page(before)
            return
        query = self.search.text().strip()
        self.search_serial += 1; serial = self.search_serial
        if not query: self.render_search([]); return
        self.render_search([], "正在搜索…")
        self.client.send({"action": "search", "serial": serial, "term": query, "country": self.store.get("country", "CN")})

    def render_search(self, results, message="", animate=True):
        before = self.stack.capture_page() if animate and self.stack.currentWidget() == self.search_scroll else None
        self.search_results, self.search_message = results, message
        page, layout = self.page_layout(); layout.addWidget(label("搜索曲库", 28, True))
        layout.addWidget(label(message or (f"找到 {len(results)} 首歌曲" if results else "搜索歌名或艺人，也可以直接粘贴 Apple Music 链接添加音乐。"), 11, color="#909099"))
        grid = QGridLayout(); grid.setSpacing(22)
        available = max(340 if self.body.opened else 660, self.search_scroll.viewport().width() - 84); columns = max(2 if self.body.opened else 3, min(5, available // 195)); size = min(220, int((available - (columns - 1) * 22) / columns))
        self.search_cards = []
        for index, result in enumerate(results):
            card = AlbumCard(result.get("trackName", "未知歌曲"), result.get("artistName", ""), size=size)
            card.clicked.connect(lambda result=result: self.catalog_dialog(result)); grid.addWidget(card, index // columns, index % columns); self.search_cards.append(card)
            artwork = result.get("artworkUrl100", "").replace("100x100", "400x400")
            if artwork: self.load_artwork(artwork, card.cover)
        layout.addLayout(grid); layout.addStretch()
        previous = self.search_scroll.takeWidget()
        if previous: previous.deleteLater()
        self.search_scroll.setWidget(page)
        if before is not None:
            self.body.transition.clear(); self.stack.reveal_page(before)

    def load_artwork(self, url, cover):
        import weakref
        ref = weakref.ref(cover)
        if url in self.art_cache: cover.set_data(self.art_cache[url]); return
        request = QNetworkRequest(QUrl(url)); request.setTransferTimeout(15000)
        reply = self.network.get(request)
        def finish():
            if reply.error() == QNetworkReply.NetworkError.NoError:
                data = bytes(reply.readAll()); self.art_cache[url] = data
                item = ref()
                if item is not None:
                    try: item.set_data(data)
                    except RuntimeError: pass
            reply.deleteLater()
        reply.finished.connect(finish)

    def catalog_dialog(self, result):
        dialog = QDialog(self); dialog.setWindowTitle(result.get("trackName", "歌曲")); dialog.resize(570, 290)
        layout = QVBoxLayout(dialog); layout.setContentsMargins(26, 24, 26, 24)
        row = QHBoxLayout(); cover = Cover(size=135); row.addWidget(cover); text = QVBoxLayout()
        text.addWidget(label(result.get("trackName", ""), 19, True)); text.addWidget(label(result.get("artistName", ""), 12, color="#90909a")); album = label(result.get("collectionName", ""), 10, color="#aaaab2"); album.setWordWrap(True); text.addWidget(album); row.addLayout(text, 1); layout.addLayout(row)
        artwork = result.get("artworkUrl100", "").replace("100x100", "400x400")
        if artwork: self.load_artwork(artwork, cover)
        buttons = QHBoxLayout(); buttons.addStretch()
        url = result.get("trackViewUrl") or f"https://music.apple.com/{self.store.get('country', 'CN').lower()}/song/{result['trackId']}"
        open_page = button("Apple Music 页面"); open_page.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url))); buttons.addWidget(open_page)
        add = button("下载这首歌", "download", True)
        def download(): dialog.accept(); self.add_dialog([url])
        add.clicked.connect(download); buttons.addWidget(add); layout.addLayout(buttons); dialog.exec()

    def choose_root(self):
        if self.client.process.state() != self.client.process.ProcessState.NotRunning:
            self.toast("请先关闭并重新打开界面，再切换安装目录。"); return
        value = QFileDialog.getExistingDirectory(self, "选择包含 main.py 的安装目录", str(self.root))
        if not value: return
        value = str(Path(value))
        if not valid_backend(value): self.toast("所选文件夹不是有效的 AppleMusicDecrypt 安装目录。"); return
        self.root = Path(value); self.client.root = self.root; self.root_field.setText(value); self.store.set("backend", value)
        if not self.store.get("library"): self.library_field.setText(str(self.library_folder())); self.scan()
        self.toast("安装目录已更新")

    def choose_library(self):
        value = QFileDialog.getExistingDirectory(self, "选择音乐资料库", str(self.library_folder()))
        if value:
            value = str(Path(value)); self.store.set("library", value); self.library_field.setText(value); self.scan()

    def save_settings(self):
        if self.active_job: self.toast("请等待当前下载完成后再保存下载设置。"); return
        try:
            update_config(self.root, {("region", "language"): self.language_combo.currentData(), ("download", "maxSampleRate"): self.rate_combo.currentData(), ("download", "maxBitDepth"): self.bits_combo.currentData()})
            self.store.set("codec", self.default_codec.currentData())
            self.client.shutdown(); self.toast("设置已保存，下次启动下载后端时生效。")
        except Exception as error: self.toast("保存失败：" + str(error))

    def start_backend(self):
        if self.closing: return
        self.backend_dot.setText("●  后端启动中")
        self.client.send({"action": "start"})

    def restart_backend(self):
        if self.active_job: self.toast("请先完成或取消当前下载，再重新连接。"); return
        if self.client.process.state() != self.client.process.ProcessState.NotRunning:
            self.restart_requested = True; self.client.shutdown(); self.toast("正在重新连接下载后端…")
        else: self.start_backend()

    def login_dialog(self):
        if self.active_job: self.toast("请先完成当前下载再登录。"); return
        if self.login_window:
            self.login_window.raise_(); self.login_window.activateWindow(); return
        dialog = LoginDialog(self, self.accounts, self.client.send, is_managed(self.root))
        self.login_window = dialog
        def finished(*_):
            self.login_window = None; dialog.deleteLater()
        dialog.finished.connect(finished); dialog.open()

    def set_account_status(self, regions):
        self.backend_dot.setText("●  已登录 · " + ", ".join(regions) if regions else "●  未登录")
        self.backend_dot.setToolTip("账号地区：" + ", ".join(regions) if regions else "后端已就绪，尚未登录 Apple 账号。")
        self.backend_dot.setStyleSheet(f"color:{'#449679' if regions else '#92929c'};")

    def try_auto_login(self, regions):
        if not is_managed(self.root) or self.auto_login_attempted or regions or self.closing or self.active_job or self.login_window: return
        self.auto_login_attempted = True
        history = self.accounts.history()
        if not history or not history[0].get("automatic") or not history[0].get("secret"): return
        self.login_dialog()
        if self.login_window and self.login_window.password.text(): self.login_window.start_login()

    def toast(self, message):
        self.notice.setText(message[:55]); self.notice.setToolTip(message)
        if len(message) > 55: self.log(message)
        QTimer.singleShot(9000, lambda: self.notice.setText(f"{len(self.tracks)} 首歌曲") if not self.closing else None)

    def resizeEvent(self, event):
        if hasattr(self, "resize_timer") and self.isVisible() and not self.isMinimized():
            self.body.transition.clear(); self.stack.begin_resize()
        super().resizeEvent(event)
        if hasattr(self, "resize_timer"): self.resize_timer.start(80)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText() or event.mimeData().hasUrls(): event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if len(paths) == 1 and Path(paths[0]).suffix.lower() in {".m3u", ".m3u8"}:
            self.custom_playlists.import_file(paths[0]); event.setDropAction(Qt.DropAction.CopyAction); event.accept(); return
        if paths:
            self.import_audio_files(paths); event.setDropAction(Qt.DropAction.CopyAction); event.accept(); return
        try: links = validate_links(event.mimeData().text())
        except ValueError as error: self.toast(str(error)); return
        self.add_dialog(links); event.acceptProposedAction()

    def closeEvent(self, event):
        if not self.tray.exiting and not self.closing:
            event.ignore(); self.tray.request_close(); return
        if any(editor.saving for editor in self.findChildren(AlbumEditor)):
            self.toast("正在保存标签，请稍候再关闭。"); event.ignore(); return
        self.cancel_track_gap(); self.play_request += 1
        if hasattr(self, "prepare_cancel"): self.prepare_cancel.set()
        if self.login_window: self.login_window.reject()
        self.dismiss_format_dialog()
        self.volume_popup.hide()
        self.audio_settings.shutdown()
        self.media.shutdown()
        if self.client.process.state() != self.client.process.ProcessState.NotRunning:
            event.ignore()
            if not self.closing:
                self.closing = True; self.queue_paused = True; self.persist_jobs(); self.notice.setText("正在保存队列并关闭后端…"); self.client.shutdown()
                QTimer.singleShot(25000, self.force_close)
            return
        self.closing = True; self.tray.shutdown()
        if self.output_dialog: self.output_dialog.close()
        event.accept()
        if self.tray.exiting or not self.isVisible(): QTimer.singleShot(0, QApplication.instance().quit)

    def force_close(self):
        if self.closing and self.client.process.state() != self.client.process.ProcessState.NotRunning:
            self.client.process.kill(); self.client.process.waitForFinished(1500)
        self.close()
