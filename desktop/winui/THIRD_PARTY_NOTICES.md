# AM Dowloader WinUI — third-party software

The application and native audio host are distributed under GNU AGPL-3.0-or-later;
see LICENSE.txt. Complete application source and build scripts are in `source`.
This software is independent of Apple Inc. No account image, saved credentials,
personal preferences, catalog artwork or music is included in the distribution.

## Windows application runtime

| Component | Pinned version | Notices and source |
| --- | --- | --- |
| .NET runtime | 10.0.13; built with SDK 10.0.402 | Microsoft runtime license and third-party notices in `licenses`; https://github.com/dotnet/runtime/tree/v10.0.13 |
| Microsoft.WindowsAppSDK.WinUI | 2.3.9 | Original NuGet license and NOTICE included; framework source: https://github.com/microsoft/microsoft-ui-xaml |
| Microsoft.WindowsAppSDK.InteractiveExperiences | 2.1.9 | Original NuGet license and NOTICE included; https://github.com/microsoft/WindowsAppSDK |
| Microsoft.WindowsAppSDK.Foundation / Base | 2.3.12 / 2.0.4 | Original NuGet terms in `licenses`; https://github.com/microsoft/WindowsAppSDK |
| WebView2 loader / C#/WinRT / Windows SDK projections | Versions recorded in application dependency files and source project lock data | Original package licenses and notices in `licenses`; https://github.com/microsoft/CsWinRT ; https://learn.microsoft.com/microsoft-edge/webview2/ |

The actual self-contained Windows App SDK binaries are governed by their included
Microsoft license terms and third-party notices; the framework source repository's
license is not a substitute for those binary terms. Windows fonts are loaded from
the user's Windows installation and are not redistributed. Qt, PySide6, Shiboken,
Qt Multimedia and PyInstaller are not used by this WinUI distribution.

## Retained backend and audio components

The public AppleMusicDecrypt Windows runtime comes from the matching upstream
artifact (run 28754686975, artifact 8095733521), verified with SHA-256
`0d2b7b21b2cb9a6ad3f411ad88519de68a94f345c8b56b25ae1b61cc015bc428`.
The complete modified backend source, lock file, patch descriptions and license
are in `vendor/backend`. Integration changes are reproducible from
`source/backend_patches.py`; exact provenance is in `vendor/backend/bundle.json`.

| Component | Version / provenance | License and source |
| --- | --- | --- |
| AppleMusicDecrypt | d1a9a10079a72a454ce013589a5a47d5c17c8aee | AGPL v3; `vendor/backend/LICENSE.txt`; https://github.com/WorldObservationLog/AppleMusicDecrypt/tree/d1a9a10079a72a454ce013589a5a47d5c17c8aee |
| Backend CPython / WinPython | 3.12.10 / WinPython 3.12.10.1 | PSF; license included in `.venv`; https://github.com/winpython/winpython/releases/tag/16.6.20250620 |
| Python dependencies | Exact versions and notices in `.venv/Lib/site-packages/*dist-info`; upstream lock in `poetry.lock` | Individual distribution licenses included |
| Mutagen | Version in its bundled dist-info | GPL v2 or later; https://github.com/quodlibet/mutagen |
| Pillow / FreeType | Versions and third-party notices in bundled distribution | MIT-CMU / HPND and included FreeType terms; https://github.com/python-pillow/Pillow |
| tomlkit | Version in bundled dist-info | MIT; https://github.com/python-poetry/tomlkit |
| Steinberg ASIO SDK headers | mirror commit 496a0765b8bb9c26f764f22f9a9712a937177db2 | GPL v3 alternative explicitly selected; original headers and terms in `source/native/asio`; https://github.com/audiosdk/asio/tree/496a0765b8bb9c26f764f22f9a9712a937177db2/common |
| QEMU and bundled firmware | 10.2.0, Windows build 20251224 | GPL v2 and component-specific terms; https://qemu.weilnetz.de/w64/2025/ ; https://gitlab.com/qemu-project/qemu |
| GPAC / MP4Box | 26.03-DEV-rev410-geb769790-master | LGPL v2.1 or later; https://github.com/gpac/gpac/tree/eb769790 |
| FFmpeg command-line tool | 2026-07-02-git-95a888b9ca, Gyan essentials | GPL-enabled build; licenses included; https://www.gyan.dev/ffmpeg/builds/ ; https://github.com/FFmpeg/FFmpeg/tree/95a888b9ca |
| Bento4 tools | SDK 1.6.0-641 | GPL v2; https://github.com/axiomatic-systems/Bento4 |
| wrapper-manager | Pristine image supplied by pinned artifact | Source, image recipes and notices: https://github.com/WorldObservationLog/wrapper-manager |

The pristine uncompressed QCOW2 has SHA-256
`15f154159ea191197b7d1859a104c6b140480ac0ed320d8076e4a48d3224ddda`.
Its `.xz` archive has SHA-256
`c4bfdafe74d198388242c188aaed49ee01f4a16b599dcfd4cd282ad012bb0b1c`.
The installation image is never opened for writing. A private copy is created in
the per-user profile at first backend launch.

Direct Linux boot includes the unmodified QEMU v10.2.0 `linuxboot_dma.bin`,
GPL-2.0-or-later, SHA-256
`9c49e255340c78fc12e54ed043462bca02fb7fca29b7cfab62ff88a5344b6950`.
Corresponding source/build tree:
https://github.com/qemu/qemu/tree/v10.2.0/pc-bios/optionrom ; full release:
https://download.qemu.org/qemu-10.2.0.tar.xz . Initramfs initialization changes are
generated locally by `source/musicdesk_boot.py`; no user-derived kernel cache is shipped.

SACD extraction uses the upstream-built `sacd_extract.exe` from netXing/sacd_extract,
release `sacd_extract_fixed`, commit `9fae7fa5b66a391eb2ef2d69384352e895680f0d`.
Binary SHA-256:
`e79f79957650a10a4845fc3e7efe59c6ca4b0045ad5ad63026324cf4727f84cc`.
Complete corresponding source, build files and dependency notices are included
in `source/native/sacd-source.zip`, SHA-256
`293a0cec23502bf40b9db82ac3738ded7073dafa65813af8fa462cd88e55ff1d`.
The main component is GPL-2.0-or-later; bundled libiconv retains its LGPL notices.
Provenance is in `source/native/sacd-upstream.json`; staging verifies both hashes.
Upstream: https://github.com/netxing/sacd_extract/releases/tag/sacd_extract_fixed ;
https://github.com/sacd-ripper/sacd-ripper .

Backend tools and shared libraries remain replaceable. Original license texts and
metadata are retained. No restriction on reverse engineering for debugging LGPL
modifications is added. ASIO is a Steinberg trademark; vendor ASIO drivers are
loaded from the user's installation and are not redistributed. No BASS library
or foobar2000 component is included.
