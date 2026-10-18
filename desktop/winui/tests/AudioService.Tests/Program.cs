using System.Diagnostics;
using System.Text.Json;
using AMDownloader.Core;
using AMDownloader.WinUI.Services;

if (args.Length > 0 && args[0].StartsWith("--")) return await FakeHost(args);
var report = new List<object>();
var folder = Path.GetFullPath(args[0]); Directory.CreateDirectory(folder);
await Check("failed-settings-are-not-applied", async (audio, library, track) =>
{
    await audio.LoadAsync(track, true); await Until(() => audio.State == "playing");
    var saved = audio.Config; var rejected = false;
    try { await audio.ConfigureAsync(new("asio", "missing", "native", "Disconnected test driver")); }
    catch (InvalidOperationException error) { rejected = error.Message.Contains("test driver unavailable"); }
    await Until(() => audio.State == "stopped");
    Require(rejected && audio.Config == saved, "Driver failure was reported as applied or saved invalid output settings");
});
await Check("concurrent-stop-waits-for-device-release", async (audio, library, track) =>
{
    await audio.LoadAsync(track, true); await Until(() => audio.State == "playing");
    var switching = audio.ConfigureAsync(audio.Config);
    await Until(() => File.Exists(track.Path + ".stopping"));
    var loading = audio.LoadAsync(track with { Title = "Latest track" }, true);
    await Task.WhenAll(switching, loading); await Until(() => audio.State is "playing" or "stopped");
    Require(audio.State == "playing" && audio.Error.Length == 0 && audio.Current?.Title == "Latest track", "New output opened before old driver released its lock: " + audio.Error);
});
await Check("probe-releases-paused-host-and-preserves-track", async (audio, library, track) =>
{
    await audio.LoadAsync(track, true); await Until(() => audio.State == "playing");
    await audio.PauseAsync(); await Until(() => audio.State == "paused");
    var position = audio.Position; var config = audio.Config;
    var method = typeof(AudioService).GetMethod("ProbeAsioAsync") ?? throw new InvalidOperationException("No device-releasing probe operation");
    var result = await (Task<List<JsonElement>>)method.Invoke(audio, [track.Path])!;
    Require(result[0].GetProperty("dsd_rates").GetArrayLength() == 4, "Probe failed despite releasing paused output");
    Require(audio.State == "paused" && audio.Position == position && audio.Current == track && audio.Config == config, "Probe changed track, position, output configuration or resumed playback");
    var rejected = false;
    try { await (Task<List<JsonElement>>)method.Invoke(audio, ["missing"])!; }
    catch (InvalidOperationException error) { rejected = error.Message.Contains("test driver unavailable"); }
    Require(rejected && audio.State == "paused" && audio.Position == position && audio.Config == config, "Failed probe damaged playback state");
    await (Task<List<JsonElement>>)method.Invoke(audio, [track.Path])!;
    await audio.PlayAsync(); await Until(() => audio.State == "playing");
});
await Check("probe-during-preparation-does-not-autoplay", async (audio, library, track) =>
{
    library.Preparation = new(TaskCreationOptions.RunContinuationsAsynchronously);
    var loading = audio.LoadAsync(track, true);
    await Until(() => audio.Preparing);
    var method = typeof(AudioService).GetMethod("ProbeAsioAsync") ?? throw new InvalidOperationException("No device-releasing probe operation");
    var inspecting = (Task<List<JsonElement>>)method.Invoke(audio, [track.Path])!;
    library.Preparation.SetResult(track.Path);
    await Task.WhenAll(inspecting, loading);
    Require(!audio.Preparing && audio.State != "playing" && !File.Exists(track.Path + ".lock"), "Preparing track reopened device during or after probe");
    await audio.PlayAsync(); await Until(() => audio.State == "playing");
});
await File.WriteAllTextAsync(Path.Combine(folder, "report.json"), JsonSerializer.Serialize(report, StateStore.Json));
return report.Any(x => !JsonSerializer.SerializeToElement(x).GetProperty("ok").GetBoolean()) ? 1 : 0;

async Task Check(string name, Func<AudioService, LibraryService, Track, Task> run)
{
    var profile = Path.Combine(folder, name); Directory.CreateDirectory(profile);
    var library = new LibraryService(); var store = new StateStore(profile);
    var track = new Track { Path = Path.Combine(profile, "silence.wav"), Title = "Silent fixture", Duration = 600 };
    await using var audio = new AudioService(new RuntimePaths(), library, store, action => action());
    try { await run(audio, library, track); report.Add(new { name, ok = true }); Console.WriteLine("PASS " + name); }
    catch (Exception error) { report.Add(new { name, ok = false, error = error.ToString() }); Console.WriteLine("FAIL " + name + ": " + error.Message); }
}
static void Require(bool condition, string message) { if (!condition) throw new InvalidOperationException(message); }
static async Task Until(Func<bool> condition)
{
    var timer = Stopwatch.StartNew();
    while (!condition()) { if (timer.ElapsedMilliseconds > 6000) throw new TimeoutException("Audio state timed out"); await Task.Delay(10); }
}
static async Task<int> FakeHost(string[] args)
{
    var options = Enumerable.Range(0, args.Length / 2).ToDictionary(i => args[2 * i], i => args[2 * i + 1]);
    if (options.GetValueOrDefault("--device") == "missing" || options.GetValueOrDefault("--probe-asio") == "missing") { Console.WriteLine("{\"event\":\"error\",\"message\":\"test driver unavailable\"}"); return 1; }
    var probe = options.TryGetValue("--probe-asio", out var path); path ??= options["--file"];
    try
    {
        using var locked = new FileStream(path + ".lock", FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None, 1, FileOptions.DeleteOnClose);
        if (probe) { await Task.Delay(100); Console.WriteLine("{\"event\":\"capabilities\",\"dsd_rates\":[64,128,256,512]}"); return 0; }
        Console.WriteLine("{\"event\":\"ready\"}");
        Console.WriteLine("{\"event\":\"position\",\"ms\":1200}");
        while (await Console.In.ReadLineAsync() is { } command)
        {
            if (command == "stop") { await File.WriteAllTextAsync(path + ".stopping", "stopping"); await Task.Delay(350); return 0; }
            Console.WriteLine(command == "pause" ? "{\"event\":\"paused\"}" : "{\"event\":\"playing\"}");
        }
        return 0;
    }
    catch (IOException) { Console.WriteLine("{\"event\":\"error\",\"message\":\"test device busy\"}"); return 1; }
}

namespace AMDownloader.WinUI.Services
{
    public sealed class RuntimePaths
    {
        public string AudioHost => Environment.ProcessPath!;
        public string Ffmpeg => "unused-by-fake-host";
    }
    public sealed class LibraryService
    {
        public TaskCompletionSource<string>? Preparation;
        public Task<string> PrepareAsync(Track track, CancellationToken cancel) => Preparation?.Task.WaitAsync(cancel) ?? Task.FromResult(track.Path);
        public Task<JsonElement> CallAsync(string action, Dictionary<string, object?> values, CancellationToken cancel) => Task.FromResult(JsonSerializer.SerializeToElement(new { duration = 600000, dsd = false, rate = 44100, channels = 2, bits = 16 }));
    }
}
