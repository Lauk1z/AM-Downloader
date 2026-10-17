# AM Dowloader — third-party software

AM Dowloader 1.3.0 is provided with its complete application source under GNU AGPL-3.0-or-later; see LICENSE.txt. It is independent software and is not affiliated with Apple Inc. Apple Music names and catalog artwork belong to their respective owners. Catalog artwork is fetched at runtime and is not included in this package.

The package includes AppleMusicDecrypt v2 at commit d1a9a10079a72a454ce013589a5a47d5c17c8aee, its public runtime dependencies and pristine wrapper-manager image. No user's account image, preferences, credentials or music are included. Upstream: https://github.com/WorldObservationLog/AppleMusicDecrypt (GNU AGPL v3). The complete modified backend Python source, dependency lock and license are in backend; the application and reproducible integration patches are in source. See backend/PATCHES.md and backend/bundle.json for exact provenance and changes.

The bundled Windows runtime is taken from the matching official upstream workflow artifact (run 28754686975, artifact 8095733521). The build script verifies SHA-256 0d2b7b21b2cb9a6ad3f411ad88519de68a94f345c8b56b25ae1b61cc015bc428 before extraction. The unchanged initial QCOW2 has SHA-256 15f154159ea191197b7d1859a104c6b140480ac0ed320d8076e4a48d3224ddda. The application copies it into a per-user writable location at first backend launch; the installation copy is never opened for writing.

The original Actions artifact is no longer available. An unchanged copy is preserved as `AppleMusicDecrypt-v2-runtime.zip` in https://github.com/Lauk1z/AM-Downloader/releases/tag/v1.5.2 . Its SHA-256 remains the original value above; the source build downloads this mirror and still verifies the checksum. The archive is a build input, not a user account image. Component sources, upstream notices and licenses remain in the archive and in the packaged backend.

Bundled runtime components:

