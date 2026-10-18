"""Start the packaged public backend in a new, account-free test profile."""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    args = parser.parse_args()
    package, profile = args.package.resolve(), args.profile.resolve()
    if profile.exists():
        raise FileExistsError("Use a new test profile; never reuse a logged-in image")
    profile.mkdir(parents=True)
    bundle = package / "vendor/backend"
    python = bundle / ".venv/python.exe"
    environment = os.environ.copy()
    environment.update(PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
    environment["PATH"] = str(bundle / "deps") + os.pathsep + environment.get("PATH", "")
    initialize = (
        "import sys,json;sys.path.insert(0,sys.argv[1]);"
        "from musicdesk.runtime import prepare_backend;"
        "prepare_backend(sys.argv[2]);"
        "assert not any(x.startswith('PySide6') for x in sys.modules);print('initialized')")
    subprocess.run([str(python), "-c", initialize, str(package), str(profile)],
        check=True, env=environment, timeout=30)
    events, errors, received = queue.Queue(), [], []
    def launch():
        child = subprocess.Popen([str(python), "-u", str(package / "musicdesk_worker.py"),
            "--root", str(bundle), "--state-root", str(profile / "backend")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", env=environment, cwd=profile)
        threading.Thread(target=lambda: [events.put(json.loads(line)) for line in child.stdout], daemon=True).start()
        threading.Thread(target=lambda: errors.extend(child.stderr), daemon=True).start()
        return child

    process = launch()

    def send(action, **values):
        process.stdin.write(json.dumps(dict(action=action, **values)) + "\n")
        process.stdin.flush()

    def wait(predicate, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None and events.empty():
                raise RuntimeError("Backend exited: " + "".join(errors)[-2000:])
            try:
                event = events.get(timeout=1)
            except queue.Empty:
                continue
            received.append(event)
            if event["event"] in {"fatal", "error"}:
                raise RuntimeError(str(event))
            if event["event"] == "backend" or event["event"] == "log" and "秒" in event.get("text", ""):
                print(json.dumps(event, ensure_ascii=False), flush=True)
            if predicate(event):
                return event
        raise TimeoutError("Backend check timed out")

    started = time.monotonic()
    try:
        wait(lambda e: e["event"] == "hello", 60)
        send("start")
        ready = wait(lambda e: e["event"] == "backend" and e.get("state") == "ready", 210)
        cold_seconds = round(time.monotonic() - started, 2)
        if ready.get("regions"):
            raise AssertionError("Pristine public backend unexpectedly contains a logged-in account")
        log = profile / "diagnostic.txt"
        send("export", path=str(log)); wait(lambda e: e["event"] == "exported", 30)
        if not log.is_file():
            raise AssertionError("Backend did not export diagnostics")
        send("stop"); wait(lambda e: e["event"] == "stopped", 30)
        process.stdin.close()
        if process.wait(timeout=15) != 0:
            raise AssertionError("Backend did not exit cleanly")
        started = time.monotonic(); process = launch()
        wait(lambda e: e["event"] == "hello", 60); send("start")
        warm = wait(lambda e: e["event"] == "backend" and e.get("state") == "ready", 150)
        warm_seconds = round(time.monotonic() - started, 2)
        if warm.get("regions") or warm.get("boot_mode") != "direct":
            raise AssertionError("Warm launch did not use the account-free direct-boot cache")
        send("stop"); wait(lambda e: e["event"] == "stopped", 30); process.stdin.close()
        if process.wait(timeout=15) != 0:
            raise AssertionError("Warm backend did not exit cleanly")
        result = {"ok": True, "cold_start_seconds": cold_seconds, "warm_start_seconds": warm_seconds,
            "checks": ["packaged imports without Qt", "hello protocol", "private pristine image", "backend ready without account", "log export", "direct-boot warm restart", "graceful shutdown"], "events": received}
        (profile / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in result.items() if k != "events"}, ensure_ascii=False), flush=True)
    finally:
        if process.poll() is None:
            try:
                send("stop"); process.stdin.close(); process.wait(timeout=25)
            except (OSError, subprocess.TimeoutExpired):
                process.kill(); process.wait(timeout=10)


if __name__ == "__main__":
    main()
