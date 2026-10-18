using AMDownloader.Core;
using System.Text;
using System.Text.Json;

var count = 0;
void Check(bool condition, string name) { if (!condition) throw new Exception(name); count++; }
var root = Path.Combine(Path.GetTempPath(), "am-winui-tests-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(root);
try
{
    var paths = "ABCDEFG".Select(x => x.ToString()).ToList(); var current = "A"; var order = new ShuffleOrder(new Random(170)); var round = new List<string> { current };
    for (var i = 0; i < 6; i++) { var upcoming = order.Upcoming(paths, current).First(); current = order.Step(paths, current)!; Check(current == upcoming, "queue preview matches next song"); round.Add(current); }
    Check(round.Distinct().Count() == 7, "initial shuffle round is unique");
    for (var iteration = 0; iteration < 100; iteration++)
    { var last = current; round.Clear(); for (var i = 0; i < 7; i++) { current = order.Step(paths, current)!; round.Add(current); } Check(round.Distinct().Count() == 7 && round[0] != last, "next shuffle round avoids boundary repeat"); }
    var previous = order.Step(paths, current, -1)!; Check(order.Step(paths, previous) == current, "Back does not redraw shuffle history");
    order.Reset(); current = "A"; var visited = new List<string> { current }; for (var i = 0; i < 2; i++) { current = order.Step(paths, current)!; visited.Add(current); }
    paths.Remove(paths.First(x => !visited.Contains(x))); for (var i = 0; i < 3; i++) { current = order.Step(paths, current)!; visited.Add(current); }
    Check(visited.Distinct().Count() == 6, "removal preserves unplayed shuffle remainder"); Check(order.Step([], "") is null, "empty shuffle");
    Check(OrderedEntries.Move(new[] { 0, 1, 2, 3, 4 }, [1, 3], 5).SequenceEqual(new[] { 0, 2, 4, 1, 3 }), "multi-row reorder");
    var lyrics = Lyrics.Parse("[offset:-250]\n[00:00.00]Intro\n[00:01.50][00:02.50]Main\n[00:01.50]Translation");
    Check(lyrics.Count == 3 && lyrics[1].Time == 1250 && lyrics[1].Content == "Main\nTranslation", "LRC offset and translation grouping");
    Check(Lyrics.Active(lyrics, 1249) == 0 && Lyrics.Active(lyrics, 1250) == 1, "lyric time boundary");
    var audio = Path.Combine(root, "曲目.wav"); File.WriteAllBytes(audio, []); var cue = Path.Combine(root, "整轨.cue"); File.WriteAllText(cue, "");
    var entries = new List<PlaylistEntry> { new(audio, "曲目", "艺人", 123), new(audio, "曲目", "艺人", 123), new(cue + "#amtrack=2", "二", "", 5), new(Path.Combine(root, "missing.flac"), "缺失", "", 2) };
    var filename = Path.Combine(root, "list.m3u8"); M3u.Write(filename, "测试歌单", entries); var imported = M3u.Read(filename);
    Check(imported.Name == "测试歌单" && imported.Entries.Select(x => x.Path).SequenceEqual(entries.Select(x => x.Path)), "M3U keeps duplicates, virtual tracks and missing files");
    Check(File.ReadAllBytes(filename).Take(3).SequenceEqual(new byte[] { 239, 187, 191 }), "UTF-8 M3U BOM");
    File.WriteAllText(filename, "#EXTM3U\nhttps://example.test/live.mp3\n曲目.wav\n", Encoding.Unicode); imported = M3u.Read(filename);
    Check(imported.Entries.Count == 1 && imported.Warnings.Count == 1, "UTF16 and network stream exclusion");
    File.WriteAllText(Path.Combine(root, "preferences.json"), "{\"unknown\":{\"retain\":true},\"volume\":17,\"last_track\":\"old\"}");
    var store = new StateStore(root); store.Set("last_track", audio); store.Set("playlists", new[] { new Playlist { Name = "Keep", Entries = entries } });
    using var state = JsonDocument.Parse(File.ReadAllText(store.FilePath)); Check(state.RootElement.GetProperty("unknown").GetProperty("retain").GetBoolean() && store.Get("volume", 0) == 17, "unknown legacy preferences retained");
    Check(Directory.GetFiles(root, "preferences.json.before-winui-*").Length == 1, "single pre-migration backup");
    Check(new StateStore(root).Get("playlists", new List<Playlist>())[0].Entries.Count == 4, "playlist JSON compatibility");
    using var gap = new InterTrackGap(TimeSpan.FromMilliseconds(80)); var ready = new TaskCompletionSource(); var fired = 0; gap.Ready += () => { fired++; ready.TrySetResult(); };
    gap.Start(); await Task.Delay(20); gap.Pause(); await Task.Delay(100); Check(gap.Waiting && !gap.Running && fired == 0, "pause holds pending inter-track gap"); gap.Start(); await ready.Task.WaitAsync(TimeSpan.FromSeconds(2)); Check(fired == 1 && !gap.Waiting, "resume restarts inter-track gap");
    gap.Start(); gap.Start(); gap.Cancel(); await Task.Delay(100); Check(fired == 1 && !gap.Waiting, "duplicate end and explicit cancel cannot advance");
    Check(new InterTrackGap() is IDisposable, "gap lifetime");
    Check(Formats.ValidateLinks("https://music.apple.com/cn/album/test/123\nhttps://music.apple.com/cn/album/test/123").Count == 1, "download link deduplication");
    var rejected = false; try { Formats.ValidateLinks("https://untrusted.test/song/123"); } catch (ArgumentException) { rejected = true; } Check(rejected, "download host validation");
    Check(new Track { Codec = "dsd", Bits = 1, Rate = 22579200 }.Quality.Contains("DSD512"), "DSD512 display");
    Console.WriteLine($"PASS {count} assertions: state, queue, shuffle, gap, lyrics, M3U and formats");
}
finally { Directory.Delete(root, true); }
