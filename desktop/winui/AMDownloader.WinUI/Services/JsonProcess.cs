using System.Collections.Concurrent;
using System.Diagnostics;
using System.Text;
using System.Text.Json;
using AMDownloader.Core;

namespace AMDownloader.WinUI.Services;

public sealed class JsonProcess : IAsyncDisposable
{
    private readonly Process process;
    private readonly SemaphoreSlim writeLock = new(1, 1);
    private static readonly JsonSerializerOptions WireJson = new(StateStore.Json) { WriteIndented = false };
    private readonly ConcurrentDictionary<string, TaskCompletionSource<JsonElement>> requests = new();
    private Task reader = Task.CompletedTask;
    private Task errors = Task.CompletedTask;
    public event Action<JsonElement>? Event;
    public event Action<string>? Log;
    public event Action<int>? Disconnected;
    public bool HasExited => process.HasExited;
    public JsonProcess(string executable, IEnumerable<string> arguments, string workingDirectory, string? dependencyPath = null)
    {
        var info = new ProcessStartInfo(executable) { WorkingDirectory = workingDirectory, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
            StandardInputEncoding = new UTF8Encoding(false), StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8 };
        foreach (var argument in arguments) info.ArgumentList.Add(argument);
        info.Environment["PYTHONIOENCODING"] = "utf-8"; info.Environment["PYTHONUNBUFFERED"] = "1"; info.Environment["PYTHONDONTWRITEBYTECODE"] = "1";
        if (dependencyPath is not null) info.Environment["PATH"] = dependencyPath + Path.PathSeparator + Environment.GetEnvironmentVariable("PATH");
        process = Process.Start(info) ?? throw new InvalidOperationException("无法启动组件：" + executable);
    }
    public void StartReading()
    {
        reader = ReadAsync();
        errors = ReadErrorsAsync();
    }
    private async Task ReadErrorsAsync()
    { try { while (await process.StandardError.ReadLineAsync() is { } line) Log?.Invoke(Text.Redact(line)); } catch (IOException error) { Log?.Invoke(Text.Redact(error.Message)); } }
    private async Task ReadAsync()
    {
        try
        {
            while (await process.StandardOutput.ReadLineAsync() is { } line)
            {
                JsonElement value;
                try { using var document = JsonDocument.Parse(line); value = document.RootElement.Clone(); }
                catch (JsonException) { Log?.Invoke(Text.Redact(line)); continue; }
                if (value.TryGetProperty("id", out var id) && requests.TryRemove(id.GetString()!, out var completion))
                {
                    if (value.TryGetProperty("error", out var error)) completion.TrySetException(new InvalidOperationException(error.GetString()));
                    else completion.TrySetResult(value.GetProperty("result"));
                }
                else Event?.Invoke(value);
            }
            await process.WaitForExitAsync();
        }
        catch (IOException error) { Log?.Invoke(Text.Redact(error.Message)); }
        finally
        {
            foreach (var entry in requests) entry.Value.TrySetException(new IOException("组件连接已关闭。"));
            requests.Clear(); Disconnected?.Invoke(process.HasExited ? process.ExitCode : -1);
        }
    }
    public async Task SendAsync(object command)
    {
        await writeLock.WaitAsync();
        try { await process.StandardInput.WriteLineAsync(JsonSerializer.Serialize(command, WireJson)); await process.StandardInput.FlushAsync(); }
        finally { writeLock.Release(); }
    }
    public async Task<JsonElement> RequestAsync(Dictionary<string, object?> command, CancellationToken cancellation = default)
    {
        var id = Guid.NewGuid().ToString("N"); command["id"] = id;
        var completion = new TaskCompletionSource<JsonElement>(TaskCreationOptions.RunContinuationsAsynchronously); requests[id] = completion;
        using var registration = cancellation.Register(() => { if (requests.TryRemove(id, out var pending)) { pending.TrySetCanceled(cancellation); _ = CancelRequestAsync(id); } });
        try { cancellation.ThrowIfCancellationRequested(); await SendAsync(command); return await completion.Task; }
        catch { requests.TryRemove(id, out _); throw; }
    }
    private async Task CancelRequestAsync(string id)
    { try { await SendAsync(new { action = "cancel", target = id }); } catch (IOException) { } catch (ObjectDisposedException) { } }
    public async ValueTask DisposeAsync()
    {
        if (!process.HasExited)
        {
            try { await SendAsync(new { action = "stop" }); process.StandardInput.Close(); }
            catch (IOException) { }
            var exit = process.WaitForExitAsync();
            if (await Task.WhenAny(exit, Task.Delay(20000)) != exit) process.Kill(true);
            await process.WaitForExitAsync();
        }
        await Task.WhenAll(reader, errors); process.Dispose();
    }
}
