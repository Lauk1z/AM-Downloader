"""Small, checked patches to the pinned upstream Windows media commands."""
PATCH_VERSION = 5


ALAC_TERMINATION_PATCH = '''def normalize_alac_termination(song_info: SongInfo, media: bytes) -> bytes:
    # Some ALAC escape frames have a zeroed ID_END. Apple finishes after all
    # channels; FFmpeg requires ID_END. Change only that marker, never PCM bits.
    atom = song_info.decoderParams or b""
    if song_info.codec != Codec.ALAC or len(atom) != 36 or atom[:12] != b"\\x00\\x00\\x00$alac\\x00\\x00\\x00\\x00":
        return media
    frame_length = int.from_bytes(atom[12:16], "big")
    depth, channels = atom[17], atom[21]
    if atom[16] != 0 or depth not in (16, 20, 24, 32) or channels not in (1, 2):
        return media
    if sum(len(sample.data) for sample in song_info.samples) != len(media):
        return media
    view, fixed, offset, changed = memoryview(media), None, 0, 0
    for sample in song_info.samples:
        size = len(sample.data)
        packet = view[offset:offset + size]
        start, offset = offset, offset + size
        if size < 7:
            continue
        header = int.from_bytes(packet[:3], "big") >> 1
        # One complete SCE/CPE, instance 0, reserved/shift bits 0, escape flag 1.
        expected = ((channels - 1) << 20) | 1
        if header not in (expected, expected | 8):
            continue
        partial = bool(header & 8)
        count = (int.from_bytes(packet[:7], "big") >> 1) & 0xffffffff if partial else frame_length
        if not 0 < count <= frame_length or count != sample.duration:
            continue
        end = (55 if partial else 23) + count * channels * depth
        if (end + 3 + 7) // 8 != size:
            continue
        tail_mask = (1 << (size * 8 - end)) - 1
        # Require the original source to carry the same zero trailer too.
        if int.from_bytes(packet[-2:], "big") & tail_mask or int.from_bytes(sample.data[-2:], "big") & tail_mask:
            continue
        if fixed is None:
            fixed = bytearray(media)
        for bit in range(end, end + 3):
            fixed[start + bit // 8] |= 1 << (7 - bit % 8)
        changed += 1
    if changed:
        logger.info("Normalized missing ALAC end markers in {} uncompressed frames; PCM samples unchanged", changed)
    return bytes(fixed) if fixed is not None else media


'''


def apply_alac_termination(target):
    path = target / "src/mp4.py"
    text = path.read_text(encoding="utf-8")
    marker = "def encapsulate(song_info: SongInfo, decrypted_media: bytes, atmos_convent: bool) -> bytes:\n"
    text = replace_checked(text, marker, ALAC_TERMINATION_PATCH + marker +
                           "    decrypted_media = normalize_alac_termination(song_info, decrypted_media)\n")
    path.write_text(text, encoding="utf-8")


def apply_format_selection(target):
    path = target / "src/rip.py"
    text = path.read_text(encoding="utf-8")
    original = "            m3u8_url = await self._get_m3u8_url(task, codec, raw_metadata)\n"
    text = replace_checked(text, original, original +
        "            if hasattr(self, 'select_audio'):\n" +
        "                codec, m3u8_url = await self.select_audio(task, codec, raw_metadata, m3u8_url)\n")
    text = replace_checked(text,
        "task.m3u8Info = await legacy_extract_media(await it(WrapperManager).webPlayback(task.adamId))",
        "task.m3u8Info = getattr(task, 'legacy_media', None) or await legacy_extract_media(await it(WrapperManager).webPlayback(task.adamId))")
    path.write_text(text, encoding="utf-8")
    path = target / "src/mp4.py"
    text = path.read_text(encoding="utf-8")
    original = '''    parsed_m3u8 = m3u8.loads(await it(WebAPI).download_m3u8(m3u8_url), uri=m3u8_url)
    specifyPlaylist = find_best_codec(parsed_m3u8, codec)'''
    text = replace_checked(text, original, '''    parsed_m3u8 = getattr(task, "audio_manifest", None) or m3u8.loads(await it(WebAPI).download_m3u8(m3u8_url), uri=m3u8_url)
    specifyPlaylist = getattr(task, "selected_media", None) or find_best_codec(parsed_m3u8, codec)''')
    path.write_text(text, encoding="utf-8")


