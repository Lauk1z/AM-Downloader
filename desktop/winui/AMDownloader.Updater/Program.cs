using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text.Json;
using AMDownloader.Core;
using Microsoft.Win32;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Length != 2 || args[0] != "--job") return 2;
        UpdateJob? job = null; UpdateTransaction? transaction = null; Process? launched = null; Mutex? gate = null; var ownsGate = false; var applied = false; var committed = false;
        try
        {
            job = UpdatePackage.ReadJob(args[1]); var work = UpdatePackage.JobDirectory(job.Id);
            var source = Path.TrimEndingDirectorySeparator(AppContext.BaseDirectory);
            if (!UpdatePackage.Within(source, Path.Combine(work, "payload")) || job.Id != args[1] || !ReleaseVersion.TryParse(job.Version, out _)) throw new InvalidDataException("更新任务来源无效。");
            var metadata = JsonSerializer.Deserialize<AppPackageVersion>(File.ReadAllText(Path.Combine(source, "app-version.json")), StateStore.Json);
            if (metadata?.Version != job.Version || metadata.UpdaterProtocol != 1) throw new InvalidDataException("更新版本校验失败。");
            gate = new Mutex(false, UpdatePackage.LockName(job.Target));
            try { ownsGate = gate.WaitOne(TimeSpan.FromMinutes(2)); } catch (AbandonedMutexException) { ownsGate = true; }
            if (!ownsGate) throw new IOException("另一项软件更新仍在进行，请稍后重新打开软件。");
            try
            {
                using var parent = Process.GetProcessById(job.ParentId);
                if (parent.StartTime.ToUniversalTime().Ticks == job.ParentStartedUtc && !parent.WaitForExit(120000)) throw new IOException("软件尚未退出，更新未应用。请正常退出后重试。");
            }
            catch (ArgumentException) { }
            transaction = new(source, job.Target, Path.Combine(work, "backup"), job.Profile); transaction.Apply(); applied = true;
            launched = Start(job, true); var ready = Path.Combine(work, "ready.json"); var clock = Stopwatch.StartNew(); var accepted = false;
            while (clock.Elapsed < TimeSpan.FromSeconds(45))
            {
                if (File.Exists(ready))
                {
                    try
                    {
                        using var document = JsonDocument.Parse(File.ReadAllText(ready));
                        accepted = document.RootElement.GetProperty("pid").GetInt32() == launched.Id && document.RootElement.GetProperty("version").GetString() == job.Version;
                        if (accepted) break;
                    }
                    catch (JsonException) { }
                }
                if (launched.HasExited) break;
                Thread.Sleep(100);
            }
            if (!accepted) throw new IOException("新版未能正常启动，已尝试恢复原版本。");
            committed = true;
            WriteResult(job, true, "软件已更新到 " + job.Version);
            try
            {
                using var key = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\AMDownloader.WinUI_is1", true);
                if (key?.GetValue("InstallLocation") is string location && Path.TrimEndingDirectorySeparator(Path.GetFullPath(location)).Equals(Path.TrimEndingDirectorySeparator(Path.GetFullPath(job.Target)), StringComparison.OrdinalIgnoreCase))
                    key.SetValue("DisplayVersion", job.Version);
            }
            catch (UnauthorizedAccessException) { }
            return 0;
        }
        catch (Exception error)
        {
            var message = error.Message;
            if (applied && !committed)
            {
                try { if (launched is { HasExited: false }) { launched.Kill(true); launched.WaitForExit(10000); } transaction!.Rollback(); }
                catch (Exception rollback) { message += "\n恢复原版本失败：" + rollback.Message; }
            }
            if (job is not null)
            {
                try { WriteResult(job, false, message); } catch (IOException) { }
                if (ownsGate && !committed)
                {
                    gate!.ReleaseMutex(); ownsGate = false;
                    try { using var restored = Start(job, false); } catch (Exception restart) { message += "\n请手动重新打开软件：" + restart.Message; }
                }
            }
            MessageBox(0, message, "AM Downloader 更新未完成", 0x10); return 1;
        }
        finally { launched?.Dispose(); if (ownsGate) gate!.ReleaseMutex(); gate?.Dispose(); }
    }
    private static Process Start(UpdateJob job, bool handshake)
    {
        var start = new ProcessStartInfo(Path.Combine(job.Target, "AM Downloader WinUI.exe")) { UseShellExecute = false, WorkingDirectory = job.Target };
        start.ArgumentList.Add("--data-dir"); start.ArgumentList.Add(job.Profile);
        if (job.NoBackend) start.ArgumentList.Add("--no-backend");
        if (handshake) { start.ArgumentList.Add("--update-job"); start.ArgumentList.Add(job.Id); }
        return Process.Start(start) ?? throw new IOException("无法启动软件。");
    }
    private static void WriteResult(UpdateJob job, bool success, string message)
    {
        var value = JsonSerializer.Serialize(new UpdateResult(job.Version, success, message, Environment.ProcessId), StateStore.Json);
        var work = UpdatePackage.JobDirectory(job.Id); File.WriteAllText(Path.Combine(work, "result.json"), value);
        var receipt = UpdatePackage.ProfileReceipt(job.Profile); File.WriteAllText(receipt + ".tmp", JsonSerializer.Serialize(new { job = job.Id, result = JsonSerializer.Deserialize<JsonElement>(value) }, StateStore.Json));
        File.Move(receipt + ".tmp", receipt, true);
    }
    [DllImport("user32.dll", EntryPoint = "MessageBoxW", CharSet = CharSet.Unicode)] private static extern int MessageBox(nint owner, string text, string caption, uint type);
}
