"""Locate bundled code and keep each user's mutable backend data outside it."""
import json
from pathlib import Path
import shutil
import sys

import tomlkit


def bundled_backend():
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent / "vendor"
    root = base / "backend"
    return root if (root / "bundle.json").is_file() else None


def is_managed(root):
    return (Path(root) / ".am-backend").is_file()


def code_root(root):
    if is_managed(root):
        bundle = bundled_backend()
        if bundle is None: raise FileNotFoundError("内置下载组件缺失，请完整解压软件后重试。")
        return bundle
    return Path(root)


def prepare_backend(data_dir, bundle=None):
    bundle = Path(bundle) if bundle else bundled_backend()
    if bundle is None: raise FileNotFoundError("内置下载组件缺失。")
    state = Path(data_dir) / "backend"
    assets = state / "assets"; assets.mkdir(parents=True, exist_ok=True)
    # These catalog resources are public upstream files, never account images.
    for name in ("device.wvd", "storefronts.json", "storefront_ids.json"):
        source, target = bundle / "assets" / name, assets / name
        if not target.is_file() or target.read_bytes() != source.read_bytes(): shutil.copy2(source, target)
    config = state / "config.toml"
    if not config.exists():
        document = tomlkit.parse((bundle / "config.example.toml").read_text(encoding="utf-8-sig"))
        document["localInstance"]["enable"] = True
        document["localInstance"]["enableHardwareAcceleration"] = False
        document["localInstance"]["showWindow"] = False
        document["region"]["language"] = "zh-Hans-CN"
        document["download"]["failedSongNotPassIntegrityCheck"] = True
        config.write_text(tomlkit.dumps(document), encoding="utf-8")
    (state / ".am-backend").write_text(json.dumps({"format": 1}), encoding="utf-8")
    return state
