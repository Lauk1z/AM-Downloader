"""Asynchronous login and verification dialogs; only confirmed success closes login."""
import uuid
from PySide6.QtCore import QEvent, QRegularExpression, QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QHBoxLayout, QLineEdit, QVBoxLayout
from .core import redact
from .widgets import button, label


class AccountField(QComboBox):
    def __init__(self, usernames):
        super().__init__()
        self.setEditable(True); self.addItems(usernames); self.setCompleter(None)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.lineEdit().setPlaceholderText("Apple 账号邮箱或手机号码")
        self.lineEdit().installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched is self.lineEdit() and event.type() == QEvent.Type.MouseButtonPress and self.count():
            QTimer.singleShot(0, self.showPopup)
        return super().eventFilter(watched, event)


class VerificationDialog(QDialog):
    submitted = Signal(str)
    retry_requested = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.challenge_id = ""; self.retry_needed = False
        self.setWindowTitle("Apple 账号双重认证"); self.setMinimumWidth(400)
        layout = QVBoxLayout(self); layout.setContentsMargins(26, 24, 26, 24); layout.setSpacing(16)
        layout.addWidget(label("输入验证码", 18, True))
        self.message = label("在受信任的 Apple 设备上允许登录，然后输入收到的六位验证码。", 11, color="#aaaab3")
        self.message.setWordWrap(True); layout.addWidget(self.message)
        self.code = QLineEdit(); self.code.setPlaceholderText("六位验证码"); self.code.setMaxLength(6)
        self.code.setValidator(QRegularExpressionValidator(QRegularExpression("[0-9]{0,6}"), self))
        self.code.setInputMethodHints(Qt.InputMethodHint.ImhDigitsOnly | Qt.InputMethodHint.ImhSensitiveData)
        layout.addWidget(self.code)
        actions = QHBoxLayout(); cancel = button("取消验证"); cancel.clicked.connect(self.reject)
        self.submit = button("验证", primary=True); self.submit.setEnabled(False)
        actions.addWidget(cancel); actions.addWidget(self.submit); layout.addLayout(actions)
        self.code.textChanged.connect(lambda text: self.submit.setEnabled(self.code.isEnabled() and len(text) == 6))
        self.submit.clicked.connect(self.send_code); self.code.returnPressed.connect(self.send_code)

    def waiting(self, message):
        self.challenge_id = ""; self.retry_needed = False
        self.code.clear(); self.code.setEnabled(False); self.submit.setEnabled(False)
        self.submit.setText("验证"); self.message.setText(message)

    def set_challenge(self, challenge_id, repeated):
        self.waiting("需要重新验证，请输入设备收到的有效六位验证码。" if repeated else
                     "在受信任的 Apple 设备上允许登录，然后输入收到的六位验证码。")
        self.challenge_id = challenge_id; self.code.setEnabled(True); self.code.setFocus()

    def show_error(self, message):
        self.waiting(message + "\n点击“重新验证”后，输入设备上收到的有效验证码。")
        self.retry_needed = True; self.submit.setText("重新验证"); self.submit.setEnabled(True)
        self.submit.setFocus()

    def send_code(self):
        if not self.submit.isEnabled(): return
        if self.retry_needed:
            self.retry_requested.emit(); return
        self.submitted.emit(self.code.text())


