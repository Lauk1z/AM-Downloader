"""JSON-lines adapter for bundled or explicitly selected AppleMusicDecrypt code."""
import argparse
import asyncio
import inspect
import json
import os
import re
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import uuid

PROTOCOL = sys.stdout
LOCK = threading.Lock()

FORMAT_PRIORITY = ("alac", "ec3", "ac3", "aac", "aac-binaural", "aac-downmix")
FORMAT_NAMES = {"alac": "ALAC · 无损", "ec3": "Dolby Atmos", "ac3": "Dolby Digital",
                "aac": "AAC", "aac-binaural": "AAC · 空间音频", "aac-downmix": "AAC · 混音",
                "aac-legacy": "AAC · 兼容格式"}


def available_formats(manifest, max_depth, max_rate):
    from src.utils import get_codec_from_codec_id
    result = {}
    for media in manifest.playlists:
        codec = get_codec_from_codec_id(media.stream_info.audio or "")
        if codec not in FORMAT_PRIORITY or not media.media: continue
        bandwidth = media.stream_info.average_bandwidth or media.stream_info.bandwidth or 0
        depth = rate = 0
        name = FORMAT_NAMES[codec]
        if codec == "alac":
            depth = int(media.media[0].extras["bit_depth"])
            rate = int(media.media[0].extras["sample_rate"])
            if depth > max_depth or rate > max_rate: continue
            name += f" · {depth} bit / {rate / 1000:g} kHz"
        elif bandwidth:
            name += f" · 约 {bandwidth / 1000:.0f} kbps"
        rank = (depth, rate, bandwidth)
        if codec not in result or rank > result[codec]["rank"]:
            result[codec] = {"codec": codec, "label": name, "rank": rank, "media": media}
    return result


def send(event, **data):
    with LOCK:
        PROTOCOL.write(json.dumps({"event": event, **data}, ensure_ascii=False, default=str) + "\n")
        PROTOCOL.flush()


