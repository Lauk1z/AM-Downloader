# WinUI migration

Scope confirmed by the maintainer: replace the Qt application layer with C# and
WinUI 3. Keep the existing AppleMusicDecrypt worker and native ASIO/WASAPI/DSD
host. Mutagen, CUE/SACD indexing and transactional tag editing run in an isolated,
Qt-free utility process. No Qt control, Qt multimedia, Qt application event loop
or Qt library is used by the new desktop application.

The 1.5.2 application is the behavior and layout baseline. The new entry point is
`AM Downloader WinUI.exe`; the former Qt source and installed release are kept
for comparison and are not loaded by this executable. This is a working migration
preview, not an assertion that every online service or DAC has been tested.

## Acceptance matrix

| Area | Implemented behavior | Verification and remaining checks |
| --- | --- | --- |
| Shell | 224 DIP sidebar, 64 DIP player, integrated window controls, permanent album blur, dark/rose theme | Real WinUI render captures reviewed; narrow layout, fullscreen/restore, caption hit tests and minimize exercised |
| Navigation | Home, recently played albums, recent imports, artists, albums, songs, favourites, album details, search transitions | Eleven real pages rendered; artists checked at 1100 by 720 DIP with lyrics open, filters contained, detail scroll restored on return |
| Library | Recursive import, drag/drop, 28 audio extensions, CUE/SACD, filters, versions, duplicates | Generated audio, CUE and SACD samples scanned/prepared; duplicate and metadata rules tested. External Explorer drag/drop still needs manual acceptance |
| Editing | Album context menu; per-track and album fields, cover replacement, original-file backups | Real tag/cover transactions, backup preservation and virtual-track overrides tested; cancellation recovery implemented |
| Playlists | Create, rename, delete, drag/drop, multi-selection, reorder, missing entries, M3U roundtrip | Order/move, duplicate/missing entries, virtual tracks and UTF-8/UTF-16/legacy encodings tested; pointer drag gestures still need manual acceptance |
| Playback | Shared decoding without Qt, WASAPI/ASIO PCM, native DSD/DoP, pause, seek, volume, repeat | Real shared host played silent samples; PCM conversion and offline DSD/DoP byte/seek tests passed. Actual DAC exclusive/ASIO/DoP/native DSD is untested |
| Queue | Independent saved queue, next/last, reorder/remove/clear, no-repeat shuffle, two-second gap | Core rules including 100 shuffle rounds; real playback pause/seek/gap and rapid preparation exercised |
| Lyrics | Sidebar, bold text, timestamp grouping, native animated following, click-to-seek | LRC grouping/offset rules and real sidebar render/seek exercised. No frame-rate benchmark or manual high-refresh display test claimed |
| Downloads | Auto-start, progress, pause/retry/remove, fallback confirmation, search, sanitized logs | Retained packaged backend started, exported logs and stopped; warm direct boot exercised. Stale fallback UI replies tested. Live Apple search/download/integrity results remain untested |
| Account | History without password autofill, DPAPI secrets, auto-login, persistent errors and 2FA retry | Real modeless WinUI login with mocked protocol responses; DPAPI, bad password, first 2FA, bad code, retry and stale success tested. Live account authorization remains untested |
| Lifecycle | Single instance, tray restore, close choice and remember, tray playback/queue/output shortcuts, orderly engine shutdown | Own WM_CLOSE/minimize messages, WinUI automation peers, tray hiding/queue/output dispatch and a second executable process exercised; original window restored and child exited |
| Data | Existing JSON keys and paths, persistent queues/playlists, restore last track without autoplay | Fixture profile roundtrip, unknown-key preservation, first-write backup and restored paused selection tested. No personal profile was changed for acceptance |
| Distribution | Isolated self-contained package, Qt-free runtime, corresponding sources and notices | Build succeeded with zero warnings/errors; actual module paths checked for local .NET and WinUI. Public pristine backend provenance and checksums verified; see package manifest |

## Recorded evidence

- `AMDownloader.Tests`: **126 assertions passed**, covering state, queues,
  shuffle, inter-track gap, lyrics, M3U and format/DSD display rules.
- `tests/test_engine.py`: **26 tests passed**. Eighteen generated audio formats
  decoded against FFmpeg references. DSD64/128/256/512 and DoP data and seeking
  were checked byte for byte; CUE/SACD, metadata transactions and config preservation
  also ran. These tests assert that the Python utility does not import PySide6.
