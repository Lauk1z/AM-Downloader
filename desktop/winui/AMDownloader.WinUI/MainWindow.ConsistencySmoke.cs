using AMDownloader.Core;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation.Peers;
using Microsoft.UI.Xaml.Automation.Provider;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;

namespace AMDownloader.WinUI;

public sealed partial class MainWindow
{
    private async Task<object> VerifyConsistencyAsync(string folder)
    {
        var savedTrack = Audio.Current; var savedTracks = tracks; var savedJobs = jobs; var savedPaused = queuePaused;
        var savedArtist = selectedArtist; var offsets = (artistListOffset, artistDetailOffset); var savedSize = AppWindow.Size; var savedPage = page;
        try
        {
            var sample = tracks.First();
            foreach (var (codec, bits, rate, label) in new[] { ("pcm", 16, 44100, "无损"), ("alac", 24, 192000, "高解析度无损"), ("aac", 0, 44100, "AAC") })
            {
                await Audio.LoadAsync(sample with { Codec = codec, Bits = bits, Rate = rate }, false); await Task.Delay(60);
                Check(qualityButton.Content is Viewbox { Width: 15 } && !Descendants<TextBlock>(qualityButton).Any() && ReferenceEquals(qualityButton.Foreground, playButton.Foreground) && (ToolTipService.GetToolTip(qualityButton)?.ToString()?.Contains(label) ?? false), "主播放器音质图标仍含文字、颜色不一致或音质提示缺失");
            }
            await Audio.LoadAsync(savedTrack, false); await Capture("quality-badge");
            var cards = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 20, VerticalAlignment = VerticalAlignment.Top };
            foreach (var name in new[] { "唱游", "需要两行显示的较长专辑名称 · Album" }) cards.Children.Add(AlbumCard(sample with { Album = name, AlbumArtist = "王菲 Artist" }, 185));
            pageHost.Content = cards; await Task.Delay(150); root.UpdateLayout();
            foreach (var card in cards.Children.OfType<Button>())
            {
                var artist = ((StackPanel)card.Content).Children.OfType<TextBlock>().Last(); var bottom = artist.TransformToVisual(card).TransformPoint(new(0, artist.ActualHeight)).Y;
                Check(artist.ActualHeight > 0 && bottom <= card.ActualHeight - card.CornerRadius.BottomLeft + .5, "艺人文字进入卡片底部圆角裁切区域");
                VisualStateManager.GoToState(card, "PointerOver", false);
            }
            await Capture("album-caption-safe");
            foreach (var width in new[] { 1100, 1440 })
            {
                AppWindow.Resize(new((int)(width * root.XamlRoot.RasterizationScale), savedSize.Height)); Navigate("settings"); await Task.Delay(220); root.UpdateLayout();
                var scroll = FindElement<ScrollViewer>(pageHost, "SettingsScroll")!; var content = (FrameworkElement)((Border)scroll.Content).Child;
                Check(Math.Abs(scroll.TransformToVisual(pageHost).TransformPoint(new(scroll.ActualWidth, 0)).X - pageHost.ActualWidth) < 1, "设置滚动条没有移到页面右侧");
                CheckRightGutter(scroll, content, 12);
                scroll.ChangeView(null, scroll.ScrollableHeight, null, true); await Task.Delay(100); CheckRightGutter(scroll, content, 12); await Capture("settings-gutter-" + width);
            }
            tracks = savedTracks.Concat(Enumerable.Range(0, 24).Select(i => sample with { Path = sample.Path + "#layout-" + i, Artist = "布局艺人 " + i, AlbumArtist = "布局艺人 " + i }))
                .Concat(Enumerable.Range(0, 6).Select(i => sample with { Path = sample.Path + "#layout-album-" + i, Album = "专辑排版样本 " + i })).ToList();
            selectedArtist = sample.Artist; Navigate("artists"); await Task.Delay(220); root.UpdateLayout();
            var list = FindElement<ListView>(pageHost, "ArtistsList")!; var artistScroll = Descendants<ScrollViewer>(list).First();
            Check(artistScroll.ScrollableHeight > 0, "艺人列表样本未产生滚动区域");
            artistScroll.ChangeView(null, artistScroll.ScrollableHeight, null, true); await Task.Delay(100); root.UpdateLayout();
            var artistBar = Descendants<ScrollBar>(artistScroll).First(x => x.Orientation == Orientation.Vertical && x.ActualWidth > 0);
            var barLeft = artistBar.TransformToVisual(list).TransformPoint(new()).X;
            foreach (var item in list.Items.OfType<ListViewItem>().Where(x => x.IsLoaded && x.ActualWidth > 0))
                Check(item.TransformToVisual(list).TransformPoint(new(item.ActualWidth, 0)).X <= barLeft + 1, "艺人滚动条与列表高光重叠");
            var detailsScroll = FindElement<ScrollViewer>(pageHost, "ArtistDetailsScroll")!;
            CheckRightGutter(detailsScroll, (FrameworkElement)((Border)detailsScroll.Content).Child, 6); await Capture("artists-scroll-gutter");
            tracks = savedTracks;
            jobs = Enumerable.Range(0, 24).Select(i => new DownloadJob { Id = "ui-table-" + i, Title = "下载样式样本 " + i, Artist = "测试艺人", Codec = "alac", State = i == 2 ? "FAILED" : i == 3 ? "queued" : "DONE", Total = 1, Completed = i == 3 ? 0 : 1 }).ToList(); queuePaused = true;
            Navigate("queue"); await Task.Delay(200); root.UpdateLayout();
            var downloadScroll = FindElement<ScrollViewer>(pageHost, "DownloadScroll")!; var header = FindElement<Grid>(pageHost, "DownloadHeader")!;
            var rows = Descendants<Grid>(downloadScroll).Where(x => x.Name == "DownloadItem").ToList();
            Check(rows.Count == jobs.Count && rows.All(x => x.CornerRadius.TopLeft == 7 && x.MinHeight == 52 && x.Padding.Top == 12), "下载表格行规格未与歌曲表格统一");
            Check(rows[0].Background is SolidColorBrush { Color.A: 65 } && rows[1].Background is SolidColorBrush { Color.A: 0 } && rows[2].Background is SolidColorBrush { Color.A: 110 }, "下载表格交替行或失败提示色错误");
            Check(!downloadRows[jobs[0].Id].Action.IsEnabled && Equals(downloadRows[jobs[2].Id].Action.Content, "重试"), "下载操作状态被改变");
            await Capture("downloads-table");
            var top = header.TransformToVisual(pageHost).TransformPoint(new()).Y;
            downloadScroll.ChangeView(null, downloadScroll.ScrollableHeight, null, true); await Task.Delay(100);
            Check(downloadScroll.VerticalOffset > 0 && header.TransformToVisual(pageHost).TransformPoint(new()).Y == top, "滚动下载任务时表头未固定"); await Capture("downloads-table-bottom");
            jobs[2].State = "DONE"; UpdateDownloadView(); Check(rows[2].Background is SolidColorBrush { Color.A: 65 } && !downloadRows[jobs[2].Id].Action.IsEnabled, "下载状态改变后底色或按钮未刷新");
            var cancel = downloadRows[jobs[3].Id].Action; ((IInvokeProvider)new ButtonAutomationPeer(cancel).GetPattern(PatternInterface.Invoke)).Invoke(); await Until(() => jobs[3].State == "cancelled", 2000);
            var removed = jobs[^1]; await JobActionAsync(removed, true); Check(!jobs.Contains(removed), "下载队列移除操作失效");
            return new { consistency = "actual-quality-badge,album-caption-safe,settings-edge-scroll,artist-scroll-gutters,striped-download-table,fixed-header,status-refresh,cancel-and-remove", ok = true };
        }
        finally
        {
            tracks = savedTracks; jobs = savedJobs; queuePaused = savedPaused; selectedArtist = savedArtist; (artistListOffset, artistDetailOffset) = offsets; Store.Set("jobs", savedJobs);
            AppWindow.Resize(savedSize); await Audio.LoadAsync(savedTrack, false); Navigate(savedPage);
        }
        void Check(bool condition, string message) { if (!condition) throw new InvalidOperationException(message); }
        void CheckRightGutter(ScrollViewer scroll, FrameworkElement content, double minimum)
        {
            var bar = Descendants<ScrollBar>(scroll).First(x => x.Orientation == Orientation.Vertical && x.ActualWidth > 0);
            var right = content.TransformToVisual(scroll).TransformPoint(new(content.ActualWidth, 0)).X;
            Check(right + minimum <= bar.TransformToVisual(scroll).TransformPoint(new()).X + 1, "滚动条与内容没有安全间距");
        }
        async Task Capture(string name) { var bitmap = new RenderTargetBitmap(); await bitmap.RenderAsync(root); await SaveScreenshotAsync(bitmap, Path.Combine(folder, name + ".png")); }
    }
}
