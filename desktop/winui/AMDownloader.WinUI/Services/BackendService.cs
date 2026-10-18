using System.Text.Json;
using AMDownloader.Core;

namespace AMDownloader.WinUI.Services;

public sealed class BackendService : IAsyncDisposable
{
    private readonly RuntimePaths paths;
    private readonly string state;
    private JsonProcess? process;
    private readonly SemaphoreSlim startup = new(1, 1);
    private TaskCompletionSource hello = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private bool disposed;
    public event Action<JsonElement>? Event;
    public event Action<string>? Log;
    public BackendService(RuntimePaths paths, string state) { this.paths = paths; this.state = state; }
    public async Task SendAsync(object command)
    {
        await startup.WaitAsync();
        try
        {
          ObjectDisposedException.ThrowIf(disposed, this);
          if (process is null || process.HasExited)
          {
            if (process is not null) await process.DisposeAsync();
            var greeting = hello = new(TaskCreationOptions.RunContinuationsAsynchronously);
            var current = process = new(paths.Python, ["-u", Path.Combine(paths.Resources, "musicdesk_worker.py"), "--root", paths.Bundle, "--state-root", state], state, Path.Combine(paths.Bundle, "deps"));
            current.Event += value => { if (current != process) return; if (value.GetProperty("event").GetString() == "hello") greeting.TrySetResult(); Event?.Invoke(value); };
            current.Log += text => { if (current == process) Log?.Invoke(text); };
            current.Disconnected += code => { greeting.TrySetException(new IOException("下载后端已退出。")); if (current == process) Event?.Invoke(JsonSerializer.SerializeToElement(new { @event = "disconnected", code })); };
            current.StartReading();
          }
          await hello.Task.WaitAsync(TimeSpan.FromSeconds(60));
          await process.SendAsync(command);
        }
        finally { startup.Release(); }
    }
    public async Task RestartAsync()
    {
        await startup.WaitAsync();
        try { var old = process; process = null; if (old is not null) await old.DisposeAsync(); }
        finally { startup.Release(); }
        await SendAsync(new { action = "start" });
    }
    public async ValueTask DisposeAsync()
    {
        await startup.WaitAsync();
        try { disposed = true; var old = process; process = null; if (old is not null) await old.DisposeAsync(); }
        finally { startup.Release(); }
    }
}
