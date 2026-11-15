using AMDownloader.WinUI.Views;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;

namespace AMDownloader.WinUI;

public sealed partial class MainWindow
{
    private async Task<object> VerifyShellUiAsync(string folder)
    {
        var size = AppWindow.Size; var material = SystemBackdrop; var savedPage = page;
        var savedTrack = Audio.Current; var savedArtist = selectedArtist; var savedFavourites = favourites.ToHashSet();
        var widths = new List<int>(); var pages = new List<string>();
        try
        {
            Check(material is DesktopAcrylicBackdrop && root.Background is SolidColorBrush { Color.A: 0 }, "主窗口未使用透明内容层和窗口后方的 Acrylic 材质");
            Check(!root.Children.OfType<Image>().Any(), "主窗口仍包含封面背景层");
            foreach (var width in new[] { 1100, 1440 })
            {
                AppWindow.Resize(new((int)(width * root.XamlRoot.RasterizationScale), size.Height)); await Task.Delay(180); UpdateDragRegions();
                Check(HitTest(new(90, 25)) == 2 && HitTest(Centre(playerCover)) == 1 && HitTest(Centre(playerTitle)) == 2 && HitTest(Centre(playerArtist)) == 2, "顶部文字拖动或封面点击区域错误");
                foreach (var button in captionControls.OfType<Button>().Where(x => x == playButton || x.Parent == playerActions))
                    Check(HitTest(Centre(button)) == 1, "顶部按钮被拖动区域遮挡");
                ShowVolume(); await Task.Delay(80); UpdateDragRegions(); Check(HitTest(Centre(volumeSlider)) == 1, "音量滑块不能接收鼠标操作");
                HideVolume(); await Task.Delay(80); UpdateDragRegions();
                Check(HitTest(Centre((FrameworkElement)playerActions.Children[0])) == 1 && HitTest(Centre(playerTitle)) == 2, "收起音量后拖动区域未更新");
                var library = FindElement<StackPanel>(navigation, "LibraryHeading")!;
                var playlist = FindElement<StackPanel>(navigation, "PlaylistHeading")!;
                Check(Math.Abs(library.TransformToVisual(root).TransformPoint(new()).X - playlist.TransformToVisual(root).TransformPoint(new()).X) < .1 &&
                    Math.Abs(((FrameworkElement)library.Children[1]).TransformToVisual(root).TransformPoint(new()).X - ((FrameworkElement)playlist.Children[1]).TransformToVisual(root).TransformPoint(new()).X) < .1, "资料库和播放列表标题未对齐");
                widths.Add(width);
            }
            AppWindow.Resize(size); await Task.Delay(150);
            Check(tracks.Count >= 2 && Audio.Volume == 0 && Audio.Config.Mode == "shared", "播放标记检查需要至少两首静音测试歌曲");
            var first = tracks[0]; var second = tracks[1]; favourites.Add(first.Path);
            Navigate("songs"); await Task.Delay(100);
            var list = Descendants<ListView>(pageHost).First(x => x.Items.FirstOrDefault() is TrackRow); list.SelectedIndex = 1; var selected = list.SelectedItem;
            await Audio.LoadAsync(first, true); await Until(() => Audio.State == "playing", 8000); await Task.Delay(100);
            Check(pageTrackRows.First(x => x.Track.Path == first.Path).PlaybackTip == "正在播放", "开始播放后歌曲行没有更新"); CheckRows(); await Capture("songs-now-playing");
            await Audio.PauseAsync(); await Until(() => Audio.State == "paused", 3000); await Task.Delay(80);
            Check(pageTrackRows.First(x => x.Track.Path == first.Path).MarkerData == Icons.PauseData, "暂停后标记未保留或未更新"); CheckRows(); await Capture("songs-now-paused");
            await Audio.LoadAsync(second, true); await Until(() => Audio.State == "playing", 8000); await Task.Delay(100);
            Check(ReferenceEquals(list.SelectedItem, selected), "播放状态更新改变了用户选中的歌曲");
            Check(!pageTrackRows.First(x => x.Track.Path == first.Path).IsCurrent && pageTrackRows.First(x => x.Track.Path == first.Path).MarkerData == Icons.StarData, "切歌后上一首播放标记未清除或收藏标记丢失");
            CheckRows(); UpdateDragRegions(); Check(HitTest(Centre(playerTitle)) == 2, "换歌后顶部歌名不可拖动");
            await Audio.LoadAsync(first, true); await Until(() => Audio.State == "playing", 8000); await Audio.PauseAsync(); await Until(() => Audio.State == "paused", 3000);
            selectedArtist = first.Artist;
            var targets = new List<string> { "songs", "recent", "favourites", "search", "album:" + first.AlbumKey, "artists" };
            targets.AddRange(playlists.Where(x => x.Entries.Any(y => y.Path == first.Path)).Select(x => x.Id));
            foreach (var target in targets)
            {
                Navigate(target); await Task.Delay(150); root.UpdateLayout();
                Check(pageTrackRows.Any(x => x.Track.Path == first.Path && x.IsCurrent), "切换页面后丢失播放标记：" + target); CheckRows(); pages.Add(target);
                if (target == "artists") await Capture("artists-now-playing");
            }
            pageTrackRows.Clear(); pageHost.Content = TrackTable(Enumerable.Range(0, 160).Select(i => tracks[i % tracks.Count]).ToList()); await Task.Delay(100); root.UpdateLayout();
            var scrolling = Descendants<ScrollViewer>(pageHost).First();
            foreach (var offset in new[] { scrolling.ScrollableHeight, 0d }) { scrolling.ChangeView(null, offset, null, true); await Task.Delay(120); root.UpdateLayout(); CheckRows(); }
            await Audio.LoadAsync(null, false); await Task.Delay(80); Check(pageTrackRows.All(x => !x.IsCurrent), "停止并清空歌曲后播放标记未清除");
            Check(ReferenceEquals(material, SystemBackdrop) && !root.Children.OfType<Image>().Any(), "换歌后桌面材质被封面替换");
            return new { shell = "caption-text,clickable-cover,interactive-controls,volume-toggle,sidebar-heading-alignment,desktop-acrylic", widths, playback = "live-start,pause,track-change,selection-preserved,favourite-restored,page-navigation,recycling,clear", pages, backdropCapture = "system material verified by live Window.SystemBackdrop; XAML snapshots exclude the OS backdrop", ok = true };
        }
        finally { HideVolume(); AppWindow.Resize(size); favourites = savedFavourites; selectedArtist = savedArtist; await Audio.LoadAsync(savedTrack, false); Navigate(savedPage); UpdateDragRegions(); }
        void Check(bool value, string message) { if (!value) throw new InvalidOperationException(message); }
        Windows.Foundation.Point Centre(FrameworkElement element) => element.TransformToVisual(root).TransformPoint(new(element.ActualWidth / 2, element.ActualHeight / 2));
        void CheckRows()
        {
            foreach (var table in Descendants<ListView>(pageHost).Where(x => x.Items.FirstOrDefault() is TrackRow))
            {
                var viewport = Descendants<ScrollViewer>(table).First();
                foreach (var row in table.Items.Cast<TrackRow>())
                    if (table.ContainerFromItem(row) is ListViewItem { ContentTemplateRoot: Grid surface } item)
                    {
                        var y = item.TransformToVisual(viewport).TransformPoint(new()).Y;
                        if (item.ActualHeight > 0 && y + item.ActualHeight > 0 && y < viewport.ViewportHeight) CheckRow(row, surface);
                    }
            }
            foreach (var surface in Descendants<Grid>(pageHost).Where(x => x.Tag is TrackRow)) CheckRow((TrackRow)surface.Tag, surface);
        }
        void CheckRow(TrackRow row, Grid surface)
        {
            var current = row.Track.Path == Audio.Current?.Path && Audio.State is "playing" or "paused";
            Check(row.IsCurrent == current, "歌曲标记指向错误的曲目");
            var title = Descendants<TextBlock>(surface).First(x => x.Text == row.Track.Title);
            Check(title.Foreground is SolidColorBrush ink && ink.Color == (current ? Ui.Accent.Color : Ui.Brush(255, 238, 238, 242).Color), "实际歌名控件未更新播放颜色");
            if (current) Check(Descendants<Viewbox>(surface).First().Visibility == Visibility.Visible && row.IndexText == "", "当前歌曲仍显示序号，未显示播放标记");
        }
        async Task Capture(string name) { var bitmap = new RenderTargetBitmap(); await bitmap.RenderAsync(root); await SaveScreenshotAsync(bitmap, Path.Combine(folder, name + ".png")); }
    }
}
