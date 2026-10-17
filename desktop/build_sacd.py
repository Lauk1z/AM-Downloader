"""Stage the pinned upstream SACD executable and verify its source archive."""
import hashlib
import json
from pathlib import Path
import urllib.request


def build():
    root = Path(__file__).resolve().parent
    metadata = json.loads((root / "native/sacd-upstream.json").read_text())
    source = root / "native/sacd-source.zip"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == metadata["source_sha256"]
    binary = root / "native/bin/sacd_extract.exe"
    if not binary.exists():
        url = metadata["repository"] + "/releases/download/" + metadata["tag"] + "/sacd_extract.exe"
        with urllib.request.urlopen(url, timeout=60) as response: data = response.read()
        if hashlib.sha256(data).hexdigest() != metadata["sha256"]: raise ValueError("SACD component checksum mismatch")
        binary.parent.mkdir(parents=True, exist_ok=True); binary.write_bytes(data)
    if hashlib.sha256(binary.read_bytes()).hexdigest() != metadata["sha256"]: raise ValueError("SACD component checksum mismatch")
    return binary


if __name__ == "__main__": print(build())
