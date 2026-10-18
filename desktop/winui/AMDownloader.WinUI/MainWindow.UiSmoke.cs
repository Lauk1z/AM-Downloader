using AMDownloader.Core;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;

namespace AMDownloader.WinUI;

public sealed partial class MainWindow
{
    private async Task<object> VerifyPageUiAsync(string folder)
    {
        Navigate("home"); await Task.Delay(300); root.UpdateLayout();
        var buttons = navButtons.ToDictionary();
        var covers = navButtons.Where(x => x.Key.StartsWith("album:")).SelectMany(x => Descendants<Image>(x.Value)).ToList();
        var sources = covers.Select(x => x.Source).ToList(); var opened = 0;
        foreach (var cover in covers) cover.ImageOpened += (_, _) => ++opened;
        for (var pass = 0; pass < 3; ++pass)
        foreach (var target in new[] { "recent", "artists", "albums", "songs", "home" })
        {
            Navigate(target); await Task.Delay(35);
            Require(buttons.All(x => ReferenceEquals(navButtons[x.Key], x.Value)), "普通切页重建了侧栏按钮与专辑封面");
            Require(covers.Select(x => x.Source).SequenceEqual(sources) && opened == 0, "普通切页重新加载了侧栏封面");
        }
        Navigate("home"); await Task.Delay(300); var start = navigationIndicator.Translation; await CaptureAsync("navigation-start");
        Navigate("queue"); await Task.Delay(60); var middle = navigationIndicator.Translation; await CaptureAsync("navigation-interrupted");
        Navigate("albums"); await Task.Delay(320); var end = navigationIndicator.Translation; await CaptureAsync("navigation-end");
        Require(navigationIndicator.Visibility == Visibility.Visible && end == navigationIndicatorTarget, "快速切页后红条没有停在最后选中的栏目");
        var marker = new { start = start.ToString(), middle = middle.ToString(), end = end.ToString() };

        var artworkChecks = new List<string>();
        if (tracks.FirstOrDefault(x => x.Cover.Length > 0) is { } sample)
        {
            var cover = Path.Combine(folder, "cold-cover-" + Guid.NewGuid().ToString("N") + Path.GetExtension(sample.Cover));
            File.Copy(sample.Cover, cover); var track = sample with { Cover = cover };
            var cold = FeaturedCard(track, 250); var card = (Grid)cold.Content; var image = card.Children.OfType<Image>().Single();
            Require(image.Source is null, "精选卡片在处理图就绪前显示了原封面");
            var exposedOriginal = false; var wrongBadge = false;
            var token = image.RegisterPropertyChangedCallback(Image.SourceProperty, (_, _) =>
            {
                if (image.Source is not BitmapImage bitmap || bitmap.UriSource is not null || bitmap.PixelWidth != 640 || bitmap.PixelHeight != 858) exposedOriginal = true;
                var ready = featuredArtwork[cover].Load;
                var badge = card.Children.OfType<Border>().Single();
                var label = ((StackPanel)badge.Child).Children.OfType<TextBlock>().Single();
                if (!ready.IsCompletedSuccessfully || ((SolidColorBrush)label.Foreground).Color != (ready.Result.Dark ? Microsoft.UI.Colors.Black : Microsoft.UI.Colors.White)) wrongBadge = true;
            });
            await Until(() => image.Source is not null, 8000); image.UnregisterPropertyChangedCallback(Image.SourceProperty, token);
            Require(!exposedOriginal && !wrongBadge, "处理图和标识配色没有在解码后协调显示");
            var warm = FeaturedCard(track, 250); var warmImage = ((Grid)warm.Content).Children.OfType<Image>().Single();
            Require(ReferenceEquals(warmImage.Source, image.Source), "重复进入没有直接复用解码后的精选图片");
            var originalStamp = File.GetLastWriteTimeUtc(cover); File.SetLastWriteTimeUtc(cover, originalStamp.AddSeconds(2));
            var updated = await FeaturedArtworkAsync(cover);
            Require(!ReferenceEquals(updated.Image, image.Source) && updated.Image.PixelHeight == 858, "封面文件更新后仍使用旧缓存");
            artworkChecks.AddRange(["cold-placeholder-until-decoded", "processed-only", "badge-synchronized", "warm-decoded-image-reuse", "source-version-invalidates-cache"]);
        }

        var layoutChecks = new List<object>(); var originalSize = AppWindow.Size; var scale = root.XamlRoot.RasterizationScale;
        try
        {
            foreach (var width in new[] { 1100, 1440, 1800 })
            {
                AppWindow.Resize(new Windows.Graphics.SizeInt32((int)(width * scale), (int)(720 * scale))); await Task.Delay(200);
                foreach (var target in new[] { "home", "albums" })
                {
                    Navigate(target); await Task.Delay(250); root.UpdateLayout();
                    var grid = target == "albums" ? FindElement<GridView>(pageHost, "AlbumsGrid") : null;
                    // Exercise the native wrapping/scrolling panel even with the six-album smoke fixture.
                    if (grid is not null) { for (var i = 0; i < 18; ++i) grid.Items.Add(AlbumCard(tracks[i % tracks.Count], 200)); root.UpdateLayout(); await Task.Delay(80); }
                    var scroll = target == "home" ? FindElement<ScrollViewer>(pageHost, "HomeScroll") : FindElement<ScrollViewer>(grid!, "ScrollViewer");
                    Require(scroll is not null && scroll.ScrollableHeight > 0, "滚动验收样本没有形成滚动区域：" + target);
                    var bar = Descendants<ScrollBar>(scroll!).First(x => x.Orientation == Orientation.Vertical && x.ActualWidth > 0);
                    var edge = scroll!.TransformToVisual(pageHost).TransformPoint(new(scroll.ActualWidth, scroll.ActualHeight));
                    var barEdge = bar.TransformToVisual(pageHost).TransformPoint(new(bar.ActualWidth, 0)).X;
                    Require(Math.Abs(edge.X - pageHost.ActualWidth) < 1 && Math.Abs(edge.Y - pageHost.ActualHeight) < 1 && pageHost.ActualWidth - barEdge < 5, "滚动条被页面外边距内缩：" + target);
                    scroll.ChangeView(null, scroll.ScrollableHeight, null, true); await Task.Delay(120); root.UpdateLayout();
                    Require(Math.Abs(scroll.VerticalOffset - scroll.ScrollableHeight) < 1, "不能滚动到底部：" + target);
                    var safeRight = target == "home"
                        ? ((Border)scroll.Content).Child.TransformToVisual(scroll).TransformPoint(new(((FrameworkElement)((Border)scroll.Content).Child).ActualWidth, 0)).X
                        : grid!.Items.OfType<Button>().Where(x => x.IsLoaded).Max(x => x.TransformToVisual(scroll).TransformPoint(new(x.ActualWidth, 0)).X);
                    var barLeft = bar.TransformToVisual(scroll).TransformPoint(new()).X;
                    Require(barLeft - safeRight >= 12, "滚动条与专辑内容重叠：" + target);
                    if (grid is not null) Require(grid.ItemsPanelRoot is ItemsWrapGrid, "专辑列表失去了原生虚拟化面板");
                    var bitmap = new RenderTargetBitmap(); await bitmap.RenderAsync(root); await SaveScreenshotAsync(bitmap, Path.Combine(folder, $"{target}-{width}-bottom.png"));
                    layoutChecks.Add(new { page = target, width = root.ActualWidth, viewport = scroll.ViewportWidth, rightGap = pageHost.ActualWidth - barEdge, contentClearance = barLeft - safeRight, bottom = scroll.VerticalOffset });
                }
            }
            Navigate("home"); TogglePanel("lyrics"); await Task.Delay(350); root.UpdateLayout();
            var compact = FindElement<ScrollViewer>(pageHost, "HomeScroll")!;
            Require(Math.Abs(compact.TransformToVisual(pageHost).TransformPoint(new(compact.ActualWidth, 0)).X - pageHost.ActualWidth) < 1, "歌词展开后主页滚动条没有跟随内容区边缘");
            TogglePanel("lyrics");
        }
        finally { AppWindow.Resize(originalSize); }
        return new { navigation = "15-rapid-switches,persistent-buttons-and-images,no-image-reopen", albumCovers = covers.Count, marker, artworkChecks, layoutChecks, ok = true };
        static void Require(bool condition, string message) { if (!condition) throw new InvalidOperationException(message); }
        async Task CaptureAsync(string name) { var bitmap = new RenderTargetBitmap(); await bitmap.RenderAsync(root); await SaveScreenshotAsync(bitmap, Path.Combine(folder, name + ".png")); }
    }
    private static IEnumerable<T> Descendants<T>(DependencyObject parent) where T : DependencyObject
    {
        for (var i = 0; i < VisualTreeHelper.GetChildrenCount(parent); ++i)
        {
            var child = VisualTreeHelper.GetChild(parent, i); if (child is T match) yield return match;
            foreach (var descendant in Descendants<T>(child)) yield return descendant;
        }
    }
}
