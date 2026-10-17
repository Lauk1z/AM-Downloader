"""Explicit packaging verification mode; never runs during normal application use."""
import json
from pathlib import Path
import time
from PySide6.QtCore import QTimer


def start_login_ui(window, output):
    """Isolated GUI checks. Synthetic events only; no backend process is started."""
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    if window.accounts.history(): raise RuntimeError("Login UI verification requires a fresh profile")
    commands = []; window.client.send = commands.append
    checks = []; state = {"phase": 0}
    timer = QTimer(window); timer.setInterval(300)
    def complete(error=""):
        timer.stop()
        (output / "report.json").write_text(json.dumps({"ok": not error, "error": error, "checks": checks, "real_apple_login": False}, ensure_ascii=False, indent=2), encoding="utf-8")
        window.tray.exit()
    def tick():
        try:
            phase = state["phase"]
            if phase == 0:
                window.login_dialog(); dialog = window.login_window
                assert dialog.remember.isChecked() and dialog.automatic.isChecked()
                dialog.reject(); checks.append("new_login_defaults_to_remember_and_automatic")
                window.accounts.success("older@example.test", "older-test-only", True, False)
                window.accounts.success("latest@example.test", "latest-test-only", True, True)
                window.login_dialog(); dialog = window.login_window
                assert dialog.password.text() == "latest-test-only"
                checks.append("remembered_password_loaded_from_windows_encryption")
            elif phase == 1:
                dialog = window.login_window; dialog.grab().save(str(output / "login.png"))
                dialog.start_login(); assert dialog.isVisible()
                window.backend_event({"event": "login", "request_id": dialog.request_id, "ok": False, "error": "账号或密码错误，请修改后重试。"})
                assert dialog.isVisible() and dialog.submit.isEnabled()
                checks.append("incorrect_password_keeps_dialog_open")
            elif phase == 2:
                dialog = window.login_window; dialog.grab().save(str(output / "error.png"))
                dialog.automatic.setChecked(True); dialog.start_login()
                window.backend_event({"event": "twofa", "request_id": dialog.request_id, "challenge_id": "first-login"})
            elif phase == 3:
                dialog = window.login_window; verify = dialog.verification
                assert verify.isVisible(); verify.grab().save(str(output / "verification.png"))
                state["verification"] = verify; state["old_request"] = dialog.request_id
                verify.code.setText("111111"); verify.send_code()
                assert verify.isVisible() and not verify.submit.isEnabled()
                window.backend_event({"event": "login", "request_id": dialog.request_id, "ok": False, "error": "验证码错误，请重新验证。"})
                assert dialog.verification is verify and verify.isVisible() and verify.submit.isEnabled()
                assert not verify.code.text() and not verify.code.isEnabled()
                state["command_count"] = len(commands)
                checks.append("incorrect_code_keeps_original_verification_window_open")
            elif phase == 4:
                dialog = window.login_window; verify = dialog.verification
                assert len(commands) == state["command_count"]
                verify.grab().save(str(output / "verification-error.png")); verify.submit.click()
                assert commands[-1]["action"] == "login" and "code" not in commands[-1]
                assert dialog.request_id != state["old_request"] and not verify.code.isEnabled()
                window.backend_event({"event": "login", "request_id": state["old_request"], "ok": True, "regions": ["CN"]})
                assert dialog.isVisible() and verify.isVisible()
                window.backend_event({"event": "twofa", "request_id": dialog.request_id, "challenge_id": "retry-login"})
                assert dialog.verification is verify and not verify.code.text() and verify.code.isEnabled()
                checks.append("explicit_retry_uses_new_challenge_in_same_window_and_ignores_stale_success")
            elif phase == 5:
                dialog = window.login_window; verify = dialog.verification
                verify.code.setText("654321"); verify.send_code()
                assert commands[-1]["action"] == "twofa" and commands[-1]["code"] == "654321"
                assert commands[-1]["challenge_id"] == "retry-login" and verify.isVisible()
                window.backend_event({"event": "login", "request_id": dialog.request_id, "ok": True, "regions": ["CN"]})
                assert window.login_window is None
                checks.append("verification_code_submitted_and_success_closes_both_dialogs")
            elif phase == 6:
                window.login_dialog(); dialog = window.login_window
                dialog.user.setCurrentIndex(1); dialog.select_history()
                assert dialog.user.currentText() == "older@example.test" and not dialog.password.text()
                dialog.user.showPopup(); checks.append("history_fills_username_only")
            elif phase == 7:
                dialog = window.login_window; dialog.user.view().grab().save(str(output / "history.png"))
                dialog.user.hidePopup(); dialog.reject()
                window.accounts.success("latest@example.test", "latest-test-only", True, True)
                window.auto_login_attempted = False; window.try_auto_login([])
                assert window.login_window and window.login_window.pending
                dialog = window.login_window
                window.backend_event({"event": "twofa", "request_id": dialog.request_id, "challenge_id": "automatic"})
                assert dialog.verification.isVisible()
                checks.append("automatic_login_still_prompts_for_verification")
                window.backend_event({"event": "login", "request_id": dialog.request_id, "ok": False, "error": "模拟网络中断"})
                count = len(commands); window.try_auto_login([]); assert len(commands) == count
                assert not window.accounts.history()[0]["automatic"]
                assert dialog.verification.isVisible() and dialog.verification.submit.isEnabled()
                text = window.store.path.read_text(encoding="utf-8")
                assert all(secret not in text for secret in ("latest-test-only", "older-test-only", "111111", "654321"))
                checks.append("automatic_failure_does_not_loop_and_secrets_not_plaintext")
                dialog.reject()
                window.accounts.store.set("login_accounts", [])
            elif phase == 8:
                count = len(commands)
                window.backend_event({"event": "backend", "state": "ready", "regions": ["CN"]})
                assert window.backend_dot.text() == "●  已登录 · CN" and window.login_window is None
                assert len(commands) == count
                window.grab().save(str(output / "restored-session.png"))
                checks.append("existing_backend_session_restored_without_saved_password_or_login_prompt")
                complete(); return
            state["phase"] += 1
        except Exception as error: complete(str(error) or type(error).__name__)
    timer.timeout.connect(tick); timer.start()


