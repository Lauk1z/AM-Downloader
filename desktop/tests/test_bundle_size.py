import hashlib
import json
import lzma
from pathlib import PurePosixPath

import pytest

from build_backend import runtime_python_file
from musicdesk_backend import prepare_private_image


@pytest.fixture
def image_paths(tmp_path):
    runtime, state = tmp_path / "runtime", tmp_path / "state"
    for directory in (runtime, state): (directory / "assets").mkdir(parents=True)
    return runtime, state


def compressed_seed(runtime, data):
    archive = runtime / "assets/wrapper-manager.qcow2.xz"
    archive.write_bytes(lzma.compress(data))
    (runtime / "bundle.json").write_text(json.dumps({"pristine_image_sha256": hashlib.sha256(data).hexdigest()}))
    return archive


def test_first_restore_is_exact_and_later_start_preserves_account(image_paths):
    runtime, state = image_paths
    original = b"public image" * 1024
    archive = compressed_seed(runtime, original)
    image = prepare_private_image(runtime, state)
    assert image.read_bytes() == original
    assert not image.with_suffix(".partial").exists()
    image.write_bytes(b"private account state")
    archive.write_bytes(b"damaged unused seed")
    (runtime / "bundle.json").unlink()
    assert prepare_private_image(runtime, state).read_bytes() == b"private account state"


@pytest.mark.parametrize("damage", ["truncated", "invalid", "wrong_hash"])
def test_bad_seed_is_not_published_and_retry_recovers(image_paths, damage):
    runtime, state = image_paths
    archive = compressed_seed(runtime, b"public image")
    if damage == "truncated": archive.write_bytes(archive.read_bytes()[:-8])
    elif damage == "invalid": archive.write_bytes(b"not an archive")
    else: (runtime / "bundle.json").write_text(json.dumps({"pristine_image_sha256": "0" * 64}))
    with pytest.raises((EOFError, lzma.LZMAError, RuntimeError)):
        prepare_private_image(runtime, state)
    assert not (state / "assets/wrapper-manager.qcow2").exists()
    assert not (state / "assets/wrapper-manager.partial").exists()
    compressed_seed(runtime, b"correct replacement")
    assert prepare_private_image(runtime, state).read_bytes() == b"correct replacement"


def test_legacy_uncompressed_seed_still_starts(image_paths):
    runtime, state = image_paths
    (runtime / "assets/wrapper-manager.qcow2").write_bytes(b"legacy seed")
    assert prepare_private_image(runtime, state).read_bytes() == b"legacy seed"


@pytest.mark.parametrize("relative", [
    "python.exe", "python312.dll", "DLLs/_lzma.pyd", "DLLs/_ssl.pyd", "DLLs/sqlite3.dll",
    "Lib/site-packages/setuptools/_distutils/version.py", "Lib/site-packages/distutils-precedence.pth",
    "Lib/site-packages/grpc/_cython/cygrpc.pyd", "Lib/site-packages/google/protobuf/__init__.py",
    "Lib/site-packages/creart-0.4.0.dist-info/entry_points.txt", "Lib/site-packages/PIL/_imaging.pyd",
    "src/pywidevine/pywidevine/cdm.py", "LICENSE.txt",
])
def test_runtime_libraries_and_metadata_remain(relative):
    assert runtime_python_file(PurePosixPath(".venv/" + relative))


@pytest.mark.parametrize("relative", [
    "Doc/html/index.html", "include/Python.h", "libs/python312.lib", "Scripts/pip.exe",
    "Lib/ensurepip/_bundled/pip.whl", "Lib/idlelib/idle.py", "Lib/tkinter/__init__.py",
    "DLLs/_tkinter.pyd", "DLLs/tk86t.dll", "tcl/tk8.6/tk.tcl",
    "Lib/site-packages/virtualenv/__init__.py", "Lib/site-packages/virtualenv-20.0.dist-info/METADATA",
    "Lib/site-packages/poetry/core/__init__.py", "Lib/site-packages/grpc_tools/protoc.py",
    "Lib/site-packages/setuptools/tests/test_build.py",
])
def test_development_only_files_are_excluded(relative):
    assert not runtime_python_file(PurePosixPath(".venv/" + relative))