def listening(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


async def login_stream(manager, username, password, get_code):
    from src.grpc.manager_pb2 import LoginRequest, LoginData
    async with manager._login_lock:
        requests = asyncio.Queue()
        async def request_stream():
            while (item := await requests.get()) is not None: yield item
        stream = manager._stub.Login(request_stream())
        try:
            await requests.put(LoginRequest(data=LoginData(username=username, password=password)))
            async for reply in stream:
                if reply.header.code == 0: return
                if reply.header.code != 2:
                    raise RuntimeError(reply.header.msg or "账号或密码不正确，请重试。")
                code = await get_code()
                await requests.put(LoginRequest(data=LoginData(username=username, password=password, two_step_code=code)))
            raise RuntimeError("登录连接已中断，尚未确认登录成功，请重试。")
        finally:
            await requests.put(None)
            stream.cancel()


class Bridge:
    def __init__(self, root, state=None):
        self.root = Path(root)
        self.state = Path(state) if state else self.root
        self.managed = state is not None
        self.job = None
        self.job_id = ""
        self.ready = False
        self.owns_vm = False
        self.vm = None
        self.login_task = None
        self.start_task = None
        self.search_task = None
        self.background = set()
        self.twofa = None
        self.login_request_id = ""
        self.challenge_id = ""
        self.start_lock = asyncio.Lock()
        self.last_tasks = {}
        self.completed = 0
        self.total = 0
        self.prefetch = None
        self.format_future = None
        self.format_request_id = ""

    def bootstrap(self):
        # Use the installation's own creators and dependencies, never its shell parser.
        import main as installed
        installed.loop.close()
        from creart import it
        from src.config import Config
        from src.api import WebAPI
        from src.grpc.manager import WrapperManager
        from src.rip import Ripper
        from src.qemu import QemuInstance
        from src.task import Task
        from src.logger import RipLogger, GlobalLogger
        from src.measurer import Measurer
        import src.rip as rip_module
        from loguru import logger
        self.it, self.config = it, it(Config)
        self.config.download.failedSongNotPassIntegrityCheck = True
        # The desktop asks before substituting a different audio format.
        self.config.download.codecAlternative = False
        self.api, self.wm, self.ripper = it(WebAPI), it(WrapperManager), Ripper()
        self.ripper.select_audio = self.select_audio
        self.measurer = it(Measurer)
        self.vm = QemuInstance()
        if self.managed:
            from musicdesk_backend import BundledInstance
            self.vm = BundledInstance(self.root, self.state, self.config)
            self.config.localInstance.enable = True
        # The CLI helper reads exception() on cancelled tasks during shutdown.
        # Track only this process's callbacks and handle normal cancellation.
        import src.grpc.manager as manager_module
        def background_task(coro):
            task = asyncio.create_task(coro)
            self.background.add(task)
            def done(value):
                self.background.discard(value)
                if not value.cancelled() and value.exception():
                    send("log", text=str(value.exception()))
            task.add_done_callback(done)
            return task
        manager_module.safely_create_task = background_task
        logger.remove()
        it(GlobalLogger).logger.remove()
        it(GlobalLogger).logger.add(lambda message: send("log", text=str(message).strip()), format="{message}", diagnose=False)
        def logger_init(log, kind, identifier):
            log.song_id = str(identifier)
            log.logger = logger.bind(song_id=str(identifier))
        def fullname(log, artist, name=None):
            send("track", job_id=self.job_id, song_id=log.song_id, title=name or artist, artist=artist)
        RipLogger.__init__ = logger_init
        RipLogger.set_fullname = fullname
        logger.add(lambda message: send("log", job_id=self.job_id, text=message.record["message"]), format="{message}", diagnose=False)
        original_update = Task.update_status
        def update(task, status):
            original_update(task, status)
            self.last_tasks[task.adamId] = task
            metadata = task.metadata
            send("stage", job_id=self.job_id, song_id=task.adamId, stage=str(status), title=getattr(metadata, "title", task.adamId), artist=getattr(metadata, "artist", ""), completed=self.completed, total=self.total, error=str(task.error) if task.error else "")
        Task.update_status = update
        original_save = rip_module.save
        def save(*args, **kwargs):
            path = original_save(*args, **kwargs)
            send("saved", job_id=self.job_id, path=str(path))
            return path
        rip_module.save = save

    async def confirm_format(self, task, requested, candidate):
        self.format_request_id = uuid.uuid4().hex
        self.format_future = asyncio.get_running_loop().create_future()
        try:
            send("format_fallback", job_id=self.job_id, request_id=self.format_request_id,
                 song_id=task.adamId, title=task.metadata.title, artist=task.metadata.artist,
                 requested=FORMAT_NAMES.get(requested, requested), codec=candidate["codec"],
                 quality=candidate["label"], completed=self.completed, total=self.total)
            if not await self.format_future:
                raise asyncio.CancelledError()
        finally:
            self.format_future = None
            self.format_request_id = ""

    def format_response(self, command):
        if (command.get("job_id") == self.job_id and command.get("request_id") == self.format_request_id
                and self.format_future is not None and not self.format_future.done()):
            self.format_future.set_result(command.get("accepted") is True)

    async def select_audio(self, task, requested, raw_metadata, m3u8_url):
        import m3u8
        from src.legacy.mp4 import extract_media as legacy_extract_media
        if requested == "aac-legacy":
            candidate = {"codec": requested, "label": FORMAT_NAMES[requested]}
        else:
            formats = {}
            if not m3u8_url:
                m3u8_url = getattr(raw_metadata.attributes.extendedAssetUrls, "enhancedHls", None)
            if m3u8_url:
                task.audio_manifest = m3u8.loads(await self.api.download_m3u8(m3u8_url), uri=m3u8_url)
                formats = available_formats(task.audio_manifest, self.config.download.maxBitDepth,
                                            self.config.download.maxSampleRate)
            candidate = formats.get(requested)
            if candidate is None:
                candidate = next((formats[codec] for codec in FORMAT_PRIORITY if codec in formats), None)
                if candidate is None:
                    # Verify the full legacy asset exists before offering it; never use previews.
                    legacy_url = await self.wm.webPlayback(task.adamId)
                    if not legacy_url:
                        raise RuntimeError("这首歌没有可下载的音频格式。")
                    task.legacy_media = await legacy_extract_media(legacy_url)
                    if not task.legacy_media.uri or not task.legacy_media.keys or not all(task.legacy_media.keys):
                        raise RuntimeError("这首歌没有可下载的音频格式。")
                    candidate = {"codec": "aac-legacy", "label": FORMAT_NAMES["aac-legacy"]}
                await self.confirm_format(task, requested, candidate)
            task.selected_media = candidate.get("media")
        send("format_selected", job_id=self.job_id, song_id=task.adamId,
             codec=candidate["codec"], quality=candidate["label"])
        return candidate["codec"], m3u8_url

    async def start(self):
        async with self.start_lock:
            try:
                await self.start_backend()
            except BaseException:
                if self.managed and self.owns_vm:
                    await self.vm.terminate(); self.owns_vm = False
                raise

    async def start_backend(self):
        if self.ready:
            return
        started = time.perf_counter()
        send("backend", state="starting", message="正在启动下载后端…")
        if self.managed:
            self.owns_vm = True
            send("backend", state="starting", message="正在启动内置登录服务…")
            initialization = asyncio.create_task(self.initialize_api())
            try:
                await self.vm.launch_instance(asyncio.get_running_loop())
                await initialization
            finally:
                if not initialization.done(): initialization.cancel()
                await asyncio.gather(initialization, return_exceptions=True)
            if self.vm.acceleration_fallback: send("log", text="硬件加速启动失败，已使用兼容模式启动。")
            cache = getattr(self.vm, "boot_cache", None)
            if cache and cache.note: send("log", text=cache.note)
            endpoint = f"127.0.0.1:{self.vm.port}"
            await self.wm.init(endpoint, False)
            self.config.instance.url, self.config.instance.secure = endpoint, False
            await asyncio.wait_for(self.wm._channel.channel_ready(), 120)
        elif self.config.localInstance.enable:
            await self.initialize_api()
            if not listening(32767):
                if listening(32766):
                    raise RuntimeError("本地 QEMU 已在运行但服务尚未就绪，请等待原程序启动完成。")
                self.owns_vm = True
                await asyncio.wait_for(self.vm.launch_instance(asyncio.get_running_loop()), 150)
            await self.wm.init("127.0.0.1:32767", False)
            self.config.instance.url = "127.0.0.1:32767"
            self.config.instance.secure = False
        else:
            await self.initialize_api()
            await self.wm.init(self.config.instance.url, self.config.instance.secure)
        async def wait_ready():
            while True:
                self.wm.status.cache_invalidate()
                status = await self.wm.status()
                if status.ready:
                    return status
                await asyncio.sleep(1)
        status = await asyncio.wait_for(wait_ready(), 120)
        self.decrypt_task = asyncio.create_task(self.wm.decrypt_init(self.ripper.on_decrypt_success, self.ripper.on_decrypt_failed))
        self.ready = True
        self.regions = list(status.regions)
        elapsed = round(time.perf_counter() - started, 2)
        accelerator = self.vm.accelerator if self.managed else "configured"
        send("backend", state="ready", regions=list(status.regions), startup_seconds=elapsed, accelerator=accelerator,
             boot_mode=getattr(self.vm, "boot_mode", "configured"),
             message=("下载后端已就绪" if status.regions else "后端已就绪，请登录 Apple 账号") + f"（{elapsed:g} 秒）")

    async def initialize_api(self):
        if inspect.iscoroutinefunction(self.api.init): await self.api.init()
        else: await asyncio.to_thread(self.api.init)

    async def prefetch_metadata(self, song, language):
        try:
            metadata = await self.api.get_song_info(song.id, song.storefront, language)
            await self.api.get_album_info(metadata.relationships.albums.data[0].id, song.storefront, language)
        except Exception:
            # Speculative failure is retried and reported by the actual song task.
            pass

    async def expand(self, raw, language):
        from src.url import AppleMusicURL, Song, URLType
        url = AppleMusicURL.parse_url(raw)
        if url is None:
            url = AppleMusicURL.parse_url(await self.api.get_real_url(raw))
        if url is None:
            raise ValueError("无法识别 Apple Music 链接")
        if url.type == URLType.Song:
            return [(url, None)]
        if url.type == URLType.Album:
            album = await self.api.get_album_info(url.id, url.storefront, language)
            return [(Song(id=item.id, storefront=url.storefront, url="", type=URLType.Song), None) for item in album.data[0].relationships.tracks.data]
        if url.type == URLType.Playlist:
            from src.utils import playlist_write_song_index
            playlist = playlist_write_song_index(await self.api.get_playlist_info_and_tracks(url.id, url.storefront, language))
            return [(Song(id=item.id, storefront=url.storefront, url="", type=URLType.Song), playlist) for item in playlist.data[0].relationships.tracks.data]
        if url.type == URLType.Artist:
            albums = await self.api.get_albums_from_artist(url.id, url.storefront, language)
            result = []
            for album in albums:
                result.extend(await self.expand(album, language))
            return list({song.id: (song, playlist) for song, playlist in result}.values())
        raise ValueError("不支持的链接类型")

    async def download(self, command):
        from src.flags import Flags
        self.job_id = command["id"]
        self.completed, self.total = 0, 0
        failures = []
        try:
            await self.start()
            if self.managed:
                if not self.regions: raise RuntimeError("请先在设置中登录 Apple 账号，再下载歌曲。")
                output = str(Path(command["output_dir"]).resolve()).replace("{", "{{").replace("}", "}}")
                self.config.download.dirPathFormat = output + "/{album_artist}/{album}"
                self.config.download.playlistDirPathFormat = output + "/playlists/{playlistName}"
            send("stage", job_id=self.job_id, stage="resolving")
            language = command.get("language") or self.config.region.language
            songs = await self.expand(command["url"], language)
            self.total = len(songs)
            if not songs:
                raise RuntimeError("该链接未返回可下载的歌曲。")
            for index, (song, playlist) in enumerate(songs):
                if self.prefetch:
                    await self.prefetch; self.prefetch = None
                if self.managed and index + 1 < len(songs):
                    self.prefetch = asyncio.create_task(self.prefetch_metadata(songs[index + 1][0], language))
                send("stage", job_id=self.job_id, stage="WAITING", song_id=song.id, completed=self.completed, total=self.total)
                await self.ripper.rip_song(song, command.get("codec", "alac"), Flags(force_save=False, language=language), playlist=playlist)
                track = self.last_tasks.pop(song.id, None)
                if track is None or str(track.status) != "DONE":
                    failures.append(f"{song.id}: {getattr(track, 'error', None) or '下载失败'}")
                self.completed += 1
            send("finished", job_id=self.job_id, state="FAILED" if failures else "DONE", completed=self.completed, total=self.total, error="\n".join(failures))
        except asyncio.CancelledError:
            send("finished", job_id=self.job_id, state="cancelled", completed=self.completed, total=self.total)
        except Exception as error:
            send("finished", job_id=self.job_id, state="FAILED", error=str(error))
        finally:
            if self.prefetch:
                self.prefetch.cancel()
                await asyncio.gather(self.prefetch, return_exceptions=True)
                self.prefetch = None
            self.last_tasks.clear()
            self.job_id = ""

    async def start_requested(self):
        try:
            await self.start()
        except Exception as error:
            send("backend", state="error", message=str(error))

    async def search(self, command):
        serial = command.get("serial")
        try:
            country = command.get("country", "CN").lower()
            if not re.fullmatch(r"[a-z]{2}", country): raise ValueError("无效的曲库地区")
            response = await asyncio.wait_for(self.api._request("GET", f"https://amp-api.music.apple.com/v1/catalog/{country}/search", params={"term": str(command["term"])[:200], "types": "songs", "limit": 25, "l": "zh-Hans-CN"}), 40)
            response.raise_for_status()
            results = []
            for item in response.json().get("results", {}).get("songs", {}).get("data", []):
                data = item["attributes"]
                artwork = data.get("artwork", {}).get("url", "").replace("{w}", "400").replace("{h}", "400")
                results.append({"trackId": item["id"], "trackName": data["name"], "artistName": data["artistName"], "collectionName": data.get("albumName", ""), "artworkUrl100": artwork, "trackViewUrl": data.get("url", f"https://music.apple.com/{country}/song/{item['id']}")})
            send("catalog", serial=serial, results=results)
        except asyncio.CancelledError:
            pass
        except Exception as error:
            send("catalog", serial=serial, results=[], error=str(error) or "搜索请求超时")

    async def login(self, command):
        request_id = command.get("request_id", "")
        username, password = command.pop("username"), command.pop("password")
        secrets = [username, password]
        self.login_request_id = request_id
        try:
            await self.start()
            async def get_code(*_):
                self.twofa = asyncio.get_running_loop().create_future()
                self.challenge_id = uuid.uuid4().hex
                send("twofa", request_id=request_id, challenge_id=self.challenge_id)
                try:
                    code = await asyncio.wait_for(self.twofa, 180)
                    secrets.append(code); return code
                finally: self.twofa = None; self.challenge_id = ""
            async with asyncio.timeout(300):
                await login_stream(self.wm, username, password, get_code)
            self.wm.status.cache_invalidate()
            status = await asyncio.wait_for(self.wm.status(), 15)
            self.regions = list(status.regions)
            send("login", request_id=request_id, ok=True, regions=list(status.regions))
        except asyncio.CancelledError:
            send("login", request_id=request_id, ok=False, cancelled=True, error="已取消登录或验证，可以重新登录。")
        except asyncio.TimeoutError:
            send("login", request_id=request_id, ok=False, error="登录或验证码等待超时，请重新登录。")
        except Exception as error:
            message = str(error) or "登录失败，请检查账号、密码或网络后重试。"
            for secret in secrets:
                if secret: message = message.replace(secret, "[已隐藏]")
            send("login", request_id=request_id, ok=False, error=message)
        finally:
            if self.twofa and not self.twofa.done(): self.twofa.cancel()
            self.twofa = None; self.challenge_id = ""; self.login_request_id = ""
            secrets.clear(); password = ""

    def login_action(self, command):
        action = command["action"]
        if action == "login":
            if self.login_task and not self.login_task.done():
                send("login", request_id=command.get("request_id", ""), ok=False, error="账号登录仍在进行中，请稍候。")
            else:
                self.login_request_id = command.get("request_id", "")
                self.login_task = asyncio.create_task(self.login(command))
                def cancelled_before_start(task):
                    if task.cancelled() and self.login_task is task:
                        send("login", request_id=self.login_request_id, ok=False, cancelled=True, error="已取消登录，可以重新登录。")
                        self.login_request_id = ""
                self.login_task.add_done_callback(cancelled_before_start)
        elif command.get("request_id") == self.login_request_id:
            if action == "cancel_login" and self.login_task: self.login_task.cancel()
            elif action == "twofa" and self.twofa and not self.twofa.done() and command.get("challenge_id") == self.challenge_id:
                code = str(command.get("code", ""))
                if re.fullmatch(r"[0-9]{6}", code): self.twofa.set_result(code)

    async def export(self, target):
        try:
            if not self.owns_vm:
                raise RuntimeError("当前连接到已运行的后端。请先关闭原命令行程序，再从本界面启动后端以导出日志。")
            text = await asyncio.wait_for(self.vm.logs(), 20)
            text = re.sub(r"https?://\S+", "[URL hidden]", text)
            text = re.sub(r"(?i)(music-token|authorization|password|cookie)([\s:=\"']+)[^\s,\"']+", r"\1\2[hidden]", text)
            text = re.sub(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}", "[account hidden]", text)
            Path(target).write_text(text, encoding="utf-8")
            send("exported", path=target)
        except Exception as error:
            send("error", message=str(error))

    async def tick(self):
        while True:
            if self.ready:
                send("speed", download=self.measurer.download_speed(), decrypt=self.measurer.decrypt_speed())
            await asyncio.sleep(1)

    async def run(self):
        self.bootstrap()
        send("hello")
        ticker = asyncio.create_task(self.tick())
        try:
            while line := await asyncio.to_thread(sys.stdin.readline):
                try:
                    command = json.loads(line)
                    action = command.get("action")
                    if action == "download":
                        if self.job and not self.job.done():
                            raise RuntimeError("已有任务正在运行")
                        self.job = asyncio.create_task(self.download(command))
                    elif action == "cancel":
                        if self.job:
                            self.job.cancel()
                    elif action == "format_response": self.format_response(command)
                    elif action == "start":
                        if not self.start_task or self.start_task.done():
                            self.start_task = asyncio.create_task(self.start_requested())
                    elif action in {"login", "twofa", "cancel_login"}: self.login_action(command)
                    elif action == "search":
                        if self.search_task and not self.search_task.done(): self.search_task.cancel()
                        self.search_task = asyncio.create_task(self.search(command))
                    elif action == "export":
                        await self.export(command["path"])
                    elif action == "stop":
                        break
                except Exception as error:
                    send("error", message=str(error))
        finally:
            ticker.cancel()
            if self.job and not self.job.done():
                self.job.cancel()
                await self.job
            if self.login_task and not self.login_task.done():
                self.login_task.cancel()
                await asyncio.gather(self.login_task, return_exceptions=True)
            if self.start_task and not self.start_task.done():
                self.start_task.cancel()
                await asyncio.gather(self.start_task, return_exceptions=True)
            if self.search_task and not self.search_task.done(): self.search_task.cancel()
            if hasattr(self, "decrypt_task"): self.decrypt_task.cancel()
            for task in list(self.background): task.cancel()
            await asyncio.gather(*self.background, return_exceptions=True)
            if self.owns_vm:
                try:
                    await asyncio.wait_for(self.vm.terminate(), 15)
                except Exception as error:
                    send("log", text=f"关闭本地后端: {error}")
            if hasattr(self.api, "aclose"): await self.api.aclose()
            else: await self.api.client.aclose()
            if hasattr(self.wm, "_channel"): await self.wm._channel.close()
            send("stopped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--state-root")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    sys.path.insert(0, str(root))
    state = Path(args.state_root).resolve() if args.state_root else None
    os.chdir(state or root)
    os.environ["PATH"] = str(root / "deps") + os.pathsep + os.environ.get("PATH", "")
    sys.stdout = sys.stderr
    if os.name == "nt":
        original_popen = subprocess.Popen
        class HiddenPopen(original_popen):
            def __init__(self, *args, **kwargs):
                kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
                super().__init__(*args, **kwargs)
        subprocess.Popen = HiddenPopen
    try:
        if state and os.name == "nt":
            from musicdesk_backend import protect_process_tree
            process_job = protect_process_tree()
        asyncio.run(Bridge(root, state).run())
    except Exception as error:
        send("fatal", message=str(error))
