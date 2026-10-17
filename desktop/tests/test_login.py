import os
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from musicdesk.appearance import create_application
from musicdesk.accounts import Accounts, protected
from musicdesk.core import Store
from musicdesk.login import LoginDialog
from musicdesk.window import MusicWindow


def wait(ms=30):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()


@pytest.fixture(scope="module")
def app(): return QApplication.instance() or create_application([])


@pytest.fixture
def login(app, tmp_path, monkeypatch):
    # GUI logic tests use a reversible stand-in; DPAPI has its own real test below.
    monkeypatch.setattr("musicdesk.accounts.protected", lambda value, decrypt=False: value[::-1])
    owner = QWidget(); owner.toast = lambda *_: None; owner.show()
    commands = []; accounts = Accounts(Store(tmp_path))
    dialog = LoginDialog(owner, accounts, commands.append); dialog.open(); wait()
    yield dialog, accounts, commands
    dialog.reject(); owner.close(); wait()


def begin(dialog, username="first@example.test", password="synthetic-password"):
    dialog.user.setEditText(username); dialog.password.setText(password); dialog.start_login()
    return dialog.request_id


def test_wrong_password_stays_open_retry_success_closes_and_saves(login):
    dialog, accounts, commands = login
    dialog.remember.setChecked(True); dialog.automatic.setChecked(True)
    request = begin(dialog)
    assert dialog.isVisible() and not dialog.submit.isEnabled()
    dialog.start_login(); assert len(commands) == 1
    dialog.handle({"event": "login", "request_id": request, "ok": False, "error": "密码错误"})
    assert dialog.isVisible() and dialog.submit.isEnabled() and dialog.user.currentText() == "first@example.test"
    assert dialog.status.text() == "密码错误" and not accounts.history()
    request2 = begin(dialog, password="correct-synthetic")
    dialog.handle({"event": "login", "request_id": request, "ok": True})
    assert dialog.isVisible()  # Stale responses cannot close the new attempt.
    dialog.handle({"event": "login", "request_id": request2, "ok": True})
    assert not dialog.isVisible() and accounts.password("first@example.test") == "correct-synthetic"
    assert "correct-synthetic" not in accounts.store.path.read_text()


def test_history_click_opens_and_only_fills_account(app, tmp_path, monkeypatch):
    monkeypatch.setattr("musicdesk.accounts.protected", lambda value, decrypt=False: value[::-1])
    accounts = Accounts(Store(tmp_path))
    accounts.success("older@example.test", "older-secret", True, False)
    accounts.success("latest@example.test", "latest-secret", True, True)
    parent = QWidget(); parent.show(); dialog = LoginDialog(parent, accounts, lambda *_: None); dialog.open(); wait()
    try:
        assert dialog.user.currentText() == "latest@example.test" and dialog.password.text() == "latest-secret"
        QTest.mouseClick(dialog.user.lineEdit(), Qt.MouseButton.LeftButton); wait()
        assert dialog.user.view().isVisible()
        index = dialog.user.model().index(1, 0)
        QTest.mouseClick(dialog.user.view().viewport(), Qt.MouseButton.LeftButton, pos=dialog.user.view().visualRect(index).center()); wait()
        assert dialog.user.currentText() == "older@example.test" and not dialog.password.text()
        assert accounts.password("older@example.test") == "older-secret"
        dialog.remember.setChecked(False)
        assert not accounts.password("older@example.test") and not accounts.entry("older@example.test")["automatic"]
        assert len(Accounts(Store(tmp_path)).history()) == 2
    finally: dialog.reject(); parent.close()


def test_first_account_2fa_visible_validation_retry_and_cancel(login):
    dialog, accounts, commands = login
    request = begin(dialog)
    dialog.handle({"event": "twofa", "request_id": request, "challenge_id": "one"}); wait()
    verify = dialog.verification
    assert verify.isVisible() and dialog.isVisible()
    verify.code.setText("12345"); verify.send_code(); assert len(commands) == 1
    verify.code.setText("123456"); verify.send_code()
    assert commands[-1] == {"action": "twofa", "request_id": request, "challenge_id": "one", "code": "123456"}
    assert verify.isVisible() and not verify.submit.isEnabled()
    dialog.handle({"event": "twofa", "request_id": request, "challenge_id": "two"}); wait()
    assert dialog.verification is verify and verify.isVisible() and verify.code.isEnabled()
    dialog.verification.reject()
    assert commands[-1] == {"action": "cancel_login", "request_id": request}
    dialog.handle({"event": "login", "request_id": request, "ok": False, "cancelled": True, "error": "已取消验证"})
    assert dialog.isVisible() and not dialog.pending and dialog.submit.isEnabled() and dialog.verification is None
    request = begin(dialog)
    dialog.handle({"event": "twofa", "request_id": request, "challenge_id": "three"})
    dialog.verification.code.setText("654321"); dialog.verification.send_code()
    dialog.handle({"event": "login", "request_id": request, "ok": True})
    assert not dialog.isVisible() and dialog.verification is None
    assert "654321" not in accounts.store.path.read_text()


