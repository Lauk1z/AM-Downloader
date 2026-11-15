using AMDownloader.Core;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Automation.Peers;
using Microsoft.UI.Xaml.Automation.Provider;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media.Imaging;
using Microsoft.UI.Xaml.Media;
using Rectangle = Microsoft.UI.Xaml.Shapes.Rectangle;

namespace AMDownloader.WinUI;

public sealed partial class MainWindow
{
    private async Task<object> VerifyPlayerViewsAsync(string folder)
    {
        if (tracks.Count < 2 || Audio.Volume != 0 || Audio.Config.Mode != "shared") throw new InvalidOperationException("播放视图测试需要静音样本");
        var position = AppWindow.Position; var size = AppWindow.Size; var pageContent = pageHost.Content; var mainHandle = WinRT.Interop.WindowNative.GetWindowHandle(this);
        await PlayTracksAsync(tracks.Take(2)); await Until(() => Audio.State == "playing", 5000); await SeekTrackAsync(1000);
        var path = Audio.Current!.Path; var entries = queue.Select(x => x.Path).ToList();
        try
        {
            if (!body.IsPaneOpen || openPanel != "lyrics") TogglePanel("lyrics"); await Task.Delay(100); var mainLyrics = lyricScroll;
            Invoke(FindElement<Button>(root, "OpenMiniPlayer")!); await Until(() => playerWindow is not null && AppWindow.Presenter is OverlappedPresenter { State: OverlappedPresenterState.Minimized }, 2000);
            var window = playerWindow!; await Task.Delay(300); window.Surface.UpdateLayout(); var handle = WinRT.Interop.WindowNative.GetWindowHandle(window);
            Check(handle != mainHandle && ReferenceEquals(pageHost.Content, pageContent) && body.IsPaneOpen, "播放窗口未独立或丢失主界面状态");
            Check(window.AppWindow.Presenter is OverlappedPresenter { IsAlwaysOnTop: true, IsResizable: false } && window.AppWindow.Size.Width <= 361 * window.Surface.XamlRoot.RasterizationScale, "小窗呈现器或尺寸错误");
            Check(Audio.Current.Path == path && Audio.State == "playing" && Audio.Position >= 1000 && queue.Select(x => x.Path).SequenceEqual(entries), "进入小窗重置了播放");
            SetPlayerView(PlayerViewMode.Mini); Check(ReferenceEquals(playerWindow, window), "重复打开创建了第二个播放窗口");
            await Audio.PauseAsync(); await Until(() => Audio.State == "paused", 2000);
            if (Audio.Current.Cover.Length > 0) await Until(() => window.Backdrop.Source is not null, 8000);
            Inside(window.SeekSlider); Inside(window.SongTitle); Inside(window.CoverFrame); Inside(window.Footer);
            Check(!window.HasNativeFrame && !window.Surface.Children.OfType<Border>().Any(x => x.BorderThickness.Top > 0), "小窗仍有系统边框或额外描边：" + window.NativeFrameDetails);
            Check(window.CanDragAt(new(150, 30)) && !window.CanDragAt(Centre(window.SeekSlider)), "顶部拖动区域或进度条输入区域错误");
            var smallHeight = window.AppWindow.Size.Height; var headerY = window.CoverFrame.TransformToVisual(window.Surface).TransformPoint(new()).Y; await Capture("mini-player");
            window.SeekSlider.Value = 1500; await Until(() => Audio.Position == 1500, 2000); window.VolumeSlider.Value = 1; await Until(() => Audio.Volume == 1, 2000); window.VolumeSlider.Value = 0;
            window.TogglePanel("lyrics"); await Task.Delay(80); Check(window.IsAnimating && window.AppWindow.Size.Height > smallHeight, "展开没有实际的窗口动画"); await Capture("mini-expanding");
            await Until(() => !window.IsAnimating, 2000); window.Surface.UpdateLayout(); Check(window.MotionFrames > 1 && window.HadIntermediateBounds, "展开只改变了最终尺寸");
            Check(window.AppWindow.Size.Height > smallHeight && window.LyricScroll is not null && !ReferenceEquals(window.LyricScroll, mainLyrics) && ReferenceEquals(lyricScroll, mainLyrics), "小窗歌词未独立或未向下展开");
            Check(Math.Abs(window.CoverFrame.TransformToVisual(window.Surface).TransformPoint(new()).Y - headerY) < 1 && window.Footer.TransformToVisual(window.Surface).TransformPoint(new()).Y > window.PanelHost.TransformToVisual(window.Surface).TransformPoint(new()).Y + window.PanelHost.ActualHeight - 1, "展开后顶栏或底部控制栏移位");
            Inside(window.PanelHost); Inside(window.Footer); await Capture("mini-lyrics");
            Check(window.LyricScroll!.VerticalScrollBarVisibility == ScrollBarVisibility.Hidden, "小窗歌词仍显示滚动条");
            var shortLyrics = lyricLines;
            try
            {
                lyricLines = Enumerable.Range(0, 24).Select(i => new LyricLine(i * 1000, "滚动检查 " + i)).ToList(); window.RefreshLyrics();
                await Until(() => window.LyricScroll?.ScrollableHeight > 0, 2000);
                window.LyricScroll!.ChangeView(null, window.LyricScroll.ScrollableHeight, null, true); await Task.Delay(80); Check(window.LyricScroll.VerticalOffset > 0, "隐藏滚动条后歌词不能滚动");
            }
            finally { lyricLines = shortLyrics; window.RefreshLyrics(); }
            window.TogglePanel("queue"); await Task.Delay(200); Check(window.QueueList!.Items.Count == 1, "待播清单不正确"); await Capture("mini-queue");
            Check(ScrollViewer.GetVerticalScrollBarVisibility(window.QueueList) == ScrollBarVisibility.Hidden, "小窗待播清单仍显示滚动条");
            var tab = Descendants<Button>(window.PanelHost).Single(x => Equals(x.Content, "待播清单"));
            Check(tab.Background is SolidColorBrush { Color: { A: 24, R: 255, G: 255, B: 255 } } && ReferenceEquals(tab.Background, tab.Resources["ButtonBackgroundPointerOver"]), "选中标签未与白色悬停背景一致");
            var row = (ListViewItem)window.QueueList.ContainerFromIndex(0); var more = FindElement<Button>(row, "More")!; more.Visibility = Visibility.Visible; Invoke(more);
            await Task.Delay(150); var menu = (MenuFlyout)Microsoft.UI.Xaml.Controls.Primitives.FlyoutBase.GetAttachedFlyout(more); Check(ReferenceEquals(menu.Target, more), "队列菜单没有锚定当前歌曲按钮"); menu.Hide();
            shuffled = true; shuffle.Reset(); window.RefreshQueue(); await Task.Delay(150); Invoke(Descendants<Button>(window.PanelHost).Single(x => Equals(x.Content, "清除"))); await Task.Delay(100);
            Check(window.QueueList!.Items.Count == 0 && Audio.Current.Path == path && Audio.State == "paused", "清除随机待播清单停止了当前歌曲或残留待播项");
            Check(window.CanDragAt(Centre(window.PanelHost)), "空白待播区域不能拖动小窗");
            queue = entries.Select(p => tracks.First(x => x.Path == p)).ToList(); playIndex = 0; shuffled = false; shuffle.Reset(); SaveQueue(); RefreshPanel();
            window.SelectHistory(true); await Task.Delay(150); Check(window.ShowingHistory && window.QueueList!.Items.Count > 0, "播放历史未显示"); await Capture("mini-history");
            window.TogglePanel("queue"); await Until(() => !window.IsAnimating, 2000); Check(window.AppWindow.Size.Height == smallHeight && window.HadIntermediateBounds, "收起未平滑恢复紧凑小窗");
            window.TogglePanel("lyrics"); await Task.Delay(60); window.TogglePanel("lyrics"); await Task.Delay(60); window.TogglePanel("queue"); await Until(() => !window.IsAnimating, 2000);
            Check(window.Panel == "queue" && window.PanelHost.Visibility == Visibility.Visible, "连续切换后面板状态不正确"); window.TogglePanel("queue"); await Until(() => !window.IsAnimating, 2000);
            var background = window.Backdrop.Source;
            Invoke(Descendants<Button>(window.Surface).Single(x => AutomationProperties.GetName(x) == "全屏播放")); await Task.Delay(100); Check(window.IsAnimating, "进入全屏没有窗口过渡"); await Capture("fullscreen-transition"); await Until(() => !window.IsAnimating, 3000); window.Surface.UpdateLayout();
            Check(window.IsFullscreen && window.AppWindow.Presenter.Kind == AppWindowPresenterKind.FullScreen && WinRT.Interop.WindowNative.GetWindowHandle(window) == handle, "放大按钮未使同一播放窗口全屏");
            Check(AppWindow.Presenter is OverlappedPresenter { State: OverlappedPresenterState.Minimized } && ReferenceEquals(background, window.Backdrop.Source), "全屏改变了主窗口或重载封面背景");
            Check(Audio.Current.Path == path && Audio.Position == 1500 && Audio.State == "paused", "全屏切换改变了播放状态");
            Check(!window.HasNativeFrame && window.HadIntermediateBounds && window.MotionFrames > 1, "全屏仍有边框或没有实际缩放过渡");
            Check(FindElement<Rectangle>(window.SeekSlider, "HorizontalTrackRect")?.Height == 6 && window.LyricScroll?.VerticalScrollBarVisibility == ScrollBarVisibility.Hidden, "全屏进度条粗细或歌词滚动条错误");
            Inside(window.CoverFrame); Inside(window.Footer); Inside(window.PanelHost); await Capture("fullscreen-player");
            window.Surface.Width = 1024; window.Surface.Height = 640; await Task.Delay(250); window.Surface.UpdateLayout(); Inside(window.Footer); Inside(window.CoverFrame); Inside(window.PanelHost); await Capture("fullscreen-compact");
            window.Surface.Width = window.Surface.Height = double.NaN; await Task.Delay(150);
            Invoke(Descendants<Button>(window.Surface).Single(x => AutomationProperties.GetName(x) == "退出全屏")); await Until(() => !window.IsAnimating, 3000); Check(!window.IsFullscreen && ReferenceEquals(playerWindow, window), "退出全屏创建了其他窗口");
            window.ShowMode(true); await Task.Delay(80); window.ShowMode(false); await Until(() => !window.IsAnimating, 3000); Check(!window.IsFullscreen && !window.HasNativeFrame, "快速切换全屏后窗口状态错误");
            await Audio.PlayAsync(); await Until(() => Audio.State == "playing", 2000); window.Close(); await Until(() => playerWindow is null && AppWindow.Presenter is OverlappedPresenter { State: OverlappedPresenterState.Restored }, 2000);
            Check(Audio.State == "playing" && Audio.Current.Path == path && !quitting && AppWindow.Size.Width == size.Width && AppWindow.Size.Height == size.Height && AppWindow.Position.X == position.X && AppWindow.Position.Y == position.Y, "关闭小窗退出了主程序、停止播放或改变主窗口大小");
            await Audio.PauseAsync(); ((OverlappedPresenter)AppWindow.Presenter).Maximize(); await Task.Delay(150); SetPlayerView(PlayerViewMode.Fullscreen); await Until(() => playerWindow?.IsAnimating == false, 3000); playerWindow!.Close(); await Task.Delay(200);
            Check(!quitting && AppWindow.Presenter is OverlappedPresenter { State: OverlappedPresenterState.Maximized } && Audio.State == "paused", "关闭全屏未恢复最大化主窗口");
            ((OverlappedPresenter)AppWindow.Presenter).Restore(); AppWindow.MoveAndResize(new(position.X, position.Y, size.Width, size.Height));
            repeat = repeatOne = false; CycleRepeat(); Check(repeatOne && !repeat, "单曲循环未开启");
            await Audio.PlayAsync(); await Until(() => Audio.State == "playing", 2000); await SeekTrackAsync(Audio.Duration - 120); await Until(() => trackGap.Running, 3000); var gap = System.Diagnostics.Stopwatch.StartNew();
            await Until(() => !trackGap.Running && Audio.State == "playing" && Audio.Position < 1500, 5000); Check(Audio.Current.Path == path && gap.ElapsedMilliseconds >= 1800, "单曲循环未保持歌曲或两秒间隔");
            await SkipAsync(1); Check(Audio.Current!.Path != path, "单曲循环阻止了手动下一首"); CycleRepeat(); Check(!repeatOne && repeat, "列表循环切换失败"); CycleRepeat();
            return new { playerViews = "separate-window,cover-click,main-minimized,main-preserved,compact,lyrics,up-next,history,same-window-fullscreen,close-preserves-playback,restore-maximized,repeat-one", polish = "borderless,drag-regions,white-selected-tab,hidden-scrollbars,scroll-retained,6dip-fullscreen-progress,animated-expand-collapse,animated-fullscreen,interrupted-transitions", ok = true };
            Windows.Foundation.Point Centre(FrameworkElement element) => element.TransformToVisual(window.Surface).TransformPoint(new(element.ActualWidth / 2, element.ActualHeight / 2));
            void Inside(FrameworkElement element)
            { var point = element.TransformToVisual(window.Surface).TransformPoint(new()); Check(element.ActualWidth > 0 && element.ActualHeight > 0 && point.X >= -1 && point.Y >= -1 && point.X + element.ActualWidth <= window.Surface.ActualWidth + 1 && point.Y + element.ActualHeight <= window.Surface.ActualHeight + 1, "播放控件超出窗口：" + element.GetType().Name); }
            async Task Capture(string name) { var image = new RenderTargetBitmap(); await image.RenderAsync(window.Surface); await SaveScreenshotAsync(image, Path.Combine(folder, name + ".png")); }
        }
        finally { if (playerWindow is not null) { playerWindow.Surface.Width = playerWindow.Surface.Height = double.NaN; playerWindow.Close(); } repeat = repeatOne = false; CancelGap(); await Audio.PauseAsync(); UpdatePlayer(); }
        void Check(bool condition, string message) { if (!condition) throw new InvalidOperationException(message); }
        void Invoke(Button button) => ((IInvokeProvider)new ButtonAutomationPeer(button).GetPattern(PatternInterface.Invoke)).Invoke();
    }
}
