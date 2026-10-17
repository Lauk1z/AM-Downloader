import pytest
from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from musicdesk.appearance import create_application
from musicdesk.core import Store
from musicdesk.window import MusicWindow


def wait(ms=30):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()


@pytest.fixture(scope="module")
def app(): return QApplication.instance() or create_application([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    root = tmp_path / "backend"; root.mkdir()
    value = MusicWindow(root, tmp_path / "profile")
    value.commands = []
    monkeypatch.setattr(value.client, "send", value.commands.append)
    monkeypatch.setattr(value, "scan", lambda: None)
    value.show(); value.enqueue(["https://music.apple.com/cn/song/1"], "alac"); wait()
    yield value
    value.tray.exit(); wait()


def prompt(window, **changes):
    event = {"event": "format_fallback", "job_id": window.active_job, "request_id": "format-1",
             "song_id": "1", "title": "测试歌曲", "artist": "测试艺人", "requested": "ALAC · 无损",
             "codec": "aac", "quality": "AAC · 约 256 kbps", "completed": 0, "total": 1}
    event.update(changes); window.backend_event(event); wait()
    return event


def test_confirm_continues_same_job_and_displays_actual_quality(window, tmp_path):
    original = dict(window.jobs[0]); event = prompt(window)
    dialog = window.format_dialog
    assert dialog.isVisible() and window.jobs[0]["state"] == "awaiting_format"
    assert window.queue_table.item(0, 2).text() == "等待确认下载格式"
    assert all(value in "\n".join(item.text() for item in dialog.findChildren(QLabel))
               for value in ("测试歌曲", "ALAC", "AAC", "256"))
    content = next(item for item in dialog.findChildren(QLabel) if "可用格式：" in item.text())
    assert content.height() >= content.heightForWidth(content.width())
    dialog.grab().save(str(tmp_path / "format-confirmation.png"))
    QTest.mouseClick(dialog.findChild(QPushButton, "confirmFormat"), Qt.MouseButton.LeftButton); wait()
    assert window.format_dialog is None
    assert window.commands[-1] == {"action": "format_response", "job_id": event["job_id"],
                                    "request_id": event["request_id"], "accepted": True}
    assert window.jobs[0]["id"] == original["id"] and window.jobs[0]["url"] == original["url"]
    window.backend_event({"event": "format_selected", "job_id": event["job_id"], "codec": "aac", "quality": event["quality"]})
    assert window.jobs[0]["codec"] == "alac" and window.jobs[0]["actual_codec"] == "aac"
    assert window.queue_table.item(0, 1).text() == event["quality"]
    window.backend_event({"event": "finished", "job_id": event["job_id"], "state": "DONE"})
    assert window.active_job is None and window.jobs[0]["state"] == "DONE"
    assert Store(window.store.directory).get("jobs")[0]["actual_codec"] == "aac"
    assert len([command for command in window.commands if command["action"] == "download"]) == 1


@pytest.mark.parametrize("method", ["cancel_button", "close_button", "escape"])
def test_cancel_close_and_escape_cancel_without_reentering_link(window, method):
    event = prompt(window); dialog = window.format_dialog
    if method == "cancel_button": dialog.findChild(QPushButton, "cancelFormat").click()
    elif method == "close_button": dialog.close()
    else: QTest.keyClick(dialog, Qt.Key.Key_Escape)
    wait()
    assert window.commands[-1]["accepted"] is False and window.format_dialog is None
    window.backend_event({"event": "finished", "job_id": event["job_id"], "state": "cancelled"})
    assert window.jobs[0]["state"] == "cancelled"
    window.job_action(event["job_id"])
    assert window.commands[-1]["action"] == "download"
    assert window.commands[-1]["codec"] == "alac"
    assert window.commands[-1]["url"] == "https://music.apple.com/cn/song/1"


@pytest.mark.parametrize("action", ["remove", "cancel", "disconnect", "finish", "exit"])
def test_external_cancellation_or_exit_dismisses_prompt_without_stale_answer(window, action):
    event = prompt(window)
    if action == "remove": window.remove_job(event["job_id"])
    elif action == "cancel": window.job_action(event["job_id"])
    elif action == "disconnect": window.backend_event({"event": "disconnected", "expected": False})
    elif action == "finish": window.backend_event({"event": "finished", "job_id": event["job_id"], "state": "FAILED"})
    else: window.tray.exit()
    wait()
    assert window.format_dialog is None
    assert not any(command["action"] == "format_response" for command in window.commands)


def test_duplicate_prompt_is_not_opened_twice_and_stale_jobs_are_ignored(window):
    event = prompt(window); first = window.format_dialog
    window.backend_event(event)
    assert window.format_dialog is first
    prompt(window, job_id="previous-job", request_id="old")
    assert window.format_dialog is first and len(window.commands) == 1


def test_untrusted_title_is_plain_text(window):
    prompt(window, title="<b>Song title</b>")
    content = next(item for item in window.format_dialog.findChildren(QLabel) if "<b>Song title</b>" in item.text())
    assert content.textFormat() == Qt.TextFormat.PlainText