def replace_checked(text, original, replacement):
    if text.count(original) != 1: raise RuntimeError("Upstream performance patch no longer applies: " + original[:100])
    return text.replace(original, replacement)


def apply_performance(target):
    path = target / "src/api.py"
    text = path.read_text(encoding="utf-8")
    text = replace_checked(text, "from io import BytesIO", "from io import BytesIO\nfrom async_lru import alru_cache")
    text = replace_checked(text, "        self._set_token()", "        self.token = \"\"\n        self.init_lock = asyncio.Lock()\n        self.proxy = proxy or None")
    text = replace_checked(text, "        self.request_lock = asyncio.Semaphore(256)", '''        self.request_lock = asyncio.Semaphore(256)
        self.download_client = httpx.AsyncClient(transport=AsyncCustomHost(NameSolver()),
                                                timeout=httpx.Timeout(15.0, read=60.0, connect=15.0, pool=20.0))
        for name, size, ttl in (("get_song_info", 4, 60), ("get_album_info", 16, 300), ("get_cover", 2, 300)):
            setattr(self, name, alru_cache(maxsize=size, ttl=ttl)(getattr(self, name)))''')
    text = replace_checked(text, '''    def _set_token(self):
        with httpx.Client() as client:
            resp = client.get("https://music.apple.com", follow_redirects=True)
            index_js_uri = regex.findall(r"/assets/index~[^/]+\\.js", resp.text)[0]
            js_resp = client.get("https://music.apple.com" + index_js_uri)
            self.token = regex.search(r'(eyJ[A-Za-z0-9-_=]+\\.[A-Za-z0-9-_=]+\\.[A-Za-z0-9-_=]+)', js_resp.text)[0]

    # DO NOT REMOVE IT
    def init(self):
        pass''', '''    async def _set_token(self):
        async with httpx.AsyncClient(proxy=self.proxy) as client:
            resp = await client.get("https://music.apple.com", follow_redirects=True)
            resp.raise_for_status()
            index_js_uri = regex.findall(r"/assets/index~[^/]+\\.js", resp.text)[0]
            js_resp = await client.get("https://music.apple.com" + index_js_uri)
            js_resp.raise_for_status()
            self.token = regex.search(r'(eyJ[A-Za-z0-9-_=]+\\.[A-Za-z0-9-_=]+\\.[A-Za-z0-9-_=]+)', js_resp.text)[0]

    async def init(self):
        async with self.init_lock:
            if not self.token:
                await self._set_token()
                self.client.headers["Authorization"] = f"Bearer {self.token}"

    async def aclose(self):
        for name in ("get_song_info", "get_album_info", "get_cover"):
            cache = getattr(self, name)
            await cache.cache_close()
            cache.cache_clear()
        await self.download_client.aclose()
        await self.client.aclose()''')
    text = replace_checked(text, "    async def _request(self, *args, **kwargs):\n        async with self.request_lock:", "    async def _request(self, *args, **kwargs):\n        await self.init()\n        async with self.request_lock:")
    start = text.index("        timeout = httpx.Timeout", text.index("    async def _download_song_internal"))
    end = text.index("\n    async def download_song", start)
    block = text[start:end]
    body = block[block.index("            async with client.stream"):]
    body = "\n".join(line[4:] if line.startswith("    ") else line for line in body.splitlines()) + "\n"
    text = text[:start] + body.replace("client.stream", "self.download_client.stream") + text[end:]
    text = replace_checked(text, "            raise httpx.HTTPError\n", '            raise httpx.HTTPError("Downloaded audio length does not match the response header")\n')
    path.write_text(text, encoding="utf-8")
    path = target / "src/cmd.py"
    text = replace_checked(path.read_text(encoding="utf-8"), "loop.run_until_complete(run_sync(it(WebAPI).init))", "loop.run_until_complete(it(WebAPI).init())")
    path.write_text(text, encoding="utf-8")
    path = target / "src/rip.py"
    text = path.read_text(encoding="utf-8")
    start = text.index("                    # Initialize futures for each sample")
    end = text.index("                    local_codec =", start)
    text = text[:start] + "                    decrypted_media = await self._decrypt_samples(task)\n\n" + text[end:]
    text = replace_checked(text, "bytes().join(decrypted_samples)", "decrypted_media")
    marker = "    async def _get_m3u8_url("
    helper = '''    async def _decrypt_samples(self, task):
        samples = iter(enumerate(task.info.samples))
        results = [None] * len(task.info.samples)
        loop = asyncio.get_running_loop()
        async def consume():
            for index, sample in samples:
                task.decrypted_samples_futures[index] = loop.create_future()
                try:
                    results[index] = await self.decrypt_sample_with_retry(
                        task.adamId, task.m3u8Info.keys[sample.descIndex], sample.data, index)
                finally:
                    task.decrypted_samples_futures.pop(index, None)
        async with asyncio.TaskGroup() as group:
            for _ in range(min(64, len(task.info.samples))):
                group.create_task(consume())
        return b"".join(results)

'''
    text = replace_checked(text, marker, helper + marker)
    start = text.index("            # Check Local Existence")
    end = text.index("            # Get M3U8", start)
    check = text[start:end]
    text = text[:start] + text[end:]
    marker = "            # Get Cover and Lyrics"
    # Playlist indices are needed for local filename checks.
    index_block = "            if playlist:\n                task.metadata.set_playlist_index(playlist.songIdIndexMapping.get(url.id))\n\n"
    text = replace_checked(text, index_block, "")
    text = replace_checked(text, marker, index_block + check + marker)
    path.write_text(text, encoding="utf-8")