- `qa/winui-smoke/report.json`: real debug executable, eleven pages plus narrow
  layout/fullscreen, lyrics/queue, login, output chain, window lifecycle and real
  shared-host playback. Captures use the application's RenderTargetBitmap; this
  is not an external desktop screenshot or a measured animation FPS result.
- `qa/winui-ui-fixes/verified-rose/report.json`: fifteen rapid page switches kept the
  same sidebar buttons and four decoded covers, without reopening their images.
  Cold/warm featured artwork and source-version invalidation passed. Home and
  album scrolling passed at 1100, 1440 and 1800 requested window widths, including
  the bottom edge and content clearance; the album view retained ItemsWrapGrid.
  Navigation captures include an intermediate indicator position. The complete
  smoke suite used a silent Virtual Audio Cable endpoint because the user's
  existing player was using the DAC through ASIO; that player was left running.
  The close confirmation's actual primary-button template passed rose background
  and white-text checks in normal, pointer-over and pressed states, with captures.
  Remembered tray choice and single-instance restoration also passed.
- `qa/winui-ui-fixes/theme-after/report.json`: the real add-music dialog, focused
  link and password inputs, text selection, checked checkbox, selected combo item
  and shared accent buttons passed rose-theme checks. Primary-button normal,
  pointer-over and pressed states retain white text. The volume track has equal
  left/right insets at 1100, 1440 and 1800 requested window widths; captures and
  the existing UI, login, lifecycle and silent shared-output regressions passed.
- `qa/dsd-diagnostics/service-before/report.json` and `service-after-final/report.json`:
  the same simulated exclusive-device checks reproduced early reopen and false
  settings success before the fix; release ordering, failed-settings rollback,
  paused/repeated probing and preparation without autoplay pass after it.
  Capability probing now releases the playback host and preserves track/position.
  The real settings page checks explicit driver selection and retention on refresh
  and mode changes. A silent virtual endpoint checks paused probing and recovery.
  This machine's USB DAC ASIO driver reports DSD64/128/256/512; Realtek ASIO fails
  initialization even without a playback host. These queries do not prove actual
  native DSD or DoP playback. Initialization errors now identify the selected driver.
- `qa/winui-backend-smoke-2/result.json`: actual packaged, pristine account-free
  backend. Full process cold start **25.78 s**, warm start **6.88 s** on this machine;
  worker reported ready after **24.01 s** and **5.08 s**, respectively. Warm boot
  used WHPX direct boot. These numbers are observations, not a startup guarantee.
- Release archive includes `manifest.sha256.json` and an archive SHA-256 sidecar.
  `tests/check_package.py` verifies every file and uses a fresh extraction outside
  the repository, without `--resources`, so a development checkout cannot supply
  missing files. It retains `result.json`, the real executable's `smoke.json` and
  rendered page captures in the requested report directory.
  Publishing explicitly includes the application's PRI and compiled XBF. The
  real executable also checks that the WinUI control dictionary and rose accent
  loaded, so missing application resources cannot pass as a working fallback UI.
  `--audio-device` optionally selects a WASAPI endpoint for the isolated silent
  fixture, without changing the user's audio configuration.

## Checks before replacing the stable release

1. Exercise a live Apple account, first-login 2FA and automatic reconnect, catalog
   search, successful and unavailable-format downloads and cancellation against
   the external service. No credentials were supplied for these acceptance tests.
2. Verify the user's DAC and drivers with WASAPI/ASIO PCM, DoP and native DSD,
   including supported DSD512 transport. Offline byte tests do not prove hardware
   output, and shared-mode final hardware mix format is not measured.
3. Use real APE, TAK, Musepack and DST/SACD samples and the user's large library.
4. Manually check pointer drag/drop, hover scrollbars, wheel feel and animation
   smoothness at the user's display refresh rate. The available environment does
   not provide native desktop control; no manual or visual FPS result is implied.

The preview ZIP does not update the existing installation or reuse personal test
media. It is published manually through GitHub Releases; the build scripts do not
install or publish it. This release does not claim that the remaining checks
above have passed. Local qa evidence paths are development records, not files
included in the source repository; public screenshots use generated fixtures.

## preview.2 icon update

The icon-only update redraws 28 vector icons and replaces text-symbol icons in
buttons, navigation headings, favourites and cover placeholders. Release-package
UI checks cover 16/24/32 sizes, normal/hover/pressed/disabled states, path bounds,
foreground inheritance and disabled opacity. The independently extracted package
contains 4,410 verified files. It retains the earlier UI/lifecycle checks and does
not change the audio engine, download backend or the real-device limits above.