def start_startup(window, output):
    """Observe normal autostart without sending a start command from the test."""
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic(); ticks = []
    timer = QTimer(window); timer.setInterval(50)
    result = {"ok": False, "error": "", "ui_responsive": False}
    def finish(error=""):
        timer.stop(); result["error"] = error
        if error:
            (output / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        window.tray.exit()
    def tick():
        ticks.append(time.monotonic())
        if len(ticks) == 2: window.navigate("settings")
        if time.monotonic() - started > 180: finish("Automatic backend startup timed out")
    def event(value):
        if value.get("event") == "hello": result["bootstrap_seconds"] = round(time.monotonic() - started, 2)
        if value.get("event") == "backend" and value.get("state") == "ready":
            gaps = [b - a for a, b in zip(ticks, ticks[1:])]
            result.update(ok=True, ready_seconds=round(time.monotonic() - started, 2),
                            accelerator=value.get("accelerator"), boot_mode=value.get("boot_mode"), region_count=len(value.get("regions", [])),
                          service_startup_seconds=value.get("startup_seconds"),
                          ui_responsive=len(ticks) > 10 and max(gaps, default=0) < 1,
                          max_ui_tick_gap_seconds=round(max(gaps, default=0), 3))
            result["account_restored"] = bool(value.get("regions")) and window.backend_dot.text().startswith("●  已登录")
            result["login_prompt_open"] = window.login_window is not None
            if value.get("regions") and (not result["account_restored"] or result["login_prompt_open"]):
                finish("Existing login session was not restored in the GUI"); return
            window.grab().save(str(output / "ready.png")); finish()
        elif value.get("event") == "disconnected":
            result["clean_shutdown"] = value.get("expected") and value.get("code") == 0
            result["ok"] = result["ok"] and result["ui_responsive"] and result["clean_shutdown"]
            (output / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        elif value.get("event") == "fatal" or value.get("event") == "backend" and value.get("state") == "error":
            finish(value.get("message", "Backend failed"))
    window.client.event.connect(event); timer.timeout.connect(tick); timer.start()


def start(window, output):
    from .runtime import is_managed
    if is_managed(window.root): return start_bundled(window, output)
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    timer = QTimer(window); timer.setInterval(100)
    state = {"phase": "library", "started": time.monotonic(), "checks": []}
    events = []; window.client.event.connect(events.append)
    window.audio.setMuted(True)
    def complete(ok, error=""):
        timer.stop()
        (output / "report.json").write_text(json.dumps({"ok": ok, "error": error, "checks": state["checks"]}, ensure_ascii=False, indent=2), encoding="utf-8")
        window.tray.exit()
    def step():
        try:
            if time.monotonic() - state["started"] > 150: raise TimeoutError("Verification timed out: " + state["phase"])
            if state["phase"] == "library" and window.tracks:
                state["checks"].append({"library_tracks": len(window.tracks)})
                window.play_tracks(window.tracks[:1]); state["phase"] = "playing"
            elif state["phase"] == "playing" and window.media.position() > 800:
                state["checks"].append({"playback": True, "duration_ms": window.media.duration()})
                window.media.setPosition(30000); state["phase"] = "seek"
            elif state["phase"] == "seek" and window.media.position() >= 30000:
                state["checks"].append({"seek": True}); window.media.pause()
                window.grab().save(str(output / "library.png"))
                window.navigate("settings"); window.grab().save(str(output / "settings.png"))
                window.navigate("search"); window.search.setText("Eagles Hotel California"); state["phase"] = "search"
            elif state["phase"] == "search" and getattr(window, "search_cards", []) and len(window.art_cache) >= 5:
                state["checks"].append({"catalog_results": len(window.search_cards), "artwork": len(window.art_cache)})
                window.grab().save(str(output / "search.png"))
                window.enqueue(["https://music.apple.com/cn/song/hotel-california/635770202"], "alac"); state["phase"] = "queue"
            elif state["phase"] == "queue":
                result = next((event for event in events if event["event"] in {"finished", "fatal"}), None)
                if result:
                    if result.get("state") != "DONE": raise RuntimeError(str(result))
                    state["checks"].append({"worker_job": "DONE"})
                    window.grab().save(str(output / "queue.png")); complete(True)
        except Exception as error:
            complete(False, str(error))
    timer.timeout.connect(step); timer.start()


def start_bundled(window, output):
    """Fresh-profile check: never submits credentials or downloads music."""
    from .runtime import code_root
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    events = []; window.client.event.connect(events.append)
    window.navigate("settings")
    timer = QTimer(window); timer.setInterval(100)
    state = {"phase": "start", "started": time.monotonic()}
    checks = []
    def complete(ok, error=""):
        timer.stop()
        (output / "report.json").write_text(json.dumps({"ok": ok, "error": error, "checks": checks}, ensure_ascii=False, indent=2), encoding="utf-8")
        window.tray.exit()
    def step():
        try:
            if time.monotonic() - state["started"] > 180: raise TimeoutError("Bundled GUI verification timed out")
            error = next((event for event in events if event["event"] in {"fatal", "error"} or event["event"] == "backend" and event.get("state") == "error"), None)
            if error: raise RuntimeError(str(error))
            if state["phase"] == "start":
                assert not hasattr(window, "root_field")
                window.client.send({"action": "start"}); state["phase"] = "ready"
                assert Path(window.client.process.program()) == code_root(window.root) / ".venv/python.exe"
                checks.append({"bundled_python": True, "managed_settings": True})
            elif state["phase"] == "ready":
                ready = next((event for event in events if event["event"] == "backend" and event.get("state") == "ready"), None)
                if ready:
                    assert not ready["regions"], "This check requires an unused account profile"
                    checks.append({"clean_account": True, "ready_seconds": round(time.monotonic() - state["started"], 1)})
                    window.client.send({"action": "search", "serial": 9000, "country": "CN", "term": "Eagles Hotel California"})
                    state["phase"] = "search"
            elif state["phase"] == "search":
                result = next((event for event in events if event["event"] == "catalog"), None)
                if result:
                    assert result.get("results"), result
                    checks.append({"live_catalog_results": len(result["results"])})
                    window.client.send({"action": "download", "id": "login-guard", "url": "https://music.apple.com/cn/song/635770202", "codec": "alac", "output_dir": str(output / "music")})
                    state["phase"] = "guard"
            elif state["phase"] == "guard":
                result = next((event for event in events if event["event"] == "finished"), None)
                if result:
                    assert result["state"] == "FAILED" and "登录" in result["error"]
                    checks.append({"login_required": True})
                    window.grab().save(str(output / "settings.png"))
                    window.client.shutdown(); state["phase"] = "stop"
            elif state["phase"] == "stop":
                result = next((event for event in events if event["event"] == "disconnected"), None)
                if result:
                    assert result["expected"] and result["code"] == 0, result
                    checks.append({"clean_shutdown": True}); complete(True)
        except Exception as error: complete(False, str(error))
    timer.timeout.connect(step); timer.start()


def start_ui(window, output, import_only=False):
    """Offline UI check; removal only touches a uniquely generated audio fixture."""
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    window.audio.setMuted(True)
    timer = QTimer(window); timer.setInterval(50)
    state = {"started": time.monotonic(), "index": 0, "phase": "lyrics_closed" if import_only else "library"}
    checks = []
    def complete(ok, error=""):
        timer.stop()
        (output / "report.json").write_text(json.dumps({"ok": ok, "error": error, "checks": checks}, ensure_ascii=False, indent=2), encoding="utf-8")
        window.tray.exit()
    def step():
        try:
            if time.monotonic() - state["started"] > 30: raise TimeoutError("UI verification timed out")
            if state["phase"] == "library" and window.tracks:
                if window.store.get("last_track"):
                    from PySide6.QtMultimedia import QMediaPlayer
                    assert window.current_path == window.store.get("last_track")
                    assert window.media.playbackState() != QMediaPlayer.PlaybackState.PlayingState
                    checks.append({"last_track_restored_without_autoplay": True, "title": window.play_title.text()})
                    window.grab().save(str(output / "restored-player.png"))
                assert {"recent", "artists", "albums", "songs"}.issubset(window.nav)
                assert "search" not in window.nav
                checks.append({"library_navigation_restored": True, "discover_navigation_removed": True})
                from .widgets import RoundedTable
                assert isinstance(window.queue_table, RoundedTable)
                checks.append({"rounded_list_component": True})
                from .icons import icon
                from PySide6.QtCore import QSize
                glyph = icon("artist").pixmap(QSize(24, 24), window.devicePixelRatioF())
                assert glyph.width() == round(24 * window.devicePixelRatioF())
                assert window.nav["songs"].icon().name() == "songs"
                assert window.nav["favourites"].icon().name() == "favourites"
                assert window.like_button.icon().name() == "player_star"
                checks.append({"vector_icons": True, "icon_dpr": glyph.devicePixelRatio()})
                from PySide6.QtGui import QFont, QRawFont
                faces = []
                for widget, weight in ((window.search, 400), (window.play_title, 700)):
                    font = widget.font(); raw = QRawFont.fromFont(font)
                    assert font.styleStrategy() & QFont.StyleStrategy.PreferAntialias
                    assert font.styleStrategy() & QFont.StyleStrategy.NoSubpixelAntialias
                    assert font.hintingPreference() == QFont.HintingPreference.PreferNoHinting
                    assert int.from_bytes(raw.fontTable("OS/2").data()[4:6]) == weight
                    faces.append({"family": raw.familyName(), "style": raw.styleName(), "weight": weight})
                checks.append({"text_antialiasing": True, "font_faces": faces})
                state["pages"] = ["recent", "artists", "albums", "songs", "settings", "queue", "favourites", "home", next(iter(window.sidebar_albums))]
                window.play_tracks(window.tracks[:1]); state["album_index"] = 0; state["phase"] = "album_entries"
            elif state["phase"] == "album_entries":
                if state["album_index"] == 3:
                    state["phase"] = "next"; return
                window.navigate("albums" if state["album_index"] == 2 else "home")
                state["phase"] = "album_card"
            elif state["phase"] == "album_card" and not window.stack.transition.isVisible():
                from .widgets import AlbumCard, FeatureCard
                from PySide6.QtCore import Qt
                from PySide6.QtTest import QTest
                kind = FeatureCard if state["album_index"] == 0 else AlbumCard
                card = window.library_scroll.findChildren(kind)[0]
                state["album_title"] = card.toolTip().split("\n")[0] if kind is FeatureCard else card.title.toolTip()
                state["playing_path"] = window.current_path
                QTest.mouseClick(card, Qt.MouseButton.LeftButton)
                assert window.stack.transition.isVisible(); state["phase"] = "album_detail"
            elif state["phase"] == "album_detail" and not window.stack.transition.isVisible():
                from PySide6.QtWidgets import QDialog, QPushButton
                from .widgets import RoundedTable
                assert window.current_page in window.album_pages
                tracks = window.album_pages[window.current_page]
                assert tracks[0].album == state["album_title"] and window.current_path == state["playing_path"]
                assert window.library_scroll.findChild(RoundedTable).rowCount() == len(tracks)
                assert not any(d.isVisible() for d in window.findChildren(QDialog))
                assert not any(b.text() == "查看专辑" for b in window.library_scroll.findChildren(QPushButton))
                window.grab().save(str(output / f"album-main-{state['album_index']}.png"))
                checks.append({"album_entry": state["album_index"], "main_page": True, "recursive_button_removed": True})
                state["album_index"] += 1; state["phase"] = "album_entries"
            elif state["phase"] == "next":
                if state["index"] == len(state["pages"]):
                    assert window.media.position() > 0
                    checks.append({"local_playback_during_navigation": True})
                    from PySide6.QtCore import QEvent
                    from PySide6.QtWidgets import QApplication
                    window.media.pause(); window.media.setPosition(10000); window.position_changed(10000)
                    QApplication.sendEvent(window.now_playing, QEvent(QEvent.Type.Enter))
                    assert window.elapsed.isVisible() and window.elapsed.text() == "0:10"
                    assert window.remaining.isVisible() and window.remaining.text().startswith("-")
                    window.player_bar.grab().save(str(output / "player-hover.png"))
                    QApplication.sendEvent(window.now_playing, QEvent(QEvent.Type.Leave))
                    assert not window.elapsed.isVisible() and not window.remaining.isVisible()
                    window.show_volume(); window.volume.setValue(27)
                    assert window.volume_popup.isVisible() and abs(window.audio.volume() - .27) < .001
                    popup_image = window.volume_popup.grab().toImage()
                    assert all(popup_image.pixelColor(x, y).alpha() == 0 for x, y in ((0, 0), (popup_image.width() - 1, 0), (0, popup_image.height() - 1), (popup_image.width() - 1, popup_image.height() - 1)))
                    assert popup_image.pixelColor(popup_image.width() // 2, round(6 * popup_image.devicePixelRatio())).name() == window.player_bar.base
                    popup_image.save(str(output / "volume-popup.png"))
                    window.volume.value_tip.show(); window.volume.refresh_value_tip()
                    assert window.volume.value_tip.text() == "27%" and window.volume_button.icon().name() == "player_volume_low"
                    window.volume.value_tip.grab().save(str(output / "volume-percent.png")); window.volume_popup.hide()
                    assert not window.volume.value_tip.isVisible()
                    checks.append({"player_hover_details": True, "volume_popup": True, "transparent_corners": True, "matching_background": True, "live_volume_percent": True})
                    window.navigate("songs"); window.search.setText("Eagles"); window.search_changed()
                    assert window.stack.transition.isVisible()
                    state["phase"] = "local_search"; return
                page = state["pages"][state["index"]]
                window.nav[page].click()
                assert window.stack.transition.isVisible()
                state["phase"] = "transition"; state["captured"] = False
            elif state["phase"] == "transition":
                transition = window.stack.transition
                if transition.isVisible() and transition.progress >= .3 and not state["captured"]:
                    transition.grabFramebuffer().save(str(output / f"transition-{state['index']}.png")); state["captured"] = True
                if not transition.isVisible():
                    assert transition.before.isNull() and transition.after.isNull()
                    assert state["captured"]
                    window.grab().save(str(output / f"page-{state['index']}.png"))
                    checks.append({"animated_page": state["index"], "completed": True})
                    state["index"] += 1; state["phase"] = "next"
            elif state["phase"] == "local_search" and not window.stack.transition.isVisible():
                assert window.filtered_tracks() and all("eagles" in track.artist.casefold() for track in window.filtered_tracks())
                window.grab().save(str(output / "search-filter.png"))
                window.search.clear(); window.search_timer.stop(); window.navigate("search")
                # Exercise result replacement offline, without contacting the catalog service.
                window.render_search([{"trackName": window.tracks[0].title, "artistName": window.tracks[0].artist}])
                assert window.stack.transition.isVisible(); state["phase"] = "catalog_search"
            elif state["phase"] == "catalog_search" and not window.stack.transition.isVisible():
                assert len(window.search_cards) == 1
                checks.append({"local_search_transition": True, "catalog_result_transition": True})
                window.lyric_button.click()
                assert window.body.transition.isVisible() and window.body.opened
                state["phase"] = "lyrics_open"
            elif state["phase"] == "lyrics_open" and not window.body.transition.isVisible():
                assert window.lyrics.isVisible() and not window.lyrics.isWindow()
                assert window.stack.width() < window.body.width()
                sample = output / "scroll-fixture.m4a"
                sample.with_suffix(".lrc").write_text("\n".join(f"[00:{i + 1:02}.00]歌词滚动测试 · 第 {i + 1} 行" for i in range(35)), encoding="utf-8")
                window.lyrics.set_track(str(sample)); window.lyrics.set_position(18000)
                assert window.lyrics.scroll.verticalScrollBar().value() == 0
                assert window.lyrics.is_scrolling()
                state["phase"] = "lyrics_scroll"
            elif state["phase"] == "lyrics_scroll" and window.lyrics.scroll_clock.elapsed() >= 80:
                assert 0 < window.lyrics.scroll.verticalScrollBar().value() < window.lyrics.scroll_target
                from PySide6.QtCore import QPoint
                from PySide6.QtGui import QImage, QPainter
                surface = window.lyrics.surface; origin = surface.mapTo(window, QPoint()); dpr = window.devicePixelRatioF()
                # QWidget.grab can corrupt nested OpenGL readback on Windows.
                # Validate the actual GPU frame and explicitly compose the QA image.
                frame = window.grab(); gpu = surface.grabFramebuffer(); gpu.setDevicePixelRatio(dpr)
                gpu.save(str(output / "lyrics-gpu-frame.png"))
                painter = QPainter(frame); painter.drawImage(origin, gpu); painter.end()
                frame.save(str(output / "lyrics-scroll-middle.png"))
                pixels = gpu.convertToFormat(QImage.Format.Format_RGBA8888)
                data = bytes(pixels.constBits())
                assert data[0::4] == data[1::4], "Unexpected colored artifacts in the neutral lyric layer"
                state["phase"] = "lyrics_settled"
            elif state["phase"] == "lyrics_settled" and not window.lyrics.is_scrolling():
                assert window.lyrics.scroll.verticalScrollBar().value() == window.lyrics.scroll_target
                checks.append({"lyrics_smooth_scroll": True, "intermediate_position": True, "settled_at_current_line": True})
                from PySide6.QtCore import Qt
                from PySide6.QtTest import QTest
                from PySide6.QtMultimedia import QMediaPlayer
                QTest.mouseClick(window.lyrics.lines[17], Qt.MouseButton.LeftButton)
                assert window.media.position() == 18000 and window.lyrics.active == 17
                assert window.media.playbackState() == QMediaPlayer.PlaybackState.PausedState
                assert window.seek.value() == 18000
                checks.append({"click_lyrics_seek_paused": True, "position_ms": window.media.position()})
                window.media.play()
                QTest.mouseClick(window.lyrics.lines[19], Qt.MouseButton.LeftButton)
                state["phase"] = "lyrics_seek_playing"
            elif state["phase"] == "lyrics_seek_playing" and window.media.position() >= 20100:
                from PySide6.QtMultimedia import QMediaPlayer
                assert window.media.position() < 21000 and window.lyrics.active == 19
                assert window.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState
                checks.append({"click_lyrics_seek_playing": True, "position_ms": window.media.position()})
                window.media.pause()
                window.grab().save(str(output / "lyrics-sidebar.png")); window.lyric_button.click()
                assert window.body.transition.isVisible(); state["phase"] = "lyrics_closed"
            elif state["phase"] == "lyrics_closed" and not window.body.transition.isVisible() and not window.scanning:
                assert not window.lyrics.isVisible() and window.stack.width() == window.body.width()
                assert window.body.transition.panel.isNull()
                if not import_only: checks.append({"lyrics_sidebar": True, "animated_open_close": True, "nonmodal": True})
                import wave
                from uuid import uuid4
                folder = output / ("本地音乐 导入测试-" + uuid4().hex)
                nested = folder / "艺人" / "专辑"; nested.mkdir(parents=True)
                sample = nested / ("AM-Dowloader-删除测试-" + uuid4().hex + ".wav")
                with wave.open(str(sample), "wb") as audio:
                    audio.setparams((1, 2, 8000, 0, "NONE", "not compressed")); audio.writeframes(b"\0\0" * 8000 * 5)
                sample.with_suffix(".lrc").write_text("[00:00.00]删除测试歌词", encoding="utf-8")
                top = folder / "根目录歌曲.WAV"; top.write_bytes(sample.read_bytes())
                (folder / "损坏.mp3").write_bytes(b"not audio")
                state["removal_path"] = sample
                state["import_folder"], state["import_top"] = folder, top
                state["original_audio"] = sample.read_bytes()
                window.import_audio_files([], folder=str(folder)); state["phase"] = "folder_import"
            elif state["phase"] == "folder_import" and not window.importing and not window.scanning:
                assert "跳过 1 个" in window.notice.text()
                window.import_audio_files([], folder=str(state["import_folder"])); state["phase"] = "folder_duplicate"
            elif state["phase"] == "folder_duplicate" and not window.importing and not window.scanning:
                for path in (state["removal_path"], state["import_top"]):
                    assert window.store.get("imported_files").count(str(path)) == 1
                    assert sum(track.path == str(path) for track in window.tracks) == 1
                    assert path.read_bytes() == state["original_audio"]
                assert "2 首已在资料库" in window.notice.text()
                checks.append({"folder_import_recursive": True, "unicode_paths": True, "deduplicated": True, "invalid_audio_skipped": True, "original_files_preserved": True})
                if import_only:
                    window.grab().save(str(output / "imported-folder.png")); complete(True)
                else: state["phase"] = "removal_import"
            elif state["phase"] == "removal_import" and not window.importing and not window.scanning and not window.stack.transition.isVisible():
                sample = state["removal_path"]
                target = next(track for track in window.tracks if track.path == str(sample))
                from PySide6.QtWidgets import QApplication
                from .widgets import RoundedTable
                table = window.library_scroll.findChild(RoundedTable)
                row = next(row for row in range(table.rowCount()) if table.item(row, 1).text() == target.title)
                def capture_menu():
                    menu = QApplication.activePopupWidget()
                    state["removal_actions"] = [action.text() for action in menu.actions()]
                    menu.grab().save(str(output / "remove-menu.png")); menu.close()
                QTimer.singleShot(30, capture_menu)
                table.customContextMenuRequested.emit(table.visualItemRect(table.item(row, 1)).center())
                assert "从列表中删除" in state["removal_actions"] and "删除本地文件" in state["removal_actions"]
                assert window.remove_track(target)
                state["phase"] = "removal_hidden"
            elif state["phase"] == "removal_hidden" and not window.scanning:
                sample = state["removal_path"]
                assert sample.is_file() and all(track.path != str(sample) for track in window.tracks)
                checks.append({"remove_from_list_preserves_file": True, "context_menu_options": True})
                window.import_audio_files([str(sample)]); state["phase"] = "removal_reimport"
            elif state["phase"] == "removal_reimport" and not window.importing and not window.scanning:
                target = next(track for track in window.tracks if track.path == str(state["removal_path"]))
                window.play_tracks([target]); state["phase"] = "removal_playing"
            elif state["phase"] == "removal_playing" and window.media.position() > 50:
                sample = state["removal_path"]
                target = next(track for track in window.tracks if track.path == str(sample))
                assert window.remove_track(target, delete_file=True), window.notice.toolTip()
                assert not sample.exists() and sample.with_suffix(".lrc").is_file()
                assert not window.current_path and window.media.source().isEmpty()
                checks.append({"reimport_restores_hidden_song": True, "recycled_playing_fixture": sample.name, "sidecar_preserved": True, "player_cleared": True})
                state["phase"] = "removal_done"
            elif state["phase"] == "removal_done" and not window.scanning:
                assert all(track.path != str(state["removal_path"]) for track in window.tracks)
                window.grab().save(str(output / "after-removal.png"))
                complete(True)
        except Exception as error:
            complete(False, str(error) or type(error).__name__)
    timer.timeout.connect(step); timer.start()


def benchmark_lyrics(window, output):
    """Compare lyric and page GPU swap cadence in the same full-size window."""
    import statistics
    import ctypes
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    window.showMaximized(); window.audio.setMuted(True)
    panel = window.lyrics; bar = panel.scroll.verticalScrollBar()
    timer = QTimer(window); timer.setInterval(30)
    state = {"phase": "library", "index": 0, "started": time.monotonic()}
    targets, results, frames, page_frames, pages = [20, 21, 22, 40, 39, 38], [], [], [], []
    def swapped():
        if state["phase"] == "scroll" and panel.is_scrolling():
            frames.append((time.perf_counter(), panel.surface.painted_offset))
    def page_swapped():
        if state["phase"] == "page" and window.stack.transition.clock.isValid():
            page_frames.append((time.perf_counter(), window.stack.transition.progress))
    panel.surface.frameSwapped.connect(swapped)
    window.stack.transition.frameSwapped.connect(page_swapped)
    def summary(values):
        intervals = sorted((b[0] - a[0]) * 1000 for a, b in zip(values, values[1:]))
        assert intervals, "No GPU swaps recorded"
        return {"frames": len(values), "distinct_positions": len({value for _, value in values}),
                "median_ms": round(statistics.median(intervals), 2),
                "p95_ms": round(intervals[int((len(intervals) - 1) * .95)], 2), "max_ms": round(max(intervals), 2)}
    def complete(error=""):
        timer.stop()
        report = {"ok": not error, "error": error, "measurement": "Qt OpenGL frameSwapped cadence, not physical panel scanout",
                  "renderer": state.get("renderer", ""), "refresh_hz": window.screen().refreshRate(), "dpr": window.devicePixelRatioF(),
                  "window": [window.width(), window.height()], "results": results, "page_results": pages}
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        window.grab().save(str(output / "lyrics.png")); window.tray.exit()
    def step():
        try:
            if time.monotonic() - state["started"] > 30: raise TimeoutError("Lyrics benchmark timed out")
            if state["phase"] == "library" and window.tracks and not window.scanning:
                window.playlist = [window.tracks[0]]; window.play_index = 0; window.play_current(autoplay=False)
                sample = output / "performance.m4a"
                sample.with_suffix(".lrc").write_text("\n".join(f"[{i // 60:02}:{i % 60:02}.00]歌词滚动测试 第 {i} 行\n[{i // 60:02}:{i % 60:02}.00]Music and lyrics with wrapped words" for i in range(180)), encoding="utf-8")
                panel.set_track(str(sample), window.tracks[0].cover); window.show_lyrics()
                state["phase"] = "ready"; state["ready_at"] = time.monotonic()
            elif state["phase"] == "ready" and time.monotonic() - state["ready_at"] > .6:
                assert panel.surface.isValid(), "GPU lyric surface unavailable"
                panel.surface.makeCurrent()
                query = ctypes.windll.opengl32.glGetString; query.restype = ctypes.c_char_p
                state["renderer"] = query(0x1F01).decode("utf-8", "replace")
                panel.surface.doneCurrent(); state["phase"] = "next"
            elif state["phase"] == "next":
                if state["index"] == len(targets):
                    state["phase"] = "page_next"; return
                frames.clear(); state["cache_key"] = panel.background.cacheKey()
                state["phase"] = "scroll"; state["scroll_at"] = time.monotonic()
                panel.set_position(targets[state["index"]] * 1000)
                assert not panel.scroll_timer.isActive(), "Unexpected timer fallback"
            elif state["phase"] == "scroll" and time.monotonic() - state["scroll_at"] > .46:
                assert not panel.is_scrolling() and bar.value() == panel.scroll_target
                assert panel.background.cacheKey() == state["cache_key"]
                result = summary(frames)
                assert result["distinct_positions"] > 10
                results.append({"target": targets[state["index"]], "background_reused": True, **result})
                state["index"] += 1; state["phase"] = "next"
            elif state["phase"] == "page_next":
                if len(pages) == 3: complete(); return
                page_frames.clear(); state["phase"] = "page"; state["page_at"] = time.monotonic()
                window.navigate("songs" if len(pages) % 2 == 0 else "home")
            elif state["phase"] == "page" and time.monotonic() - state["page_at"] > .4:
                assert not window.stack.transition.clock.isValid()
                pages.append(summary(page_frames)); state["phase"] = "page_next"
        except Exception as error: complete(str(error) or type(error).__name__)
    timer.timeout.connect(step); timer.start()


def benchmark_animation(window, output):
    """Measure completed display frames; never capture screenshots in the loop."""
    import statistics
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    window.showMaximized()
    timer = QTimer(window); timer.setInterval(50)
    state = {"phase": "library", "index": 0, "started": time.monotonic()}
    frames, results = [], []
    transition = window.stack.transition
    def presented():
        if state["phase"] == "animation" and transition.clock.isValid(): frames.append(time.perf_counter())
    transition.frameSwapped.connect(presented)
    def complete(error=""):
        timer.stop()
        report = {"ok": not error, "error": error, "screen_refresh_hz": window.screen().refreshRate(), "window": [window.width(), window.height()], "dpr": window.devicePixelRatioF(), "results": results}
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        window.tray.exit()
    def step():
        try:
            if time.monotonic() - state["started"] > 30: raise TimeoutError("Animation benchmark timed out")
            if state["phase"] == "library" and window.tracks and not window.scanning and time.monotonic() - state["started"] > .7:
                state["pages"] = ["settings", "home", "queue", "home", "favourites", next(iter(window.sidebar_albums)), "home"]
                state["phase"] = "next"
            elif state["phase"] == "next":
                if state["index"] == len(state["pages"]): complete(); return
                frames.clear(); began = time.perf_counter()
                window.navigate(state["pages"][state["index"]])
                if not transition.isVisible(): raise RuntimeError("GPU transition unavailable")
                state["navigation_ms"] = (time.perf_counter() - began) * 1000
                state["phase"] = "animation"
            elif state["phase"] == "animation" and not transition.isVisible():
                intervals = sorted((b - a) * 1000 for a, b in zip(frames, frames[1:]))
                if not intervals: raise RuntimeError("No completed animation frames")
                median = statistics.median(intervals)
                results.append({"page": state["pages"][state["index"]].split(":", 1)[0], "frames": len(frames), "median_fps": round(1000 / median, 1), "median_interval_ms": round(median, 2), "p95_interval_ms": round(intervals[int((len(intervals) - 1) * .95)], 2), "max_interval_ms": round(max(intervals), 2), "navigation_ms": round(state["navigation_ms"], 2)})
                state["index"] += 1; state["phase"] = "next"
        except Exception as error: complete(str(error))
    timer.timeout.connect(step); timer.start()


def start_motion(window, output):
    """Measure the three reflow paths without GPU readback during animation."""
    import statistics
    from .widgets import AlbumRail
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    window.audio.setMuted(True)
    timer = QTimer(window); timer.setInterval(40)
    state = {"phase": "ready", "index": 0, "began": time.monotonic()}
    frames, results = [], []
    actions = ["albums_right", "albums_left", "lyrics_open", "lyrics_close",
               "maximize", "restore", "fullscreen", "windowed"]

    def presented():
        if state["phase"] == "running" and state["transition"].clock.isValid():
            frames.append(time.perf_counter())

    def complete(error=""):
        timer.stop()
        report = {"ok": not error, "error": error, "screen_refresh_hz": window.screen().refreshRate(),
                  "dpr": window.devicePixelRatioF(), "results": results, "phase": state["phase"],
                  "track_count": len(window.tracks), "scanning": window.scanning, "visible": window.isVisible()}
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        window.tray.exit()

    def tick():
        try:
            if time.monotonic() - state["began"] > (20 if state["phase"] == "ready" else 5): raise TimeoutError("Motion verification timed out")
            if state["phase"] == "ready":
                if window.scanning or not window.tracks or time.monotonic() - state["began"] < 1.2: return
                state["phase"] = "next"
            elif state["phase"] == "next":
                if state["index"] == len(actions): complete(); return
                action = actions[state["index"]]
                if action.startswith("albums"):
                    rail = window.library_scroll.findChildren(AlbumRail)[0]
                    assert rail.horizontalScrollBar().maximum() > 0, "Album fixture must overflow the rail"
                    transition = rail.transition
                    trigger = lambda: rail.scroll_page(1 if action.endswith("right") else -1)
                elif action.startswith("lyrics"):
                    transition = window.body.transition; trigger = window.show_lyrics
                else:
                    transition = window.stack.transition
                    trigger = {"maximize": window.showMaximized, "restore": window.showNormal,
                               "fullscreen": window.showFullScreen, "windowed": window.showNormal}[action]
                state.update(phase="running", transition=transition, began=time.monotonic())
                frames.clear(); transition.frameSwapped.connect(presented)
                began = time.perf_counter(); trigger(); state["setup_ms"] = (time.perf_counter() - began) * 1000
            elif state["phase"] == "running":
                transition = state["transition"]
                if transition.isVisible() or window.resize_timer.isActive() or time.monotonic() - state["began"] < .6: return
                transition.frameSwapped.disconnect(presented)
                intervals = sorted((b - a) * 1000 for a, b in zip(frames, frames[1:]))
                assert len(frames) >= max(8, int(window.screen().refreshRate() * .3 * .6)), "Animation did not present enough frames"
                assert not transition.clock.isValid() and transition.before.isNull() and transition.after.isNull()
                median = statistics.median(intervals)
                assert median < max(20, 2000 / (window.screen().refreshRate() or 60)), "Animation frame pacing is too slow"
                action = actions[state["index"]]
                results.append({"action": action, "frames": len(frames), "median_fps": round(1000 / median, 1),
                                "p95_ms": round(intervals[int((len(intervals) - 1) * .95)], 2),
                                "max_ms": round(max(intervals), 2), "setup_ms": round(state["setup_ms"], 2)})
                window.grab().save(str(output / (action + ".png")))
                state.update(phase="next", index=state["index"] + 1, began=time.monotonic())
        except Exception as error: complete(str(error) or type(error).__name__)
    timer.timeout.connect(tick); timer.start()


def start_audio(window, output, fixtures):
    """Exercise the shipped player with synthetic files in an isolated profile."""
    from hashlib import sha256
    from PySide6.QtMultimedia import QAudioBufferOutput, QMediaPlayer
    from .core import AUDIO_EXTENSIONS
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    fixtures = Path(fixtures).resolve()
    originals = {str(p): sha256(p.read_bytes()).hexdigest() for p in fixtures.iterdir() if p.suffix in AUDIO_EXTENSIONS}
    if not originals: raise ValueError('No audio fixtures')
    window.audio.setMuted(True)
    buffers = QAudioBufferOutput(window); window.media.setAudioBufferOutput(buffers)
    state = {'phase': 'import', 'started': time.monotonic(), 'index': 0, 'frames': 0, 'formats': set(), 'collect': False}
    results = []
    def decoded(buffer):
        if state['collect'] and buffer.isValid():
            state['frames'] += buffer.frameCount()
            fmt = buffer.format()
            state['formats'].add((fmt.sampleRate(), fmt.sampleFormat().name, fmt.channelCount()))
    buffers.audioBufferReceived.connect(decoded)
    timer = QTimer(window); timer.setInterval(75)
    def phase(name):
        state.update(phase=name, started=time.monotonic())
    def complete(error=''):
        timer.stop(); window.media.stop()
        preserved = all(Path(path).is_file() and sha256(Path(path).read_bytes()).hexdigest() == digest for path, digest in originals.items())
        report = {'ok': not error and preserved, 'error': error, 'original_files_unchanged': preserved,
                  'tested': len(results), 'results': results, 'native_dsd_tested': False}
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        window.tray.exit()
    def tick():
        try:
            current = state['phase']; elapsed = time.monotonic() - state['started']; media = window.media
            assert elapsed < 15, f"Audio timeout: {current}, {state.get('path', '')}"
            if current == 'import':
                if window.scanning: return
                window.import_audio_files([], fixtures); phase('imported')
            elif current == 'imported':
                if window.importing or window.scanning: return
                tracks = {track.path: track for track in window.tracks}
                assert set(originals) <= set(tracks), 'Imported formats missing: ' + str(set(originals) - set(tracks))
                state['tracks'] = [tracks[path] for path in sorted(originals)]
                phase('select')
            elif current == 'select':
                if elapsed < .2: return  # Drain the previous source's queued buffer signal.
                if state['index'] == len(state['tracks']): complete(); return
                track = state['tracks'][state['index']]
                state.update(frames=0, formats=set(), collect=True, path=track.path)
                window.play_tracks([track]); phase('playing')
            elif current == 'playing':
                assert media.error() == QMediaPlayer.Error.NoError, media.errorString()
                if state['frames'] == 0 or media.position() < 250: return
                assert media.duration() >= 3800 and media.isSeekable()
                track = state['tracks'][state['index']]
                assert window.current_path == track.path
                if track.is_dsd:
                    assert window.quality_button.isVisible() and 'DSD 解码为 PCM' in window.quality_button.toolTip()
                    if 'dsd-64.dsf' in track.path: window.grab().save(str(output / 'dsd-playing.png'))
                media.pause(); state['paused'] = media.position(); phase('paused')
            elif current == 'paused':
                if elapsed < .2: return
                assert media.playbackState() == QMediaPlayer.PlaybackState.PausedState
                assert abs(media.position() - state['paused']) < 100
                media.setPosition(2000); state['before_seek_frames'] = state['frames']; media.play(); phase('seek')
            elif current == 'seek':
                assert media.error() == QMediaPlayer.Error.NoError, media.errorString()
                if media.position() <= 2150 or state['frames'] <= state['before_seek_frames']: return
                track = state['tracks'][state['index']]
                state['result'] = {'file': Path(track.path).name, 'codec': track.codec, 'quality': track.quality,
                                   'duration_ms': media.duration(), 'seek_ms': media.position(),
                                   'decoded_frames': state['frames'], 'decoded_formats': sorted(state['formats']),
                                   'pause_resume_seek': True}
                media.setPosition(media.duration() - 200); phase('end')
            elif current == 'end':
                if media.mediaStatus() != QMediaPlayer.MediaStatus.EndOfMedia: return
                state['result']['end_of_media'] = True; results.append(state['result'])
                state['collect'] = False; window.clear_player(); state['index'] += 1; phase('select')
        except Exception as error:
            complete(f'{type(error).__name__}: {error}')
    timer.timeout.connect(tick); timer.start()
