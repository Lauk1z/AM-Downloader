# Windows direct audio host

Build with `python build_audio.py` using Visual Studio C++ x64 tools and Windows SDK.
The generated `bin/am_audio.exe` is shipped alongside the GUI, with the complete
source here. No ASIO driver is redistributed; it loads the user's registered
64-bit vendor driver. This host's code is AGPL-3.0-or-later.

ASIO interface headers are unchanged from SDK mirror `audiosdk/asio`, commit
496a0765b8bb9c26f764f22f9a9712a937177db2 (see `asio/COMMIT.txt`). They are used
under the SDK's **GPL version 3 alternative**, not its proprietary agreement.
The original notice is in `asio/LICENSE.txt`, and GPLv3 is included in the
application's `licenses/GPL-3.0.txt`. ASIO is a trademark and software of
Steinberg Media Technologies GmbH. Official open-source SDK information:
https://www.steinberg.net/developers/asiosdk-open/
Exact header source: https://github.com/audiosdk/asio/tree/496a0765b8bb9c26f764f22f9a9712a937177db2/common

The parser emits canonical MSB-first, byte-interleaved DSD from DSF and
uncompressed DSDIFF. ASIO buffer sizes are measured in 1-bit samples, so packed
DSD buffers contain `bufferSize / 8` bytes per channel. LSB-first driver buffers
are bit-reversed at the final copy. DoP preserves chronological payload bits
in bits 15..0 and alternates markers 0x05/0xFA in bits 23..16, identically on
all channels. Its 24 valid bits are left aligned in a 32-bit PCM transport
before conversion to the device's integer format. Standard:
https://dsd-guide.com/sites/default/files/white-papers/DoP_openStandard_1v1.pdf

PCM uses bundled FFmpeg as an incremental decoder to signed 32-bit samples,
without sample-rate conversion, channel mixing or software gain. Integer
output precision must accommodate the source. This does not assert that every
floating-point source or downstream DAC processing is bit-perfect.

File IO and decoding run on a producer thread; a preallocated SPSC ring feeds
native audio callbacks. Python/Qt exchanges only controls and progress JSON.
Seeking starts a fresh host after stopping the old one, flushing all queued
samples and resetting DoP markers. DAC/format failures do not silently switch
to shared output or convert DSD to PCM. Pause stops the device without inserting
PCM zeroes into a DSD stream; underruns abort output. Decoder child processes
belong to a kill-on-close Windows job. The selected DAC is released on stop,
track changes, mode changes and exit.

The offline `--mode render` path uses the same parser/packer and is exercised
by `tests/test_direct_audio.py`. It never opens an audio device. Hardware tests
are separate and use generated digital silence, not arbitrary DSD bit patterns.