def apply(target):
    replacements = {
        'f"gpac -i {raw_mp4.absolute()} nhmlw:pckp=true -o {nhml_name}"': '["gpac", "-p=0", "-i", str(raw_mp4.absolute()), "nhmlw:pckp=true", "-o", str(nhml_name)]',
        'f"MP4Box -diso {raw_mp4.absolute()} -out {xml_name}"': '["MP4Box", "-p=0", "-diso", str(raw_mp4.absolute()), "-out", str(xml_name)]',
        'f"mp4extract moov/trak/mdia/minf/stbl/stsd/enca[0]/alac {raw_mp4.absolute()} {alac_atom_name}"': '["mp4extract", "moov/trak/mdia/minf/stbl/stsd/enca[0]/alac", raw_mp4.name, alac_atom_name.name], cwd=tmp_dir.name',
        'f"gpac -i {nhml_name.absolute()} nhmlr -o {song_name.absolute()}"': '["gpac", "-p=0", "-i", str(nhml_name.absolute()), "nhmlr", "-o", str(song_name.absolute())]',
        'f"mp4edit --insert moov/trak/mdia/minf/stbl/stsd/alac:{alac_params_atom_name.absolute()} {song_name.absolute()} {final_m4a_name.absolute()}"': '["mp4edit", "--insert", f"moov/trak/mdia/minf/stbl/stsd/alac:{alac_params_atom_name.name}", song_name.name, final_m4a_name.name], cwd=tmp_dir.name',
        'f"gpac -i {media.absolute()} -o {song_name.absolute()}"': '["gpac", "-p=0", "-i", str(media.absolute()), "-o", str(song_name.absolute())]',
        'f\'MP4Box -brand "M4A " -ab "M4A " -ab "mp42" {song_name.absolute()}\'': '["MP4Box", "-p=0", "-brand", "M4A ", "-ab", "M4A ", "-ab", "mp42", str(song_name.absolute())]',
        '["MP4Box",\n': '["MP4Box", "-p=0",\n',
        'f"ffmpeg -y -i {song_name.absolute()} -fflags +bitexact -map_metadata 0 -c:a copy -c:v copy {new_song_name.absolute()}"': '["ffmpeg", "-y", "-i", str(song_name.absolute()), "-fflags", "+bitexact", "-map_metadata", "0", "-c:a", "copy", "-c:v", "copy", str(new_song_name.absolute())]',
        'f"mp4extract moov/trak/mdia/minf/stbl/stsd/enca[0]/esds {raw_song_name.absolute()} {esds_name.absolute()}"': '["mp4extract", "moov/trak/mdia/minf/stbl/stsd/enca[0]/esds", raw_song_name.name, esds_name.name], cwd=tmp_dir.name',
        'f"mp4edit --replace moov/trak/mdia/minf/stbl/stsd/mp4a/esds:{esds_name.absolute()} {song_name.absolute()} {final_song_name.absolute()}"': '["mp4edit", "--replace", f"moov/trak/mdia/minf/stbl/stsd/mp4a/esds:{esds_name.name}", song_name.name, final_song_name.name], cwd=tmp_dir.name',
        'f"ffmpeg -y -v error -i {song_name.absolute()} -c:a pcm_s16le -f null /dev/null"': '["ffmpeg", "-y", "-v", "error", "-i", str(song_name.absolute()), "-c:a", "pcm_s16le", "-f", "null", "-"]',
    }
    path = target / "src/mp4.py"
    text = path.read_text(encoding="utf-8")
    for original, replacement in replacements.items():
        expected = 2 if "nhmlr" in original else 1
        if text.count(original) != expected: raise RuntimeError("Upstream media patch no longer applies: " + original)
        text = text.replace(original, replacement)
    # Argument lists must not be routed through a command shell.
    text = text.replace("shell=if_shell()", "shell=False")
    text = text.replace("return not bool(output.stderr)", "return output.returncode == 0 and not bool(output.stderr)")
    path.write_text(text, encoding="utf-8")
    path = target / "src/legacy/mp4.py"
    text = path.read_text(encoding="utf-8")
    original = 'f"mp4decrypt --key {kid}:{key} {song_name.absolute()} {new_song_name.absolute()}"'
    if text.count(original) != 1: raise RuntimeError("Upstream legacy media patch no longer applies")
    text = text.replace(original, '["mp4decrypt", "--key", f"{kid}:{key}", song_name.name, new_song_name.name], cwd=tmp_dir.name')
    text = text.replace("shell=if_shell()", "shell=False").replace("from src.mp4 import if_shell\n", "")
    path.write_text(text, encoding="utf-8")
    # Only the two patched modules used this helper.
    path = target / "src/mp4.py"
    text = path.read_text(encoding="utf-8").replace("import sys\n", "")
    start, end = text.index("def if_shell():"), text.index("async def get_available_codecs")
    text = text[:start] + text[end:]
    path.write_text(text, encoding="utf-8")
    apply_performance(target)
    apply_alac_termination(target)
    apply_format_selection(target)
    (target / "PATCHES.md").write_text("""# AM Dowloader bundled backend changes

Pinned upstream source and commit are recorded in bundle.json; upstream LICENSE.txt applies.
src/mp4.py and src/legacy/mp4.py use argument lists so Windows paths containing
spaces remain single arguments. Bento4 commands use ASCII temporary filenames
relative to their Unicode working directory because its Windows build cannot
open Unicode command-line filenames. FFmpeg integrity checking uses the null muxer's
standard output and verifies its exit code. GPAC / MP4Box use the temporary
profile (-p=0), keeping installation files read-only. API initialization is
asynchronous, with bounded per-process metadata/artwork caches and a reusable
download client. Existing-file checks precede cover/lyrics requests. Audio sample
processing uses at most 64 in-flight tasks with structured cancellation. Codec
selection and full integrity checking are retained. All modified source is included here.
Uncompressed mono/stereo ALAC frames with a complete PCM payload and a zeroed
end marker are normalized before muxing. Only the three ID_END bits change;
PCM samples and the full strict integrity check are preserved.
The desktop worker can negotiate an unavailable format before downloading;
the confirmed manifest variant is reused exactly, including legacy AAC.
The reproducible patch script is ../source/backend_patches.py.
""", encoding="utf-8")
