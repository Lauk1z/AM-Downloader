using System.Runtime.InteropServices.WindowsRuntime;
using System.Text.Json;
using AMDownloader.Core;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.Graphics.Imaging;
using Windows.Storage;
using AMDownloader.WinUI.Views;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Automation.Peers;
using Microsoft.UI.Xaml.Automation.Provider;
using System.Diagnostics;
using System.Runtime.InteropServices;

namespace AMDownloader.WinUI;

public sealed partial class MainWindow
{
    private async Task RunSmokeAsync(string report)
    {
        var checks = new List<object>(); var folder = Path.GetDirectoryName(Path.GetFullPath(report))!; Directory.CreateDirectory(folder);
        try
        {
            var runtime = typeof(object).Assembly.Location; var xaml = Process.GetCurrentProcess().Modules.Cast<ProcessModule>().First(x => x.ModuleName.Equals("Microsoft.UI.Xaml.dll", StringComparison.OrdinalIgnoreCase)).FileName;
            Check(runtime.StartsWith(AppContext.BaseDirectory, StringComparison.OrdinalIgnoreCase) && xaml.StartsWith(AppContext.BaseDirectory, StringComparison.OrdinalIgnoreCase), "未使用包内独立运行时");
            var theme = Application.Current.Resources;
            Check(theme.MergedDictionaries.OfType<XamlControlsResources>().Any() && theme.TryGetValue("AccentFillColorDefaultBrush", out var accent) && accent is SolidColorBrush brush && brush.Color == Windows.UI.Color.FromArgb(255, 255, 53, 101), "应用 XAML 主题资源未加载");
            checks.Add(new { runtime, xaml, resources = Paths.Resources, audioHost = Paths.AudioHost, python = Paths.Python, applicationTheme = true });
            checks.Add(await VerifyThemeUiAsync(folder));
            checks.Add(await VerifyIconsUiAsync(folder));
            checks.Add(await VerifyPageUiAsync(folder));
            checks.Add(await VerifyAudioSettingsUiAsync());
            var initialQueue = queue.Select(x => x.Path).ToList(); var initialTrack = Audio.Current?.Path;
            var pages = new List<string> { "home", "recent", "artists", "albums", "songs", "favourites", "queue", "settings", "search" };
            if (tracks.Count > 0) pages.Add("album:" + tracks[0].AlbumKey);
            if (playlists.Count > 0) pages.Add(playlists[0].Id);
            foreach (var target in pages)
            {
                Navigate(target); await Task.Delay(400); root.UpdateLayout();
                if (root.ActualWidth <= 0 || pageHost.ActualHeight <= 0) throw new InvalidOperationException("页面未形成有效布局：" + target);
                var bitmap = new RenderTargetBitmap(); await bitmap.RenderAsync(root);
                checks.Add(new { page = target, width = bitmap.PixelWidth, height = bitmap.PixelHeight });
                var name = target.StartsWith("album:") ? "album" : target.StartsWith("playlist:") ? "playlist" : target;
                await SaveScreenshotAsync(bitmap, Path.Combine(folder, name + ".png"));
            }
            var originalSize = AppWindow.Size; var scale = root.XamlRoot.RasterizationScale;
            Navigate("artists"); AppWindow.Resize(new Windows.Graphics.SizeInt32((int)(1100 * scale), (int)(720 * scale))); await Task.Delay(350);
            TogglePanel("lyrics"); await Task.Delay(400); root.UpdateLayout(); await SaveRootAsync("artists-compact");
            Check(body.IsPaneOpen && pageHost.ActualWidth > 350, "窄窗口展开歌词后艺人页面失去可用宽度");
            var filterRow = FindElement<Grid>(pageHost, "LibraryFilters") ?? throw new InvalidOperationException("艺人筛选栏缺失");
            Check(filterRow.Children.Cast<FrameworkElement>().All(x => x.ActualWidth > 0 && x.TransformToVisual(filterRow).TransformPoint(new()).X + x.ActualWidth <= filterRow.ActualWidth + 1), "窄窗口筛选控件超出页面");
            var detailScroll = (ScrollViewer)(FindElement<ContentControl>(pageHost, "ArtistDetails")?.Content ?? throw new InvalidOperationException("艺人详情缺失"));
            var offset = Math.Min(80, detailScroll.ScrollableHeight); Check(offset > 0, "艺人滚动位置样本没有形成滚动区域");
            detailScroll.ChangeView(null, offset, null, true); await Task.Delay(100); Navigate("home"); Navigate("artists"); await Task.Delay(350);
            detailScroll = (ScrollViewer)FindElement<ContentControl>(pageHost, "ArtistDetails")!.Content;
            Check(Math.Abs(detailScroll.VerticalOffset - offset) < 2, "切页后艺人详情丢失滚动位置"); TogglePanel("lyrics");
            ToggleFullscreen(); await Task.Delay(300); Check(AppWindow.Presenter.Kind == Microsoft.UI.Windowing.AppWindowPresenterKind.FullScreen, "不能进入全屏");
            ToggleFullscreen(); AppWindow.Resize(originalSize); await Task.Delay(350); checks.Add(new { layout = "compact-artists,lyrics,fullscreen-restore", ok = true });
            Navigate("home"); TogglePanel("lyrics"); await Task.Delay(500); Check(body.IsPaneOpen, "歌词侧栏未打开");
            await SaveRootAsync("lyrics"); TogglePanel("lyrics");
            ShowVolume(); await Task.Delay(250); Check(volumePanel.Visibility == Visibility.Visible && playerActions.Visibility == Visibility.Collapsed, "音量没有在右侧播放器原位展开"); await SaveRootAsync("volume");
            HideVolume(); Check(playerActions.Visibility == Visibility.Visible, "收起音量后没有恢复歌词与队列入口");
            TogglePanel("playing"); await Task.Delay(500); Check(body.IsPaneOpen, "播放队列未打开"); await SaveRootAsync("playing"); TogglePanel("playing");
            checks.Add(new { panels = "lyrics,playing", ok = true });
            Check(Audio.State == "stopped" && Audio.Current?.Path == initialTrack && queue.Select(x => x.Path).SequenceEqual(initialQueue), "恢复上次歌曲时不能自动播放或改变队列");
            var accounts = Accounts.History;
            try { checks.Add(new { account = await LoginView.VerifyBehaviorAsync(Accounts, this) }); }
            finally { Store.Set("login_accounts", accounts); }
            var savedJobs = jobs.ToList(); var savedPause = queuePaused; queuePaused = true;
            try
            {
                var pending = new DownloadJob { Id = "smoke-format", Url = "https://music.apple.com/cn/song/test/123", Codec = "alac" };
                jobs.Add(pending); activeJob = pending.Id;
                var confirmation = BackendEventAsync(JsonSerializer.SerializeToElement(new { @event = "format_fallback", job_id = pending.Id, request_id = "format-check", quality = "AAC 256 kbps" }));
                await Until(() => Equals(activeDialog?.Tag, pending.Id), 3000); await Task.Delay(150);
                await BackendEventAsync(JsonSerializer.SerializeToElement(new { @event = "finished", job_id = pending.Id, state = "cancelled" }));
                await confirmation.WaitAsync(TimeSpan.FromSeconds(3)); Check(activeDialog is null && activeJob is null, "结束任务后格式确认仍未收起");
                checks.Add(new { downloads = "format-confirmation-dismissed-on-finish", ok = true });
            }
            finally { jobs.Clear(); jobs.AddRange(savedJobs); activeJob = null; queuePaused = savedPause; Store.Set("jobs", jobs); }
            var chain = ShowOutputChainAsync(); await Until(() => outputWindow is not null, 3000);
            await Audio.SetVolumeAsync(1); Check(outputWindow?.Body is StackPanel chainPanel && chainPanel.Children.OfType<TextBlock>().Any(x => x.Text.Contains("软件音量 1%")), "音频链路未实时刷新");
            outputWindow?.Close(); await chain; await Audio.SetVolumeAsync(0); checks.Add(new { outputChain = "modeless-window,live-update", ok = true });
            HandleTray("queue"); Check(body.IsPaneOpen && openPanel == "playing", "托盘不能打开正在播放队列"); TogglePanel("playing");
            HandleTray("output"); await Until(() => outputWindow is not null, 3000); outputWindow!.Close();
            HandleTray("tray"); await Until(() => !AppWindow.IsVisible, 2000); Restore(); checks.Add(new { shortcuts = "inline-volume,tray-queue,tray-output,tray-hide", ok = true });
            PostMessage(WinRT.Interop.WindowNative.GetWindowHandle(this), 0x112, 0xF020, 0);
            await Until(() => AppWindow.Presenter is Microsoft.UI.Windowing.OverlappedPresenter presenter && presenter.State == Microsoft.UI.Windowing.OverlappedPresenterState.Minimized, 3000); Restore();
            await Task.Delay(200); UpdateDragRegions();
            Check(HitTest(new Windows.Foundation.Point(90, 25)) == 2, "侧栏标题不能拖动窗口");
            Check(HitTest(playButton.TransformToVisual(root).TransformPoint(new(playButton.ActualWidth / 2, playButton.ActualHeight / 2))) == 1, "播放器按钮被标题拖动区域遮挡");
            checks.Add(new { window = "normal-minimize,caption-drag,interactive-player", ok = true });
            Store.Set("close_action", "ask"); PostMessage(WinRT.Interop.WindowNative.GetWindowHandle(this), 0x10, 0, 0); await Until(() => activeDialog is not null, 3000); await Task.Delay(150);
            if (activeDialog?.Content is not StackPanel closeContent || closeContent.Children.OfType<CheckBox>().FirstOrDefault() is not { } remember) throw new InvalidOperationException("关闭选择未显示");
            remember.IsChecked = true; var primary = FindElement<Button>(activeDialog, "PrimaryButton") ?? throw new InvalidOperationException("关闭选择没有主按钮");
            foreach (var (state, color) in new[] { ("Normal", Ui.Accent.Color), ("PointerOver", Ui.Brush(255, 227, 48, 91).Color), ("Pressed", Ui.Brush(255, 201, 42, 81).Color) })
            {
                Check(VisualStateManager.GoToState(primary, state, false), "关闭按钮缺少状态：" + state); await Task.Delay(120);
                var face = FindElement<ContentPresenter>(primary, "ContentPresenter") ?? throw new InvalidOperationException("关闭按钮缺少原生模板");
                Check(face.Background is SolidColorBrush background && background.Color == color, "关闭按钮未使用玫瑰红：" + state);
                Check(face.Foreground is SolidColorBrush foreground && foreground.Color == Microsoft.UI.Colors.White, "关闭按钮文字对比不足：" + state);
                var dialogBitmap = new RenderTargetBitmap(); await dialogBitmap.RenderAsync(activeDialog); await SaveScreenshotAsync(dialogBitmap, Path.Combine(folder, "close-dialog-" + state + ".png"));
            }
            VisualStateManager.GoToState(primary, "Normal", false); checks.Add(new { closeDialog = "rose-primary,hover,pressed,white-text", ok = true });
            ((IInvokeProvider)new ButtonAutomationPeer(primary).GetPattern(PatternInterface.Invoke)).Invoke();
            await Until(() => !AppWindow.IsVisible, 3000); Check(Store.Get("close_action", "") == "tray", "未记住托盘选择"); Restore();
            PostMessage(WinRT.Interop.WindowNative.GetWindowHandle(this), 0x10, 0, 0); await Until(() => !AppWindow.IsVisible, 2000);
            using (var second = Process.Start(new ProcessStartInfo(Environment.ProcessPath!) { UseShellExecute = false, CreateNoWindow = true, ArgumentList = { "--data-dir", options.Profile, "--resources", Paths.Resources, "--no-backend" } })!)
            { await second.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(10)); Check(second.ExitCode == 0, "重复启动未正常退出"); }
            await Until(() => AppWindow.IsVisible, 3000); checks.Add(new { lifecycle = "close-choice,remember,tray,single-instance-restore", ok = true });
            if (tracks.Count >= 2 && Audio.Config.Mode == "shared" && Audio.Volume == 0)
            {
                await Task.WhenAll(Audio.LoadAsync(tracks[0], false), Audio.LoadAsync(tracks[1], false));
                Check(Audio.Current?.Path == tracks[1].Path && !Audio.Preparing, "快速换歌的准备结果覆盖了最新歌曲");
                var preparing = Audio.LoadAsync(tracks[0], false); await Audio.ConfigureAsync(Audio.Config); await preparing;
                Check(!Audio.Preparing && Audio.Current?.Path == tracks[0].Path, "准备歌曲时改变输出设置导致播放卡住");
                await PlayTracksAsync(tracks.Take(2)); await Until(() => Audio.State == "playing" && Audio.Position > 100, 8000);
                await Audio.PauseAsync(); await Until(() => Audio.State == "paused", 3000); await SeekTrackAsync(1000); Check(Audio.Position == 1000 && Audio.State == "paused", "暂停时定位失败");
                await TogglePlayAsync(); await Until(() => Audio.State == "playing", 5000); var current = Audio.Current!.Path;
                await SeekTrackAsync(Math.Max(0, Audio.Duration - 120)); await Until(() => trackGap.Running, 5000); await TogglePlayAsync();
                await Task.Delay(2150); Check(Audio.Current?.Path == current && gapWaiting && !trackGap.Running, "暂停曲间等待后仍自动切歌");
                var clock = Stopwatch.StartNew(); await TogglePlayAsync(); await Until(() => Audio.Current?.Path != current, 5000); Check(clock.ElapsedMilliseconds >= 1850, "曲间等待不足两秒");
                await Until(() => Audio.State == "playing", 5000); repeat = true;
                await SeekTrackAsync(Math.Max(0, Audio.Duration - 120)); await Until(() => trackGap.Running, 5000);
                await SeekTrackAsync(1000); await Until(() => Audio.State == "playing", 5000); Check(!gapWaiting && Audio.Position >= 1000, "曲间等待时歌词定位未恢复播放");
                await Audio.PauseAsync(); await Until(() => Audio.State == "paused", 3000); repeat = false;
                var pausedPath = Audio.Current!.Path; var savedOutput = Audio.Config;
                var pausedPosition = await VerifyPausedProbeUiAsync();
                Check(Audio.Current.Path == pausedPath && Audio.Position == pausedPosition && Audio.State == "paused" && Audio.Config == savedOutput, "检测失败破坏了播放状态");
                await Audio.PlayAsync(); await Until(() => Audio.State == "playing", 5000); await Audio.PauseAsync();
                checks.Add(new { playback = "shared-host,pause,seek,two-second-gap,pause-gap,seek-gap,probe-release,failure-recovery", ok = true });
            }
            await File.WriteAllTextAsync(report, JsonSerializer.Serialize(new { ok = true, framework = "Microsoft.UI.Xaml", checks }, StateStore.Json));
        }
        catch (Exception error) { await File.WriteAllTextAsync(report, JsonSerializer.Serialize(new { ok = false, error = error.ToString(), audio = new { Audio.State, Audio.Error, Audio.Position }, checks }, StateStore.Json)); }
        await ExitAsync();
        void Check(bool value, string message) { if (!value) throw new InvalidOperationException(message); }
        async Task SaveRootAsync(string name) { var bitmap = new RenderTargetBitmap(); await bitmap.RenderAsync(root); await SaveScreenshotAsync(bitmap, Path.Combine(folder, name + ".png")); }
    }
    private static async Task Until(Func<bool> condition, int timeout)
    { var clock = Stopwatch.StartNew(); while (!condition()) { if (clock.ElapsedMilliseconds > timeout) throw new TimeoutException("WinUI integration check timed out"); await Task.Delay(25); } }
    [DllImport("user32.dll", EntryPoint = "PostMessageW")] private static extern bool PostMessage(nint window, uint message, nuint wParam, nint lParam);
    private int HitTest(Windows.Foundation.Point point)
    {
        var window = WinRT.Interop.WindowNative.GetWindowHandle(this); var scale = root.XamlRoot.RasterizationScale;
        var screen = new NativePoint { X = (int)(point.X * scale), Y = (int)(point.Y * scale) }; ClientToScreen(window, ref screen);
        return (int)SendMessage(window, 0x84, 0, (nint)((screen.Y << 16) | (screen.X & 0xffff)));
    }
    [StructLayout(LayoutKind.Sequential)] private struct NativePoint { public int X, Y; }
    [DllImport("user32.dll")] private static extern bool ClientToScreen(nint window, ref NativePoint point);
    [DllImport("user32.dll", EntryPoint = "SendMessageW")] private static extern nint SendMessage(nint window, uint message, nuint wParam, nint lParam);
    private static T? FindElement<T>(DependencyObject parent, string name) where T : FrameworkElement
    {
        if (parent is T element && element.Name == name) return element;
        for (var i = 0; i < VisualTreeHelper.GetChildrenCount(parent); i++) if (FindElement<T>(VisualTreeHelper.GetChild(parent, i), name) is { } found) return found;
        return null;
    }
    private static async Task SaveScreenshotAsync(RenderTargetBitmap bitmap, string path)
    {
        var pixels = await bitmap.GetPixelsAsync(); var file = await StorageFolder.GetFolderFromPathAsync(Path.GetDirectoryName(path)!);
        var output = await file.CreateFileAsync(Path.GetFileName(path), CreationCollisionOption.ReplaceExisting); using var stream = await output.OpenAsync(FileAccessMode.ReadWrite);
        var encoder = await BitmapEncoder.CreateAsync(BitmapEncoder.PngEncoderId, stream); encoder.SetPixelData(BitmapPixelFormat.Bgra8, BitmapAlphaMode.Premultiplied, (uint)bitmap.PixelWidth, (uint)bitmap.PixelHeight, 96, 96, pixels.ToArray()); await encoder.FlushAsync();
    }
}
