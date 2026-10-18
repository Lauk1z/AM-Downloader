using System.IO.Pipes;
using System.Security.Cryptography;
using System.Text;
using System.Runtime.InteropServices;

namespace AMDownloader.WinUI.Services;

public sealed class SingleInstance : IDisposable
{
    private readonly string name;
    private readonly Mutex mutex;
    private readonly CancellationTokenSource cancel = new();
    private bool owned;
    public event Action? Activated;
    public SingleInstance(string profile)
    {
        name = "AMDownloader.WinUI." + Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(Path.GetFullPath(profile).ToLowerInvariant())))[..24];
        mutex = new(false, @"Local\" + name);
    }
    public bool Acquire()
    {
        try { owned = mutex.WaitOne(0); } catch (AbandonedMutexException) { owned = true; }
        if (!owned)
        {
            using var client = new NamedPipeClientStream(".", name, PipeDirection.Out, PipeOptions.CurrentUserOnly);
            client.Connect(5000); if (GetNamedPipeServerProcessId(client.SafePipeHandle, out var server)) AllowSetForegroundWindow(server); client.WriteByte(1); return false;
        }
        _ = ListenAsync(); return true;
    }
    private async Task ListenAsync()
    {
        while (!cancel.IsCancellationRequested)
        {
            try
            {
                using var pipe = new NamedPipeServerStream(name, PipeDirection.In, 1, PipeTransmissionMode.Byte, PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
                await pipe.WaitForConnectionAsync(cancel.Token);
                var value = new byte[1]; await pipe.ReadExactlyAsync(value, cancel.Token); Activated?.Invoke();
            }
            catch (OperationCanceledException) { break; }
            catch (IOException) { }
        }
    }
    public void Dispose() { cancel.Cancel(); if (owned) mutex.ReleaseMutex(); mutex.Dispose(); cancel.Dispose(); }
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool GetNamedPipeServerProcessId(Microsoft.Win32.SafeHandles.SafePipeHandle pipe, out uint processId);
    [DllImport("user32.dll")] private static extern bool AllowSetForegroundWindow(uint processId);
}