| Component | Version | License / source |
| --- | --- | --- |
| Steinberg ASIO SDK interface headers | mirror commit 496a0765b8bb9c26f764f22f9a9712a937177db2 | GPL v3 alternative, explicitly selected; original license and unchanged headers in source/native/asio, GPL text in licenses/GPL-3.0.txt; https://www.steinberg.net/developers/asiosdk-open/ ; exact source https://github.com/audiosdk/asio/tree/496a0765b8bb9c26f764f22f9a9712a937177db2/common |
| CPython | 3.12.14 | PSF; https://www.python.org/ |
| PySide6 / Shiboken6 / Qt | 6.11.2 | LGPL v3 / GPL alternatives; https://code.qt.io/cgit/pyside/pyside-setup.git/ and https://code.qt.io/cgit/qt/ |
| FreeType font renderer | As supplied by Qt | FreeType Project License; https://freetype.org/ ; license text included in licenses/Pillow.txt |
| Qt Multimedia FFmpeg libraries | As supplied by Qt 6.11.2 wheels | FFmpeg licensing and source: https://ffmpeg.org/legal.html ; https://ffmpeg.org/download.html |
| Mutagen | 1.48.1 | GPL v2 or later; https://github.com/quodlibet/mutagen |
| tomlkit | 0.15.1 | MIT; https://github.com/python-poetry/tomlkit |
| Pillow | 12.3.0 | MIT-CMU / HPND; https://github.com/python-pillow/Pillow |
| PyInstaller bootloader | 6.22.2 | GPL with bootloader exception; https://pyinstaller.org/ |
| Backend CPython / WinPython | 3.12.10 / WinPython 3.12.10.1 | PSF; license in backend/.venv; https://github.com/winpython/winpython/releases/tag/16.6.20250620 |
| Backend Python dependencies | Versions in backend/.venv/Lib/site-packages/*dist-info | Individual licenses and metadata included with each distribution; backend/poetry.lock records upstream dependencies |
| AppleMusicDecrypt | d1a9a10079a72a454ce013589a5a47d5c17c8aee | AGPL v3; backend/LICENSE.txt; https://github.com/WorldObservationLog/AppleMusicDecrypt/tree/d1a9a10079a72a454ce013589a5a47d5c17c8aee |
| QEMU and bundled firmware | 10.2.0, Windows build 20251224 | GPL v2 and component-specific licenses; licenses/GPL-2.0.txt; source and build materials: https://qemu.weilnetz.de/w64/2025/ and https://gitlab.com/qemu-project/qemu |
| GPAC / MP4Box | 26.03-DEV-rev410-geb769790-master | LGPL v2.1 or later; licenses/LGPL-2.1.txt; source: https://github.com/gpac/gpac/tree/eb769790 |
| FFmpeg command-line tool | 2026-07-02-git-95a888b9ca, Gyan essentials | GPL-enabled build; licenses/FFmpeg.txt, GPL-3.0.txt, GPL-2.0.txt, LGPL-2.1.txt; https://www.gyan.dev/ffmpeg/builds/ and https://github.com/FFmpeg/FFmpeg/tree/95a888b9ca |
| Bento4 tools | SDK 1.6.0-641 | GPL v2; licenses/Bento4.txt and GPL-2.0.txt; https://github.com/axiomatic-systems/Bento4 |
| wrapper-manager image | Pristine image supplied with pinned upstream artifact | Source, image recipes and notices: https://github.com/WorldObservationLog/wrapper-manager ; image includes its upstream runtime and public assets unchanged |

License texts are provided in licenses and the backend runtime distributions. Qt and multimedia libraries are dynamically linked DLLs in _internal and can be replaced with compatible builds. Backend tools and DLLs in backend/deps are unmodified and replaceable. The source directory includes the application and build scripts for modification and rebuilding. No restriction on reverse engineering for debugging modifications to LGPL libraries is added by AM Dowloader.

Microsoft YaHei UI fonts are loaded from the user's existing Windows installation and are not redistributed. Portions of this software are copyright The FreeType Project (https://freetype.org). All rights reserved.

The native audio host is included at native/bin/am_audio.exe with its full AGPL source and build script under source/native and source/build_audio.py. ASIO is a trademark and software of Steinberg Media Technologies GmbH. The application uses the SDK's GPLv3 alternative; proprietary vendor ASIO drivers are loaded from the user's Windows installation and are not redistributed. No BASS libraries or foobar2000 components are included.

Direct Linux boot additionally includes the unmodified QEMU v10.2.0 `pc-bios/linuxboot_dma.bin` (GPL-2.0-or-later), SHA-256 `9c49e255340c78fc12e54ed043462bca02fb7fca29b7cfab62ff88a5344b6950`. Exact upstream binary and corresponding source/build tree: https://github.com/qemu/qemu/tree/v10.2.0/pc-bios/optionrom and https://github.com/qemu/qemu/blob/v10.2.0/pc-bios/linuxboot_dma.bin ; full source release: https://download.qemu.org/qemu-10.2.0.tar.xz . The original guest kernel is retained. Initramfs initialization changes are generated locally by `source/musicdesk_boot.py`; no user-derived kernel cache is distributed.

SACD ISO support uses the unmodified upstream `sacd_extract.exe` from netXing/sacd_extract, release `sacd_extract_fixed`, associated commit `9fae7fa5b66a391eb2ef2d69384352e895680f0d`. Binary SHA-256: `e79f79957650a10a4845fc3e7efe59c6ca4b0045ad5ad63026324cf4727f84cc`. This is an upstream-built component, not built by this application's packager. Repository/release: https://github.com/netxing/sacd_extract/releases/tag/sacd_extract_fixed . Complete source corresponding to the release tag (including its build files, libdstdec, libid3, libiconv and notices) is included in `source/native/sacd-source.zip`; source archive SHA-256: `293a0cec23502bf40b9db82ac3738ded7073dafa65813af8fa462cd88e55ff1d`. Provenance is also recorded in `source/native/sacd-upstream.json`. The main component is GPL-2.0-or-later; bundled libiconv retains its LGPL notices in the source archive. Original upstream: https://github.com/sacd-ripper/sacd-ripper . Our bounded TOC reader follows libsacd's documented on-disk structures. Build staging verifies both pinned hashes using `source/build_sacd.py`.
