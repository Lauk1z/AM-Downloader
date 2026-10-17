import pytest
from PySide6.QtCore import QEventLoop, QPoint, QTimer, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QApplication, QMenu

from musicdesk.appearance import create_application
from musicdesk.core import Store
from musicdesk.window import MusicWindow


def wait(ms):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or create_application([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    root = tmp_path / "backend"; root.mkdir()
    value = MusicWindow(root, tmp_path / "profile")
    value.commands = []
    monkeypatch.setattr(value.client, "send", value.commands.append)
    value.show(); value.navigate("queue"); wait(400)
    yield value
    value.tray.exit(); wait(400)


def job(identifier, state):
    return {"id": identifier, "url": "https://music.apple.com/cn/song/" + identifier,
            "title": "测试歌曲 " + identifier, "codec": "alac", "state": state}


def context_event(table, point):
    return QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, table.viewport().mapToGlobal(point))


@pytest.mark.parametrize("state", ["queued", "FAILED", "cancelled", "DONE"])
def test_right_click_removes_clicked_job_and_persists_without_deleting_audio(window, monkeypatch, state):
    audio = window.root / "saved.m4a"; audio.write_bytes(b"existing local audio")
    window.jobs = [job("1", "queued"), job("2", state), job("3", "FAILED")]
    window.refresh_queue(); window.queue_table.selectRow(0)

    def choose_remove(menu, position):
        assert window.queue_table.currentRow() == 1
        assert [action.text() for action in menu.actions()] == ["从队列删除"]
        # A refresh can move rows while the popup is open; the chosen ID must stay stable.
        window.remove_job("1")
        menu.actions()[0].trigger()

    class TestMenu(QMenu):
        def exec(self, position): choose_remove(self, position)
    monkeypatch.setattr("musicdesk.window.QMenu", TestMenu)
    point = window.queue_table.visualItemRect(window.queue_table.item(1, 2)).center()
    QApplication.sendEvent(window.queue_table.viewport(), context_event(window.queue_table, point))
    assert [item["id"] for item in window.jobs] == ["3"]
    assert window.queue_table.rowCount() == 1 and window.queue_summary.text().startswith("1 个任务")
    assert not window.commands and audio.read_bytes() == b"existing local audio"
    assert [item["id"] for item in Store(window.store.directory).get("jobs")] == ["3"]
    restored = MusicWindow(window.root, window.store.directory)
    try:
        assert [item["id"] for item in restored.jobs] == ["3"]
    finally:
        restored.tray.exit(); wait(100)


def test_empty_queue_area_has_no_delete_menu_and_dismissal_keeps_job(window, monkeypatch):
    window.jobs = [job("1", "FAILED")]; window.refresh_queue(); opened = []
    class TestMenu(QMenu):
        def exec(self, position): opened.append(True)
    monkeypatch.setattr("musicdesk.window.QMenu", TestMenu)
    point = QPoint(10, window.queue_table.viewport().height() - 2)
    assert window.queue_table.rowAt(point.y()) == -1
    QApplication.sendEvent(window.queue_table.viewport(), context_event(window.queue_table, point))
    assert not opened
    point = window.queue_table.visualItemRect(window.queue_table.item(0, 0)).center()
    QApplication.sendEvent(window.queue_table.viewport(), context_event(window.queue_table, point))
    assert opened == [True] and window.jobs[0]["id"] == "1"


@pytest.mark.parametrize("paused", [False, True])
@pytest.mark.parametrize("result", ["cancelled", "DONE", "FAILED"])
def test_active_removal_waits_for_backend_and_ignores_late_events(window, paused, result):
    links = ["https://music.apple.com/cn/song/1", "https://music.apple.com/cn/song/2"]
    window.enqueue(links, "alac"); active = window.active_job
    next_id = window.jobs[1]["id"]; window.queue_paused = paused
    window.remove_job(active); window.remove_job(active); window.next_job()
    assert [command["action"] for command in window.commands] == ["download", "cancel"]
    assert window.active_job == active and [item["id"] for item in window.jobs] == [next_id]
    window.backend_event({"event": "stage", "job_id": active, "stage": "DOWNLOADING"})
    assert [item["id"] for item in window.jobs] == [next_id]
    window.backend_event({"event": "finished", "job_id": active, "state": result})
    assert window.active_job is None
    wait(450)
    if paused:
        assert len(window.commands) == 2 and window.jobs[0]["state"] == "queued"
        window.toggle_queue()
    assert window.active_job == next_id
    assert [command["action"] for command in window.commands] == ["download", "cancel", "download"]
    window.backend_event({"event": "finished", "job_id": active, "state": "DONE"})
    assert window.active_job == next_id and len(window.jobs) == 1
    assert [item["id"] for item in Store(window.store.directory).get("jobs")] == [next_id]


def test_backend_failure_releases_removed_active_job_without_restoring_it(window):
    window.enqueue(["https://music.apple.com/cn/song/1"], "alac")
    window.remove_job(window.active_job)
    window.backend_event({"event": "disconnected", "expected": False})
    assert window.active_job is None and window.queue_paused and not window.jobs
    assert Store(window.store.directory).get("jobs") == []
