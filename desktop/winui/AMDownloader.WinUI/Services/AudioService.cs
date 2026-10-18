using System.Diagnostics;
using System.Globalization;
using System.Text;
using System.Text.Json;
using AMDownloader.Core;

namespace AMDownloader.WinUI.Services;

public sealed class AudioService : IAsyncDisposable
{
    private readonly RuntimePaths paths;
    private readonly LibraryService library;
    private readonly Action<Action> dispatch;
    private Process? host;
    private Task hostReader = Task.CompletedTask, hostErrors = Task.CompletedTask;
    private readonly SemaphoreSlim outputGate = new(1);
    private CancellationTokenSource prepare = new();
    private long generation;
    private string source = "";
    private JsonElement info;
    public bool PrepareAutoplay { get; private set; }
    public OutputConfig Config { get; private set; }
    public Track? Current { get; private set; }
    public long Position { get; private set; }
    public long Duration { get; private set; }
    public string State { get; private set; } = "stopped";
    public bool Preparing { get; private set; }
    public int Volume { get; private set; }
    public JsonElement? Negotiated { get; private set; }
    public string Error { get; private set; } = "";
    public event Action? Changed;
    public event Action? Ended;
    public event Action<string>? Failed;
    public AudioService(RuntimePaths paths, LibraryService library, StateStore store, Action<Action> dispatch)
    { this.paths = paths; this.library = library; this.dispatch = dispatch; Config = store.Get("audio_output", new OutputConfig()); Volume = store.Get("volume", 65); }
    public async Task LoadAsync(Track? track, bool autoplay)
    {
        prepare.Cancel(); prepare.Dispose(); prepare = new(); var cancel = prepare.Token;
        var version = ++generation;
        await outputGate.WaitAsync();
        try
        {
            await StopHostAsync();
            if (version != generation) return;
            Current = track; Position = 0; Duration = (long)((track?.Duration ?? 0) * 1000); source = ""; Error = ""; State = "stopped"; Negotiated = null;
            Preparing = track is not null; PrepareAutoplay = autoplay; Changed?.Invoke();
        }
        finally { outputGate.Release(); }
        if (track is null) return;
        try
        {
            var file = await library.PrepareAsync(track, cancel);
            var format = await library.CallAsync("info", new() { ["path"] = file }, cancel);
            if (version != generation) return;
            source = file; info = format; Duration = info.GetProperty("duration").GetInt64(); Preparing = false; Changed?.Invoke();
            if (PrepareAutoplay) await PlayAsync();
        }
        catch (OperationCanceledException) { }
        catch (Exception error) { if (version == generation) Fail(error.Message); }
    }
    public void TogglePrepareAutoplay() { PrepareAutoplay = !PrepareAutoplay; Changed?.Invoke(); }
    public async Task PlayAsync()
    {
        var version = generation;
        await outputGate.WaitAsync();
        try { if (version == generation) await StartHostAsync(); }
        finally { outputGate.Release(); }
    }
    private async Task StartHostAsync()
    {
        if (Preparing || source.Length == 0) return;
        if (host is { HasExited: false }) { await CommandAsync("resume"); return; }
        var requestedGeneration = generation;
        await StopHostAsync();
        if (requestedGeneration != generation || source.Length == 0) return;
        if (Position >= Duration) Position = 0;
        var mode = Config.Mode; var dsd = info.GetProperty("dsd").GetBoolean();
        var format = !dsd || mode == "shared" ? "pcm" : Config.Dsd switch { "native" => "dsd", "dop" => "dop", _ => "pcm" };
        if (mode != "shared" && Config.Device.Length == 0) { Fail("请选择音频输出设备。"); return; }
        if (format == "dsd" && mode != "asio") { Fail("原生 DSD 需要 ASIO；WASAPI 请选 DoP 或共享解码。"); return; }
        if (dsd && format == "pcm" && mode != "shared") { Fail("DSD 转 PCM 请使用系统共享模式；独占模式请选择原生 DSD 或 DoP。"); return; }
        var rate = info.GetProperty("rate").GetInt32(); var channels = info.GetProperty("channels").GetInt32();
        if (mode == "shared" && dsd) rate = 176400;
        var args = new[] { "--mode", mode, "--format", format, "--device", Config.Device, "--file", source,
            "--rate", rate.ToString(), "--channels", channels.ToString(), "--bits", Math.Min(32, info.GetProperty("bits").GetInt32()).ToString(),
            "--ffmpeg", paths.Ffmpeg, "--position", Position.ToString(), "--volume", (Volume / 100d).ToString(CultureInfo.InvariantCulture) };
        try
        {
            var start = new ProcessStartInfo(paths.AudioHost) { UseShellExecute = false, CreateNoWindow = true, RedirectStandardInput = true,
                RedirectStandardOutput = true, RedirectStandardError = true, StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8 };
            foreach (var arg in args) start.ArgumentList.Add(arg);
            host = Process.Start(start)!; State = "starting"; Error = ""; Changed?.Invoke();
            var process = host; var version = generation;
            var started = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            hostReader = ReadHostAsync(process, version, started);
            hostErrors = process.StandardError.ReadToEndAsync();
            if (!await started.Task.WaitAsync(TimeSpan.FromSeconds(20))) await StopHostAsync();
        }
        catch (Exception error) { await StopHostAsync(); Fail(error is TimeoutException ? "音频驱动启动超时，请检查设备连接及其他程序占用。" : error.Message); }
    }
    private async Task ReadHostAsync(Process process, long version, TaskCompletionSource<bool> started)
    {
        bool ended = false, failed = false;
        try
        {
          while (await process.StandardOutput.ReadLineAsync() is { } line)
          {
            JsonElement value;
            try { using var document = JsonDocument.Parse(line); value = document.RootElement.Clone(); } catch (JsonException) { continue; }
            var kind = value.GetProperty("event").GetString();
            if (kind == "end") ended = true;
            if (kind == "error") failed = true;
            dispatch(() =>
            {
                if (version != generation || process != host) { started.TrySetResult(false); return; }
                switch (kind)
                {
                    case "ready": Negotiated = value; State = "playing"; break;
                    case "position": Position = Math.Min(Duration, value.GetProperty("ms").GetInt64()); break;
                    case "paused": State = "paused"; break;
                    case "playing": State = "playing"; break;
                    case "error": Fail(value.GetProperty("message").GetString()!); break;
                    case "end": Position = Duration; State = "stopped"; Negotiated = null; Ended?.Invoke(); break;
                }
                Changed?.Invoke();
                if (kind is "ready" or "error") started.TrySetResult(kind == "ready");
            });
          }
          await process.WaitForExitAsync();
        }
        catch (IOException error) { dispatch(() => { if (version == generation && process == host) Fail(error.Message); }); failed = true; }
        dispatch(() => { if (version == generation && process == host && !ended && !failed && State is "playing" or "starting") Fail("音频输出进程退出；请检查设备连接或驱动占用。"); started.TrySetResult(false); });
    }
    public async Task PauseAsync()
    {
        await outputGate.WaitAsync();
        try { if (host is { HasExited: false }) await CommandAsync("pause"); }
        finally { outputGate.Release(); }
    }
    public async Task SeekAsync(long position)
    {
        if (Preparing || Current is null) return;
        var playing = State is "playing" or "starting";
        var requestedGeneration = ++generation; await outputGate.WaitAsync();
        try
        {
            await StopHostAsync();
            if (requestedGeneration != generation) return;
            Position = Math.Clamp(position, 0, Duration); State = "paused"; Negotiated = null; Changed?.Invoke();
            if (playing) await StartHostAsync();
        }
        finally { outputGate.Release(); }
    }
    public async Task ConfigureAsync(OutputConfig config)
    {
        await outputGate.WaitAsync();
        var previous = Config;
        try
        {
            if (Preparing) { Config = config; Changed?.Invoke(); return; }
            var playing = State is "playing" or "starting";
            var requestedGeneration = ++generation; await StopHostAsync();
            if (requestedGeneration != generation) return;
            Config = config; Error = ""; State = Current is null ? "stopped" : "paused"; Negotiated = null; Changed?.Invoke();
            if (playing)
            {
                await StartHostAsync();
                if (Error.Length > 0) throw new InvalidOperationException(Error);
            }
        }
        catch { Config = previous; Changed?.Invoke(); throw; }
        finally { outputGate.Release(); }
    }
    public async Task<List<JsonElement>> ProbeAsioAsync(string device)
    {
        PrepareAutoplay = false;
        await outputGate.WaitAsync();
        try
        {
            await StopHostAsync();
            State = Current is null ? "stopped" : "paused"; Negotiated = null; Changed?.Invoke();
            return await InspectAsync(paths.AudioHost, "--probe-asio", device);
        }
        finally { outputGate.Release(); }
    }
    public async Task SetVolumeAsync(int value)
    { Volume = Math.Clamp(value, 0, 100); if (Config.Mode == "shared" && host is { HasExited: false }) await CommandAsync("volume " + (Volume / 100d).ToString(CultureInfo.InvariantCulture)); Changed?.Invoke(); }
    private async Task CommandAsync(string command)
    {
        if (host is not { HasExited: false }) return;
        try { await host.StandardInput.WriteLineAsync(command); await host.StandardInput.FlushAsync(); }
        catch (IOException error) { Fail(error.Message); }
    }
    private async Task StopHostAsync()
    {
        var process = host; var reader = hostReader; var errors = hostErrors; host = null;
        hostReader = hostErrors = Task.CompletedTask;
        if (process is null) return;
        if (!process.HasExited)
        {
            try { await process.StandardInput.WriteLineAsync("stop"); await process.StandardInput.FlushAsync(); } catch (IOException) { }
            await Task.WhenAny(process.WaitForExitAsync(), Task.Delay(1500));
            if (!process.HasExited) process.Kill(true);
            await process.WaitForExitAsync();
        }
        await Task.WhenAll(reader, errors); process.Dispose();
    }
    private void Fail(string message) { Error = message; State = "stopped"; Preparing = false; Negotiated = null; Failed?.Invoke(message); Changed?.Invoke(); }
    public static async Task<List<JsonElement>> InspectAsync(string executable, params string[] args)
    {
        var start = new ProcessStartInfo(executable) { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true, StandardOutputEncoding = Encoding.UTF8 };
        foreach (var arg in args) start.ArgumentList.Add(arg);
        using var process = Process.Start(start)!;
        var output = process.StandardOutput.ReadToEndAsync(); var error = process.StandardError.ReadToEndAsync();
        try { await process.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(20)); }
        catch (TimeoutException) { if (!process.HasExited) process.Kill(true); await process.WaitForExitAsync(); throw; }
        var values = new List<JsonElement>();
        foreach (var line in (await output).Split('\n', StringSplitOptions.RemoveEmptyEntries)) { using var document = JsonDocument.Parse(line); values.Add(document.RootElement.Clone()); }
        if (process.ExitCode != 0) throw new InvalidOperationException(values.Count > 0 && values[0].TryGetProperty("message", out var message) ? message.GetString() : await error);
        return values;
    }
    public async ValueTask DisposeAsync()
    {
        prepare.Cancel(); ++generation; await outputGate.WaitAsync();
        try { await StopHostAsync(); prepare.Dispose(); }
        finally { outputGate.Release(); }
    }
}
