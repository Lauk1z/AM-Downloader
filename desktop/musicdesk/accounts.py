"""Successful login history; remembered secrets are protected for the Windows user."""
import base64
import ctypes as c
import os


def protected(data, decrypt=False):
    if os.name != "nt": raise OSError("记住密码需要 Windows 凭据保护支持。")
    class Blob(c.Structure):
        _fields_ = [("size", c.c_uint32), ("data", c.c_void_p)]
    crypt = c.WinDLL("crypt32", use_last_error=True)
    kernel = c.WinDLL("kernel32", use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [c.POINTER(Blob), c.c_void_p, c.c_void_p, c.c_void_p, c.c_void_p, c.c_uint32, c.POINTER(Blob)]
    function.restype = c.c_int
    kernel.LocalFree.argtypes = [c.c_void_p]; kernel.LocalFree.restype = c.c_void_p
    buffer = c.create_string_buffer(data)
    incoming, outgoing = Blob(len(data), c.cast(buffer, c.c_void_p)), Blob()
    try:
        # UI_FORBIDDEN, without LOCAL_MACHINE: bound to the current Windows user.
        if not function(c.byref(incoming), None, None, None, None, 1, c.byref(outgoing)):
            raise c.WinError(c.get_last_error())
        return c.string_at(outgoing.data, outgoing.size)
    finally:
        c.memset(buffer, 0, len(buffer))
        if outgoing.data:
            c.memset(outgoing.data, 0, outgoing.size); kernel.LocalFree(outgoing.data)


class Accounts:
    def __init__(self, store): self.store = store

    def history(self): return self.store.get("login_accounts", [])

    def entry(self, username):
        return next((item for item in self.history() if item["username"].casefold() == username.strip().casefold()), {})

    def password(self, username):
        secret = self.entry(username).get("secret")
        return protected(base64.b64decode(secret, validate=True), decrypt=True).decode("utf-8") if secret else ""

    def success(self, username, password, remember, automatic):
        secret = base64.b64encode(protected(password.encode("utf-8"))).decode("ascii") if remember else ""
        item = {"username": username.strip(), "secret": secret, "automatic": bool(automatic and remember)}
        others = [value for value in self.history() if value["username"].casefold() != item["username"].casefold()]
        self.store.set("login_accounts", [item] + others)

    def forget_password(self, username):
        self.update(username, secret="", automatic=False)

    def stop_automatic(self, username): self.update(username, automatic=False)

    def update(self, username, **values):
        items = [dict(item, **values) if item["username"].casefold() == username.strip().casefold() else item for item in self.history()]
        self.store.set("login_accounts", items)
