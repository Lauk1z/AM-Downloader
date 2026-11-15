using System.Net;
using System.Security.Cryptography;
using System.Text.Json;
using AMDownloader.Core;
using AMDownloader.WinUI.Views;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media.Imaging;

namespace AMDownloader.WinUI;

public sealed partial class MainWindow
{
    private async Task<object> VerifyUpdateUiAsync(string folder)
    {
        var savedClient = updateClient; var savedAuto = Store.Get("auto_check_updates", true); var savedOffer = availableUpdate; var response = "[]"; var fail = false;
        var download = Enumerable.Repeat((byte)93, 1024 * 1024).ToArray();
        using var http = new HttpClient(new UpdateTestHandler(async (request, cancel) =>
        {
            if (fail) return new(HttpStatusCode.ServiceUnavailable);
            if (request.RequestUri!.Host == "api.github.com") return new(HttpStatusCode.OK) { Content = new StringContent(response) };
            await Task.Delay(300, cancel);
            return new(HttpStatusCode.OK) { Content = new StreamContent(new UpdateTestStream(download)) };
        }));
        updateClient = new(http); Store.Set("auto_check_updates", true); Navigate("settings");
        try
        {
            var task = CheckSoftwareUpdatesAsync(false); await Dialog("已为最新版本");
            Check(activeDialog!.Content is TextBlock text && text.Text.Contains(ReleaseVersion.Current) && activeDialog.PrimaryButtonText == "确认" && activeDialog.CloseButtonText.Length == 0, "最新版本弹窗信息不完整");
            await Capture("update-latest"); activeDialog.Hide(); await task;
            var version = "9.0.0-preview.1"; var hash = Convert.ToHexString(SHA256.HashData(download)).ToLowerInvariant();
            response = JsonSerializer.Serialize(new[] { new { tag_name = "v" + version, draft = false, prerelease = true, body = "## 更新内容\n- 小窗和全屏播放\n- 软件内更新\n- 保留资料库和账号设置", assets = new[] { new { name = $"AM-Downloader-{version}-WinUI3-Windows-x64.zip", state = "uploaded", size = download.Length, digest = "sha256:" + hash, browser_download_url = $"https://github.com/{UpdateClient.Repository}/releases/download/v{version}/AM-Downloader-{version}-WinUI3-Windows-x64.zip" } } } });
            await CheckSoftwareUpdatesAsync(true); root.UpdateLayout();
            Check(activeDialog is null && availableUpdate?.Version.ToString() == version && updateBadge!.Visibility == Visibility.Visible && updateBadge.ActualWidth == updateBadge.ActualHeight && updateBadge.CornerRadius.TopLeft == 14, "自动检查未显示圆形提示或擅自弹窗");
            Check(updateBadge!.Background == Ui.Accent, "更新图标不是主题色");
            Navigate("home"); await Capture("update-badge"); task = OfferUpdateAsync(); await Dialog("发现新版本"); await Capture("update-offer"); activeDialog!.Hide(); await task;
            Check(!updateRunning, "取消更新确认后仍开始下载");
            Navigate("settings"); await Task.Delay(250); root.UpdateLayout(); var automatic = FindElement<ComboBox>(pageHost, "AutomaticUpdateCheck")!; automatic.SelectedIndex = 1;
            Check(!Store.Get("auto_check_updates", true) && updateBadge.Visibility == Visibility.Collapsed, "关闭自动更新未保存或提示未隐藏");
            fail = true; task = CheckSoftwareUpdatesAsync(false); await Dialog("检查更新失败"); activeDialog!.Hide(); await task; fail = false;
            var cancelledDownload = false;
            if (File.Exists(Path.Combine(AppContext.BaseDirectory, "manifest.sha256.json")))
            {
                task = InstallUpdateAsync(availableUpdate!); await Dialog("正在更新");
                var progressBar = FindElement<ProgressBar>(activeDialog!, "UpdateProgress")!; await Until(() => progressBar.Value > 0, 5000);
                Check(progressBar.Foreground == Ui.Accent && progressBar.Value < 85, "更新下载进度错误"); await Capture("update-progress"); activeDialog!.Hide(); await task;
                Check(!updateRunning && !quitting && updateStatus.Contains("取消"), "取消下载退出了应用或没有停止"); cancelledDownload = true;
            }
            return new { updateUi = "version,notes,confirm,cancel,rose-badge,automatic-preference,network-error", cancelledDownload, ok = true };
        }
        finally { updateClient.Dispose(); updateClient = savedClient; availableUpdate = savedOffer; Store.Set("auto_check_updates", savedAuto); UpdateUpdateBadge(); updateStatus = ""; Navigate("home"); }
        void Check(bool condition, string message) { if (!condition) throw new InvalidOperationException(message); }
        async Task Dialog(string title) { await Until(() => Equals(activeDialog?.Title, title), 4000); await Task.Delay(150); }
        async Task Capture(string name) { var image = new RenderTargetBitmap(); await image.RenderAsync(activeDialog ?? (UIElement)root); await SaveScreenshotAsync(image, Path.Combine(folder, name + ".png")); }
    }
    private sealed class UpdateTestHandler(Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> action) : HttpMessageHandler
    { protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancel) => action(request, cancel); }
    private sealed class UpdateTestStream(byte[] bytes) : MemoryStream(bytes)
    {
        public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancel = default)
        { await Task.Delay(100, cancel); return await base.ReadAsync(buffer[..Math.Min(buffer.Length, 32768)], cancel); }
    }
}