@pytest.mark.parametrize("failure", ["验证码错误", "验证码已过期", "验证超时", "连接中断"])
def test_failed_code_keeps_same_window_until_confirmed_success(login, failure):
    dialog, accounts, commands = login
    dialog.remember.setChecked(True); dialog.automatic.setChecked(True)
    request = begin(dialog)
    dialog.handle({"event": "twofa", "request_id": request, "challenge_id": "old"})
    verify = dialog.verification
    verify.code.setText("111111"); verify.send_code()
    if failure == "连接中断": dialog.backend_failed(failure)
    else: dialog.handle({"event": "login", "request_id": request, "ok": False, "error": failure})
    wait()
    assert dialog.verification is verify and verify.isVisible() and dialog.isVisible()
    assert failure in verify.message.text() and not verify.code.text()
    assert verify.submit.isEnabled() and not verify.code.isEnabled() and not accounts.history()
    assert len(commands) == 2  # A failed code never triggers an automatic credential retry.
    verify.submit.click()
    retry = dialog.request_id
    assert retry and retry != request and commands[-1]["action"] == "login"
    assert commands[-1]["password"] == "synthetic-password" and "code" not in commands[-1]
    assert not verify.submit.isEnabled() and not verify.code.isEnabled()
    dialog.handle({"event": "login", "request_id": request, "ok": True})
    dialog.handle({"event": "twofa", "request_id": request, "challenge_id": "stale"})
    assert verify.isVisible() and not verify.code.isEnabled()
    dialog.handle({"event": "twofa", "request_id": retry, "challenge_id": "new"})
    assert dialog.verification is verify and verify.code.isEnabled() and not verify.code.text()
    verify.code.setText("654321"); verify.submit.click(); verify.send_code()
    assert commands[-1] == {"action": "twofa", "request_id": retry, "challenge_id": "new", "code": "654321"}
    assert len(commands) == 4 and verify.isVisible() and dialog.isVisible()
    dialog.handle({"event": "login", "request_id": retry, "ok": True})
    assert not dialog.isVisible() and dialog.verification is None
    assert accounts.password("first@example.test") == "synthetic-password"
    assert accounts.entry("first@example.test")["automatic"]
    assert "111111" not in accounts.store.path.read_text() and "654321" not in accounts.store.path.read_text()


def test_cancel_after_failed_verification_returns_to_account_form(login):
    dialog, accounts, commands = login
    request = begin(dialog)
    dialog.handle({"event": "twofa", "request_id": request, "challenge_id": "one"})
    dialog.handle({"event": "login", "request_id": request, "ok": False, "error": "验证码错误"})
    dialog.verification.reject()
    assert dialog.isVisible() and dialog.submit.isEnabled() and dialog.verification is None
    assert not dialog.pending and not dialog.request_id and not accounts.history()
    assert len(commands) == 1  # The failed stream has already ended.
    begin(dialog)
    assert len(commands) == 2 and commands[-1]["action"] == "login"


def test_disconnect_and_user_close_cancel_without_saving(login):
    dialog, accounts, commands = login
    request = begin(dialog)
    dialog.backend_failed("连接中断")
    assert dialog.isVisible() and dialog.submit.isEnabled() and "连接中断" in dialog.status.text()
    request = begin(dialog); dialog.reject()
    assert commands[-1] == {"action": "cancel_login", "request_id": request}
    assert not accounts.history() and not dialog.password.text()


def test_auto_login_only_without_session_once_and_with_opt_in(login, monkeypatch):
    dialog, accounts, commands = login
    accounts.success("last@example.test", "synthetic", True, True)
    launches = []
    def open_dialog():
        launches.append(True)
        owner.login_window = SimpleNamespace(password=SimpleNamespace(text=lambda: "synthetic"), start_login=lambda: commands.append("auto"))
    owner = SimpleNamespace(root="test", accounts=accounts, auto_login_attempted=False, closing=False, active_job=None, login_window=None, login_dialog=open_dialog)
    monkeypatch.setattr("musicdesk.window.is_managed", lambda _: True)
    MusicWindow.try_auto_login(owner, ["CN"]); assert not launches
    MusicWindow.try_auto_login(owner, []); MusicWindow.try_auto_login(owner, [])
    assert launches == [True] and commands == ["auto"]
    accounts.stop_automatic("last@example.test")
    owner.login_window = None; owner.auto_login_attempted = False
    MusicWindow.try_auto_login(owner, []); assert len(launches) == 1
    accounts.success("last@example.test", "synthetic", True, True)
    owner.auto_login_attempted = False
    monkeypatch.setattr("musicdesk.window.is_managed", lambda _: False)
    MusicWindow.try_auto_login(owner, []); assert len(launches) == 1