class LoginDialog(QDialog):
    def __init__(self, parent, accounts, send, managed=True):
        super().__init__(parent)
        self.accounts, self.send = accounts, send
        self.request_id = ""; self.verification = None; self.pending = None
        self.setWindowTitle("登录 Apple 账号"); self.setMinimumWidth(480)
        layout = QVBoxLayout(self); layout.setContentsMargins(28, 26, 28, 26); layout.setSpacing(14)
        layout.addWidget(label("连接你的 Apple Music 账号", 18, True))
        hint = label("通过本机内置服务登录，支持双重认证。" if managed else "通过已配置的 wrapper-manager 登录，支持双重认证。", 11, color="#aaaab3")
        hint.setWordWrap(True); layout.addWidget(hint)
        layout.addWidget(label("账号", 11))
        self.user = AccountField([item["username"] for item in accounts.history()]); layout.addWidget(self.user)
        layout.addWidget(label("密码", 11))
        self.password = QLineEdit(); self.password.setPlaceholderText("输入密码")
        self.password.setEchoMode(QLineEdit.EchoMode.Password); layout.addWidget(self.password)
        options = QHBoxLayout(); self.remember = QCheckBox("记住密码"); self.automatic = QCheckBox("自动登录")
        self.remember.setToolTip("登录成功后加密保存；取消勾选会清除当前账号已保存的密码。")
        self.automatic.setToolTip("下次启动恢复上次账号；已有登录状态时直接沿用，需要验证码时仍会提示。")
        self.automatic.setEnabled(managed)
        self.managed = managed
        options.addWidget(self.remember); options.addWidget(self.automatic); options.addStretch(); layout.addLayout(options)
        note = label("默认在登录成功后加密保存密码，供下次自动登录；可取消勾选。历史账号只填账号。" if managed else
                     "历史账号只填账号。勾选后，登录成功时保存设置；密码由 Windows 加密保护。", 10, color="#91919b")
        note.setWordWrap(True); layout.addWidget(note)
        self.status = label("", 11, color="#fa5774"); self.status.setWordWrap(True); layout.addWidget(self.status)
        actions = QHBoxLayout(); cancel = button("取消"); cancel.clicked.connect(self.reject)
        self.submit = button("登录", primary=True); actions.addWidget(cancel); actions.addWidget(self.submit); layout.addLayout(actions)
        self.load_options()
        try: self.password.setText(accounts.password(self.user.currentText()))
        except (OSError, ValueError, UnicodeError): self.status.setText("无法读取已保存的密码，请重新输入。")
        self.user.activated.connect(self.select_history)
        self.user.lineEdit().textEdited.connect(self.account_edited)
        self.remember.toggled.connect(self.remember_changed); self.automatic.toggled.connect(self.automatic_changed)
        self.submit.clicked.connect(self.start_login); self.password.returnPressed.connect(self.start_login)

    def load_options(self):
        entry = self.accounts.entry(self.user.currentText())
        default_auto = self.managed and not entry
        with QSignalBlocker(self.remember), QSignalBlocker(self.automatic):
            self.remember.setChecked(default_auto or bool(entry.get("secret")))
            self.automatic.setChecked(self.managed and (default_auto or bool(entry.get("automatic"))))

    def select_history(self, *_):
        self.password.clear(); self.load_options(); self.password.setFocus()

    def account_edited(self, *_): self.password.clear(); self.load_options()

    def remember_changed(self, checked):
        if not checked:
            self.automatic.setChecked(False); self.accounts.forget_password(self.user.currentText())

    def automatic_changed(self, checked):
        if checked: self.remember.setChecked(True)
        else: self.accounts.stop_automatic(self.user.currentText())

    def busy(self, active):
        for widget in (self.user, self.password, self.remember, self.automatic, self.submit): widget.setEnabled(not active)
        if not self.managed: self.automatic.setEnabled(False)
        self.submit.setText("正在登录…" if active else "登录")

    def start_login(self):
        if self.pending: return
        username, password = self.user.currentText().strip(), self.password.text()
        if not username or not password:
            self.status.setText("请输入账号和密码。"); return
        self.pending = (username, password, self.remember.isChecked(), self.automatic.isChecked())
        self.send_login()

    def send_login(self):
        self.request_id = uuid.uuid4().hex
        username, password = self.pending[:2]
        self.busy(True); self.status.setText("正在登录，请稍候…")
        self.send({"action": "login", "request_id": self.request_id, "username": username, "password": password})

    def retry_verification(self):
        if not self.pending or self.request_id or not self.verification: return
        self.verification.waiting("正在重新请求验证，请稍候…")
        self.send_login()

    def submit_verification(self, code):
        if self.request_id and self.verification and self.verification.challenge_id:
            challenge = self.verification.challenge_id
            self.verification.waiting("正在验证，请稍候…")
            self.send({"action": "twofa", "request_id": self.request_id, "challenge_id": challenge, "code": code})

    def close_verification(self):
        if self.verification:
            self.verification.blockSignals(True); self.verification.close(); self.verification.deleteLater(); self.verification = None

    def handle(self, event):
        if not self.pending or not self.request_id or event.get("request_id") != self.request_id: return
        if event["event"] == "twofa":
            repeated = self.verification is not None
            if not self.verification:
                self.verification = VerificationDialog(self)
                self.verification.submitted.connect(self.submit_verification)
                self.verification.retry_requested.connect(self.retry_verification)
                self.verification.rejected.connect(self.cancel_verification)
            dialog = self.verification
            self.status.setText("等待双重认证…")
            if not dialog.isVisible(): dialog.open()
            dialog.set_challenge(event["challenge_id"], repeated)
        elif event["event"] == "login":
            pending = self.pending; self.request_id = ""
            if event.get("ok"):
                self.pending = None; self.close_verification(); self.busy(False)
                try: self.accounts.success(*pending)
                except (OSError, ValueError): self.parent().toast("登录成功，但无法保存账号或密码。")
                self.password.clear(); self.accept()
            else:
                self.accounts.stop_automatic(pending[0])
                self.status.setText(redact(event.get("error")) if event.get("error") else "登录失败，请检查账号和密码后重试。")
                if self.verification:
                    self.verification.show_error(self.status.text()); return
                self.pending = None; self.busy(False)
                self.password.setFocus(); self.password.selectAll()

    def cancel_verification(self):
        if self.request_id:
            self.send({"action": "cancel_login", "request_id": self.request_id})
        self.pending = None; self.request_id = ""; self.close_verification(); self.busy(False)
        self.status.setText("已取消验证，可以重新登录。")

    def backend_failed(self, message):
        if self.pending: self.handle({"event": "login", "request_id": self.request_id, "ok": False, "error": redact(message)})

    def reject(self):
        if self.request_id: self.send({"action": "cancel_login", "request_id": self.request_id})
        self.pending = None; self.request_id = ""; self.password.clear(); self.close_verification()
        super().reject()
