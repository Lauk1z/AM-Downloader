"""Artist list and inline albums beneath the existing library heading."""
import random

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QBoxLayout, QFrame

from .core import duration_text
from .scrolling import SmoothScrollArea
from .widgets import AnimatedPageStack, Cover, PlayerLabel, RED, button, icon, label


class ArtistBrowser(QWidget):
    def __init__(self, owner, tracks, state):
        super().__init__()
        self.owner, self.state = owner, state
        self.artists = {}
        for track in tracks: self.artists.setdefault(track.artist, []).append(track)
        self.artist_buttons, self.album_rows, self.album_tables = {}, [], []
        self.setMinimumHeight(300)
        row = QHBoxLayout(self); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(0)
        self.artist_list = SmoothScrollArea(); self.artist_list.setWidgetResizable(True)
        self.artist_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        list_body = QWidget(); artists = QVBoxLayout(list_body); artists.setContentsMargins(0, 0, 10, 0); artists.setSpacing(3)
        for name, songs in sorted(self.artists.items(), key=lambda item: item[0].casefold()):
            item = button(); item.setProperty("nav", True); item.setCheckable(True); item.setFixedHeight(48)
            item.setToolTip(name); item.setAccessibleName(name)
            content = QHBoxLayout(item); content.setContentsMargins(12, 5, 8, 5); content.setSpacing(9)
            avatar = Cover(songs[0].cover, 34, 17); title = PlayerLabel(name)
            title.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            for child in (avatar, title): child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            content.addWidget(avatar); content.addWidget(title, 1)
            item.clicked.connect(lambda _, artist=name: self.select_artist(artist))
            artists.addWidget(item); self.artist_buttons[name] = item
        artists.addStretch(); self.artist_list.setWidget(list_body); row.addWidget(self.artist_list)
        divider = QFrame(); divider.setFixedWidth(1); divider.setStyleSheet("background:#353538;"); row.addWidget(divider)
        self.details = AnimatedPageStack(); row.addWidget(self.details, 1)
        self.detail_scroll = SmoothScrollArea(); self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.details.addWidget(self.detail_scroll)
        selected = state.get("selected")
        self.select_artist(selected if selected in self.artists else next(iter(self.artist_buttons)), animate=False)
        self.restore_positions = (state.get("list_scroll", 0), state.get("detail_scroll", 0))

    def restore_scroll(self):
        self.artist_list.verticalScrollBar().setValue(self.restore_positions[0])
        self.detail_scroll.verticalScrollBar().setValue(self.restore_positions[1])
        self.artist_list.verticalScrollBar().valueChanged.connect(lambda value: self.state.update(list_scroll=value))
        self.detail_scroll.verticalScrollBar().valueChanged.connect(lambda value: self.state.update(detail_scroll=value))

    def action_button(self, symbol, text, callback):
        action = button("", symbol, compact=True); action.setProperty("plain", True); action.setFixedSize(30, 30)
        action.setIcon(icon(symbol, RED, 19)); action.setToolTip(text); action.setAccessibleName(text)
        action.clicked.connect(callback)
        return action

    def select_artist(self, name, animate=True):
        if animate and name == self.state.get("selected"):
            self.artist_buttons[name].setChecked(True); return
        before = self.details.capture_page() if animate else None
        if name != self.state.get("selected"): self.state["detail_scroll"] = 0
        self.state["selected"] = name
        for artist, item in self.artist_buttons.items(): item.setChecked(artist == name)
        songs = self.artists[name]; albums = {}
        for track in songs: albums.setdefault(track.album_key, []).append(track)
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(26, 0, 4, 16); layout.setSpacing(22)
        heading = QVBoxLayout(); heading.setSpacing(8); title_row = QHBoxLayout()
        title = label(name, 20, True); title.setWordWrap(True); title_row.addWidget(title, 1)
        title_row.addWidget(self.action_button("player_play", "播放此艺人", lambda: self.owner.play_tracks(songs)))
        title_row.addWidget(self.action_button("player_shuffle", "随机播放此艺人", lambda: self.owner.play_tracks(random.sample(songs, len(songs)))))
        heading.addLayout(title_row)
        heading.addWidget(label(f"{len(albums)} 张专辑 · {len(songs)} 首歌曲", 10, color="#9898a1"))
        divider = QFrame(); divider.setFixedHeight(1); divider.setStyleSheet("background:#323235;"); heading.addWidget(divider)
        layout.addLayout(heading); self.album_rows, self.album_tables = [], []
        for tracks in albums.values():
            album = tracks[0].album
            tracks = sorted(tracks, key=lambda track: track.order)
            section = QBoxLayout(QBoxLayout.Direction.LeftToRight); section.setSpacing(22)
            artwork = QVBoxLayout(); artwork.setSpacing(8)
            cover = Cover(tracks[0].cover, 156, 5); self.owner.bind_album_menu(cover, tracks); artwork.addWidget(cover, 0, Qt.AlignmentFlag.AlignLeft)
            duration = label(f"{len(tracks)} 首歌曲 · {duration_text(sum(track.duration for track in tracks))}", 9, color="#9898a1")
            artwork.addWidget(duration); artwork.addStretch(); section.addLayout(artwork)
            music = QVBoxLayout(); music.setSpacing(10); album_row = QHBoxLayout()
            title = label(album, 14, True); self.owner.bind_album_menu(title, tracks); title.setWordWrap(True); album_row.addWidget(title, 1)
            album_row.addWidget(self.action_button("player_play", "播放专辑：" + album, lambda _, songs=tracks: self.owner.play_tracks(songs)))
            music.addLayout(album_row); music.addWidget(label(" · ".join(value for value in (tracks[0].edition, tracks[0].quality) if value), 10, color="#9898a1"))
            table = self.owner.track_table(tracks); table.setColumnCount(7); table.horizontalHeader().hide()
            table.setStyleSheet("QTableWidget { background:transparent; }")
            for column in (2, 3, 4): table.hideColumn(column)
            table.setColumnWidth(0, 34); table.setColumnWidth(5, 56); table.setColumnWidth(6, 46)
            table.verticalHeader().setDefaultSectionSize(46); table.setWordWrap(False)
            table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            table.setFixedHeight(46 * len(tracks) + 2); table.setMinimumWidth(0)
            for index, track in enumerate(tracks):
                table.item(index, 1).setText("")
                table.item(index, 1).setData(Qt.ItemDataRole.AccessibleTextRole, track.title + " · " + track.artist)
                description = QWidget(); description.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                lines = QVBoxLayout(description); lines.setContentsMargins(8, 3, 0, 3); lines.setSpacing(0)
                for text, color in ((track.title, "#eeeeF2"), (track.artist, "#9898a1")):
                    line = PlayerLabel(text, color=color); line.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft); lines.addWidget(line)
                table.setCellWidget(index, 1, description)
                more = self.action_button("more", "歌曲操作：" + track.title,
                                          lambda _, song=track, songs=tracks, view=table: self.song_menu(song, songs, view))
                cell = QWidget(); cell_row = QHBoxLayout(cell); cell_row.setContentsMargins(0, 0, 0, 0)
                cell_row.addWidget(more, 0, Qt.AlignmentFlag.AlignVCenter); table.setCellWidget(index, 6, cell)
            music.addWidget(table); music.addStretch(); section.addLayout(music, 1)
            layout.addLayout(section); self.album_rows.append((section, cover)); self.album_tables.append(table)
        layout.addStretch()
        previous = self.detail_scroll.takeWidget()
        if previous: previous.deleteLater()
        self.detail_scroll.setWidget(page); self.update_columns()
        if animate:
            self.detail_scroll.verticalScrollBar().setValue(0)
            page.layout().activate(); self.details.reveal_page(before)

    def song_menu(self, track, tracks, table):
        if track not in tracks: return
        row = tracks.index(track)
        self.owner.track_menu(table, tracks, QPoint(8, table.rowViewportPosition(row) + table.rowHeight(row) // 2))

    def update_columns(self):
        compact = self.width() < 740
        self.artist_list.setFixedWidth(max(145, min(205, round(self.width() * .22))))
        for section, cover in self.album_rows:
            section.setDirection(QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight)
            cover.setFixedSize(120 if compact else 156, 120 if compact else 156)

    def resizeEvent(self, event):
        self.update_columns(); super().resizeEvent(event)
