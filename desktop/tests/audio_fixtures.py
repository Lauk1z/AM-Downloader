"""Reproducible synthetic audio for import and actual decoder regression tests."""
from pathlib import Path
import math
import struct
import subprocess


def dsd_files(root, multiple=64, seconds=4):
    rate = 44100 * multiple
    # One second of first-order sigma-delta, 440 Hz at a low level; repeat exactly.
    if multiple == 64:
        cycle = bytearray(rate // 8)
        accumulator = 0.0
        for n in range(rate):
            accumulator += 0.1 * math.sin(2 * math.pi * 440 * n / rate)
            positive = accumulator >= 0
            accumulator -= 1 if positive else -1
            if positive: cycle[n // 8] |= 1 << (n % 8)
        channel = bytes(cycle) * seconds
    else:
        channel = b'\x69' * (rate * seconds // 8)
    block = 4096
    padded = channel + b'\x69' * (-len(channel) % block)
    payload = b''.join(padded[n:n+block] * 2 for n in range(0, len(padded), block))
    fmt = struct.pack('<4sQIIIIIIQII', b'fmt ', 52, 1, 0, 2, 2, rate, 1, rate * seconds, block, 0)
    dsf = root / f'dsd-{multiple}.dsf'
    dsf.write_bytes(struct.pack('<4sQQQ', b'DSD ', 28, 92 + len(payload), 0) + fmt + struct.pack('<4sQ', b'data', 12 + len(payload)) + payload)
    def chunk(tag, data):
        return struct.pack('>4sQ', tag, len(data)) + data + (b'\0' if len(data) % 2 else b'')
    prop = b'SND ' + chunk(b'FS  ', struct.pack('>I', rate)) + chunk(b'CHNL', struct.pack('>H', 2) + b'SLFTSRGT') + chunk(b'CMPR', b'DSD \x00')
    reversed_bits = bytes(int(f'{i:08b}'[::-1], 2) for i in range(256))
    channel = channel.translate(reversed_bits)
    interleaved = bytearray(len(channel) * 2)
    interleaved[::2] = channel; interleaved[1::2] = channel
    dff = root / f'dsd-{multiple}.dff'
    dff.write_bytes(chunk(b'FRM8', b'DSD ' + chunk(b'FVER', struct.pack('>I', 0x01050000)) + chunk(b'PROP', prop) + chunk(b'DSD ', interleaved)))
    return dsf, dff


def generate(root, ffmpeg):
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    for multiple in (64, 128, 256):
        dsd_files(root, multiple)
    formats = {
        'vorbis.ogg': ['-c:a', 'libvorbis'], 'opus.ogg': ['-c:a', 'libopus'],
        'flac.oga': ['-c:a', 'flac', '-f', 'ogg'], 'audio.opus': ['-c:a', 'libopus'],
        'audio.flac': ['-c:a', 'flac'], 'audio.wav': ['-c:a', 'pcm_s24le'],
        'audio.aiff': ['-c:a', 'pcm_s24be'], 'compressed.aifc': ['-c:a', 'pcm_alaw', '-f', 'aiff'],
        'audio.wv': ['-c:a', 'wavpack'], 'audio.tta': ['-c:a', 'tta'],
        'audio.wma': ['-ar', '44100', '-c:a', 'wmav2'], 'audio.m4a': ['-c:a', 'alac'],
        'audio.mp3': ['-c:a', 'libmp3lame'], 'audio.aac': ['-c:a', 'aac'],
        'audio.spx': ['-ar', '32000', '-c:a', 'libspeex'], 'audio.mp2': ['-ar', '48000', '-c:a', 'mp2'],
        'audio.ac3': ['-ar', '48000', '-c:a', 'ac3'], 'audio.eac3': ['-ar', '48000', '-c:a', 'eac3'],
    }
    for name, options in formats.items():
        subprocess.run([str(ffmpeg), '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                        'sine=frequency=440:sample_rate=96000:duration=4', '-ac', '2',
                        '-metadata', 'title=格式测试', '-metadata', 'artist=Test', '-metadata', 'album=Test Audio',
                        *options, '-y', str(root / name)], check=True, capture_output=True,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    # Real embedded DSD metadata and artwork, without modifying user audio.
    import mutagen
    from mutagen.id3 import TIT2, TPE1, TALB, APIC
    from io import BytesIO
    from PIL import Image
    image = BytesIO(); Image.new('RGB', (32, 32), '#95456f').save(image, 'PNG')
    for name in ('dsd-64.dsf', 'dsd-64.dff'):
        audio = mutagen.File(root / name); audio.add_tags()
        audio.tags.add(TIT2(encoding=3, text=['DSD 本地测试']))
        audio.tags.add(TPE1(encoding=3, text=['Test']))
        audio.tags.add(TALB(encoding=3, text=['Test Audio']))
        audio.tags.add(APIC(mime='image/png', type=3, data=image.getvalue())); audio.save()
    return sorted(root.iterdir())


if __name__ == '__main__':
    import sys
    generate(sys.argv[1], sys.argv[2])