def test_new_login_defaults_to_automatic_but_respects_opt_out(login):
    dialog, accounts, commands = login
    assert dialog.remember.isChecked() and dialog.automatic.isChecked()
    request = begin(dialog)
    dialog.handle({"event": "login", "request_id": request, "ok": True})
    saved = Accounts(Store(accounts.store.directory))
    assert saved.history()[0]["automatic"] and saved.password("first@example.test") == "synthetic-password"
    reopened = LoginDialog(dialog.parent(), saved, commands.append); reopened.open()
    try:
        assert reopened.remember.isChecked() and reopened.automatic.isChecked()
        reopened.remember.setChecked(False)
        assert not reopened.automatic.isChecked() and not saved.password("first@example.test")
        reopened.user.setEditText("another@example.test"); reopened.account_edited()
        assert not reopened.password.text() and reopened.remember.isChecked() and reopened.automatic.isChecked()
    finally: reopened.reject()
    external = LoginDialog(dialog.parent(), saved, commands.append, managed=False)
    try: assert not external.automatic.isEnabled() and not external.automatic.isChecked()
    finally: external.reject()


@pytest.mark.parametrize("automatic", [True, False])
def test_successful_retry_keeps_users_automatic_login_choice(login, automatic):
    dialog, accounts, commands = login
    dialog.automatic.setChecked(automatic)
    request = begin(dialog)
    dialog.handle({"event": "login", "request_id": request, "ok": False, "error": "密码错误"})
    assert dialog.automatic.isChecked() == automatic
    request = begin(dialog, password="correct-synthetic")
    dialog.handle({"event": "login", "request_id": request, "ok": True})
    assert accounts.history()[0]["automatic"] == automatic


@pytest.fixture
def startup_window(app, tmp_path, monkeypatch):
    import shutil
    from pathlib import Path
    from musicdesk.client import BackendClient
    root = tmp_path / "backend"; root.mkdir()
    project = Path(__file__).resolve().parents[1]
    runtime = project / "vendor/backend" if (project / "vendor/backend").exists() else project.parent / "backend"
    shutil.copyfile(runtime / "config.example.toml", root / "config.toml")
    (root / ".am-backend").write_text("{}")
    monkeypatch.setattr("musicdesk.accounts.protected", lambda value, decrypt=False: value[::-1])
    monkeypatch.setattr(MusicWindow, "scan", lambda *_: None)
    commands, windows = [], []
    monkeypatch.setattr(BackendClient, "send", lambda self, command: commands.append(command))
    def create():
        window = MusicWindow(root, tmp_path / "profile"); windows.append(window); return window
    yield create, commands
    for window in windows: window.tray.exit()
    wait()


def test_restart_restores_session_without_password_history_or_login_prompt(startup_window):
    create, commands = startup_window
    for _ in range(2):
        window = create()
        assert not window.accounts.history()
        window.start_backend()
        window.backend_event({"event": "backend", "state": "ready", "regions": ["CN"]})
        assert window.backend_dot.text() == "●  已登录 · CN"
        assert "CN" in window.backend_dot.toolTip() and window.login_window is None
        window.tray.exit()
    assert commands == [{"action": "start"}, {"action": "start"}]


def test_restart_automatically_authenticates_last_success_only_once(startup_window):
    create, commands = startup_window
    first = create()
    first.accounts.success("older@example.test", "older-synthetic", True, True)
    first.login_dialog(); request = begin(first.login_window)
    first.backend_event({"event": "login", "request_id": request, "ok": True, "regions": ["CN"]})
    first.tray.exit(); commands.clear()
    second = create(); second.start_backend()
    ready = {"event": "backend", "state": "ready", "regions": []}
    second.backend_event(ready); second.backend_event(ready)
    assert len(commands) == 2 and commands[-1]["action"] == "login"
    assert commands[-1]["username"] == "first@example.test" and commands[-1]["password"] == "synthetic-password"
    assert "请在设置中登录" not in second.notice.text()
    dialog = second.login_window; request = dialog.request_id
    second.backend_event({"event": "twofa", "request_id": request, "challenge_id": "restart"})
    assert dialog.verification.isVisible()
    second.backend_event({"event": "login", "request_id": request, "ok": False, "error": "验证码错误"})
    assert dialog.verification.isVisible()
    second.backend_event(ready)
    assert len(commands) == 2  # No retry loop after a failed automatic attempt.


def test_backend_without_session_does_not_report_logged_in(startup_window):
    create, commands = startup_window
    window = create()
    window.backend_event({"event": "backend", "state": "ready", "regions": ["CN"]})
    window.backend_event({"event": "backend", "state": "ready", "regions": []})
    assert "未登录" in window.backend_dot.text() and "CN" not in window.backend_dot.toolTip()
    assert not commands and window.login_window is None


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_real_dpapi_roundtrip_and_no_plaintext_on_disk(tmp_path):
    secret = "test-only-password-测试-123!"
    encrypted = protected(secret.encode())
    assert secret.encode() not in encrypted and protected(encrypted, decrypt=True).decode() == secret
    accounts = Accounts(Store(tmp_path)); accounts.success("dpapi@example.test", secret, True, True)
    assert Accounts(Store(tmp_path)).password("dpapi@example.test") == secret
    assert secret not in accounts.store.path.read_text()
    accounts.forget_password("dpapi@example.test")
    assert not accounts.password("dpapi@example.test") and not accounts.history()[0]["automatic"]
