using System.Diagnostics;
using System.Text.Json;
using System.Text.RegularExpressions;
using AMDownloader.Core;
using AMDownloader.WinUI.Views;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;

namespace AMDownloader.WinUI;

public sealed partial class MainWindow
{
    private UpdateClient updateClient = new();
    private AvailableUpdate? availableUpdate;
    private Button? updateBadge, updateCheckButton;
    private TextBlock? updateStatusText;
    private bool checkingUpdates, updateRunning, updateOfferOpen;
    private CancellationTokenSource? updateCancellation, updateCheckCancellation;
    private string updateStatus = "";
    private UIElement BuildUpdateSettings()
    {
        var section = Ui.Stack(12); section.Children.Add(Ui.Text("软件更新", 23, true));
        var version = Ui.Text("当前版本：" + ReleaseVersion.Current); version.Name = "UpdateVersion"; section.Children.Add(version);
        var auto = Ui.Combo(new[] { ("自动检查更新", (object)true), ("不检查更新", (object)false) }, Store.Get("auto_check_updates", true)); auto.Name = "AutomaticUpdateCheck";
        AutomationProperties.SetName(auto, "自动检查软件更新");
        auto.SelectionChanged += (_, _) =>
        {
            var enabled = Ui.Selected<bool>(auto); if (Store.Get("auto_check_updates", true) == enabled) return;
            Store.Set("auto_check_updates", enabled); if (!enabled) updateCheckCancellation?.Cancel(); UpdateUpdateBadge();
            if (enabled && !options.NoBackend && options.Smoke is null) _ = CheckSoftwareUpdatesAsync(true);
        };
        section.Children.Add(auto);
        updateCheckButton = Ui.Button("检查更新", () => _ = CheckSoftwareUpdatesAsync(false), true, "refresh"); updateCheckButton.Name = "CheckForUpdates"; updateCheckButton.IsEnabled = !checkingUpdates && !updateRunning; section.Children.Add(updateCheckButton);
        updateStatusText = Ui.Text(updateStatus.Length > 0 ? updateStatus : "自动检查仅显示提醒；确认后才会下载更新并重启软件。", 12, color: Ui.Muted); section.Children.Add(updateStatusText);
        return section;
    }
    private void UpdateUpdateBadge()
    {
        if (updateBadge is null) return;
        updateBadge.Visibility = availableUpdate is not null && Store.Get("auto_check_updates", true) ? Visibility.Visible : Visibility.Collapsed;
        var message = availableUpdate is null ? "检查软件更新" : "发现新版本 " + availableUpdate.Version;
        ToolTipService.SetToolTip(updateBadge, message); AutomationProperties.SetName(updateBadge, message);
    }
    private async Task CheckSoftwareUpdatesAsync(bool automatic)
    {
        if (checkingUpdates || updateRunning || quitting) return;
        checkingUpdates = true; if (updateCheckButton is not null) updateCheckButton.IsEnabled = false;
        updateCheckCancellation = new(); SetUpdateStatus("正在检查更新…");
        try
        {
            if (!ReleaseVersion.TryParse(ReleaseVersion.Current, out var current)) throw new InvalidOperationException("当前版本信息无效。");
            availableUpdate = await updateClient.CheckAsync(current, updateCheckCancellation.Token); UpdateUpdateBadge();
            SetUpdateStatus(availableUpdate is null ? "已为最新版本 · " + current : "发现新版本 · " + availableUpdate.Version);
            if (!automatic && !quitting)
            {
                if (availableUpdate is null) await ShowDialogAsync("已为最新版本", Ui.Text("当前版本：" + current), "确认", close: "");
                else await OfferUpdateAsync();
            }
        }
        catch (OperationCanceledException) when (updateCheckCancellation.IsCancellationRequested) { SetUpdateStatus("已取消自动检查更新。"); }
        catch (Exception error)
        {
            SetUpdateStatus("暂时无法检查更新，请稍后重试。");
            if (!automatic && !quitting) await ShowDialogAsync("检查更新失败", Ui.Text(error is OperationCanceledException ? "检查更新超时，请稍后再试。" : error.Message), "确认", close: "");
        }
        finally { checkingUpdates = false; updateCheckCancellation.Dispose(); updateCheckCancellation = null; if (updateCheckButton is not null) updateCheckButton.IsEnabled = !updateRunning; }
    }
    private async Task OfferUpdateAsync()
    {
        if (availableUpdate is not { } update || updateOfferOpen || updateRunning || quitting) return;
        updateOfferOpen = true;
        try
        {
            var body = Ui.Stack(12); body.Width = 480;
            body.Children.Add(Ui.Text("当前版本：" + ReleaseVersion.Current)); body.Children.Add(Ui.Text("更新版本：" + update.Version, 18, true, Ui.Accent));
            var notes = Ui.Scroll(Ui.Text(NotesText(update.Notes), 14)); notes.MaxHeight = 320; body.Children.Add(notes);
            body.Children.Add(Ui.Text("确认后将下载更新，完成后自动重启软件。", 12, color: Ui.Muted));
            if (await ShowDialogAsync("发现新版本", body, "确认") == ContentDialogResult.Primary) await InstallUpdateAsync(update);
        }
        finally { updateOfferOpen = false; }
    }
    private static string NotesText(string source)
    {
        if (string.IsNullOrWhiteSpace(source)) return "该版本未提供更新说明。";
        var text = Regex.Replace(source, @"!\[[^\]]*\]\([^)]*\)", "");
        text = Regex.Replace(text, @"\[([^\]]+)\]\([^)]*\)", "$1");
        text = Regex.Replace(text, @"(?m)^#{1,6}\s+", "");
        return text.Replace("**", "").Replace("```text", "").Replace("```", "").Replace("`", "").Trim();
    }
    private void SetUpdateStatus(string message) { updateStatus = message; if (updateStatusText is not null) updateStatusText.Text = message; }
    private async Task InstallUpdateAsync(AvailableUpdate update)
    {
        if (updateRunning || quitting) return;
        var target = Path.TrimEndingDirectorySeparator(AppContext.BaseDirectory);
        if (!File.Exists(Path.Combine(target, "manifest.sha256.json"))) { await ShowDialogAsync("无法自动更新", Ui.Text("当前是开发运行目录，请使用完整发行版进行软件内更新。"), "确认", close: ""); return; }
        try
        {
            var probe = Path.Combine(target, ".update-write-" + Guid.NewGuid().ToString("N"));
            using (File.Create(probe)) { } File.Delete(probe);
        }
        catch (Exception error) { await ShowDialogAsync("无法自动更新", Ui.Text("当前安装目录无法写入：" + error.Message), "确认", close: ""); return; }
        SetPlayerView(PlayerViewMode.Library); updateRunning = true; updateCancellation = new(); var cancel = updateCancellation; var id = Guid.NewGuid().ToString("N"); var work = UpdatePackage.JobDirectory(id); var handedOff = false; string? failure = null;
        if (updateCheckButton is not null) updateCheckButton.IsEnabled = false;
        await dialogs.WaitAsync();
        try
        {
            var content = Ui.Stack(14); content.Width = 410;
            var label = Ui.Text("正在下载更新…"); var bar = new ProgressBar { Minimum = 0, Maximum = 100, Value = 0, Foreground = Ui.Accent, Name = "UpdateProgress" };
            var detail = Ui.Text("", 12, color: Ui.Muted); content.Children.Add(label); content.Children.Add(bar); content.Children.Add(detail);
            var dialog = activeDialog = new ContentDialog { XamlRoot = root.XamlRoot, Title = "正在更新", Content = content, CloseButtonText = "取消" };
            Ui.UseAccentResources(dialog); dialog.Closing += (_, _) => { if (!handedOff) cancel.Cancel(); };
            var showing = dialog.ShowAsync().AsTask();
            var progress = new Progress<UpdateProgress>(value =>
            {
                label.Text = value.Stage; bar.Value = Math.Clamp(value.Fraction * 100, 0, 100);
                detail.Text = value.Total > 0 ? $"{value.Downloaded / 1048576d:F1} / {value.Total / 1048576d:F1} MiB" : $"{bar.Value:F0}%";
            });
            try
            {
                var archive = await updateClient.DownloadAsync(update, work, progress, cancel.Token);
                var source = await UpdatePackage.ExtractAsync(archive, work, update.Version.ToString(), progress, cancel.Token);
                cancel.Token.ThrowIfCancellationRequested();
                using var current = Process.GetCurrentProcess();
                UpdatePackage.WriteJob(work, new(id, target, Store.DirectoryPath, update.Version.ToString(), current.Id, current.StartTime.ToUniversalTime().Ticks, options.NoBackend));
                var start = new ProcessStartInfo(Path.Combine(source, "AMDownloader.Updater.exe")) { UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = source };
                start.ArgumentList.Add("--job"); start.ArgumentList.Add(id);
                using var host = Process.Start(start) ?? throw new IOException("无法启动更新程序。");
                handedOff = true; label.Text = "正在重启并完成更新…"; bar.Value = 100;
            }
            catch (OperationCanceledException) when (cancel.IsCancellationRequested) { SetUpdateStatus("更新已取消。"); }
            catch (Exception error) { failure = error is OperationCanceledException ? "更新下载超时，请稍后重试。" : error.Message; SetUpdateStatus("更新未完成，可重新尝试。"); }
            finally { dialog.Hide(); await showing; }
        }
        finally
        {
            activeDialog = null; dialogs.Release(); updateRunning = false; updateCancellation.Dispose(); updateCancellation = null;
            if (updateCheckButton is not null) updateCheckButton.IsEnabled = !checkingUpdates;
            if (!handedOff && Directory.Exists(work)) { try { Directory.Delete(work, true); } catch (IOException) { } }
        }
        if (handedOff) await ExitAsync();
        else if (failure is not null && !quitting) await ShowDialogAsync("更新失败", Ui.Text(failure), "确认", close: "");
    }
    private async Task FinishUpdateAsync()
    {
        try
        {
            var receipt = UpdatePackage.ProfileReceipt(Store.DirectoryPath);
            if (options.UpdateJob is not null) for (var attempt = 0; attempt < 50 && !File.Exists(receipt); ++attempt) await Task.Delay(100);
            if (!File.Exists(receipt)) return;
            using var doc = JsonDocument.Parse(await File.ReadAllTextAsync(receipt)); var id = doc.RootElement.GetProperty("job").GetString()!;
            var job = UpdatePackage.ReadJob(id); var result = doc.RootElement.GetProperty("result").Deserialize<UpdateResult>(StateStore.Json)!;
            if (!Path.TrimEndingDirectorySeparator(Path.GetFullPath(job.Target)).Equals(Path.TrimEndingDirectorySeparator(AppContext.BaseDirectory), StringComparison.OrdinalIgnoreCase) || !Path.GetFullPath(job.Profile).Equals(Path.GetFullPath(Store.DirectoryPath), StringComparison.OrdinalIgnoreCase)) return;
            Toast(result.Message); File.Delete(receipt);
            if (!result.Success || result.Version != ReleaseVersion.Current) return;
            await Task.Run(async () =>
            {
                try { using var updater = Process.GetProcessById(result.UpdaterId); await updater.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(15)); } catch (ArgumentException) { }
                var work = UpdatePackage.JobDirectory(id);
                var payload = Path.Combine(work, "payload"); if (Directory.Exists(payload)) Directory.Delete(payload, true);
                var archive = Path.Combine(work, "package.zip"); if (File.Exists(archive)) File.Delete(archive);
            });
        }
        catch (Exception error) { Log("更新记录处理失败：" + error.Message); }
    }
}
