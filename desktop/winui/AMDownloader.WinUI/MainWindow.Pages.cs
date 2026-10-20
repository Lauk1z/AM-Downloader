using System.Collections.ObjectModel;
using System.Text.Json;
using AMDownloader.Core;
using AMDownloader.WinUI.Views;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Markup;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;

namespace AMDownloader.WinUI;

public sealed partial class MainWindow
{
    private Grid PageFrame(string title, string subtitle, UIElement content, UIElement? actions = null, UIElement? filtering = null, bool edgeScroll = false)
    {
        var grid = new Grid { Padding = new(edgeScroll ? 0 : 32, 24, edgeScroll ? 0 : 32, edgeScroll ? 0 : 24), RowSpacing = 18 };
        grid.RowDefinitions.Add(new() { Height = GridLength.Auto }); grid.RowDefinitions.Add(new() { Height = GridLength.Auto }); grid.RowDefinitions.Add(new() { Height = new(1, GridUnitType.Star) });
        var heading = new Grid { Margin = new(edgeScroll ? 32 : 0, 0, edgeScroll ? 32 : 0, 0) }; heading.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) }); heading.ColumnDefinitions.Add(new() { Width = GridLength.Auto });
        var labels = Ui.Stack(12); labels.Children.Add(Ui.Text(title, 38, true)); if (subtitle.Length > 0) labels.Children.Add(Ui.Text(subtitle, 15, color: Ui.Muted)); heading.Children.Add(labels);
        if (actions is FrameworkElement actionElement) { Grid.SetColumn(actionElement, 1); actionElement.VerticalAlignment = VerticalAlignment.Top; heading.Children.Add(actionElement); }
        grid.Children.Add(heading); if (filtering is FrameworkElement filterElement) { if (edgeScroll) filterElement.Margin = new(32, 0, 32, 0); Grid.SetRow(filterElement, 1); grid.Children.Add(filterElement); }
        Grid.SetRow((FrameworkElement)content, 2); grid.Children.Add(content); return grid;
    }
    private string Counts(IEnumerable<Track> values) { var all = values.ToList(); return $"{all.Count} 首歌曲 · {all.Select(x => x.AlbumKey).Distinct().Count()} 张专辑"; }
    private Grid EmptyState(string title = "把喜爱的音乐留在这里", string description = "粘贴 Apple Music 链接，或导入已有的音乐文件与文件夹。")
    {
        var center = Ui.Stack(18); center.VerticalAlignment = VerticalAlignment.Center; center.HorizontalAlignment = HorizontalAlignment.Center; center.MaxWidth = 700;
        var note = (FrameworkElement)Icons.Create("songs", 66, ink: Ui.Brush(255, 235, 159, 180)); note.HorizontalAlignment = HorizontalAlignment.Center; center.Children.Add(note);
        var text = Ui.Text(title, 25, true); text.HorizontalAlignment = HorizontalAlignment.Center; center.Children.Add(text);
        text = Ui.Text(description, 15, color: Ui.Muted); text.HorizontalAlignment = HorizontalAlignment.Center; text.TextAlignment = TextAlignment.Center; center.Children.Add(text);
        var button = Ui.Button("添加音乐", () => _ = AddMusicAsync(), true, "add"); button.HorizontalAlignment = HorizontalAlignment.Center; center.Children.Add(button);
        var grid = new Grid(); grid.Children.Add(center); return grid;
    }
    private Grid HomePage()
    {
        if (tracks.Count == 0) return PageFrame("主页", "你的音乐，从这里开始。", EmptyState(), Ui.Button("添加音乐", () => _ = AddMusicAsync(), icon: "add"));
        var stack = Ui.Stack(28);
        stack.Children.Add(AlbumRail("资料库精选", tracks.GroupBy(x => x.AlbumKey).Select(x => x.First()).Take(12).ToList(), true));
        var lookup = tracks.ToDictionary(x => x.Path); var history = Store.Get("recently_played", new List<string>()).Where(lookup.ContainsKey).Select(x => lookup[x]).ToList();
        stack.Children.Add(AlbumRail(history.Count > 0 ? "最近播放" : "最近添加", (history.Count > 0 ? history.AsEnumerable() : tracks.OrderByDescending(x => x.Modified)).DistinctBy(x => x.AlbumKey).Take(14).ToList(), false));
        stack.Children.Add(Ui.Text("你的音乐资料库", 23, true)); stack.Children.Add(Ui.Text(Counts(tracks), 15, color: Ui.Muted));
        var scroll = Ui.Scroll(new Border { Padding = new(32, 0, 32, 24), Child = stack }); scroll.Name = "HomeScroll";
        return PageFrame("主页", "", scroll, Ui.Button("添加音乐", () => _ = AddMusicAsync(), icon: "add"), edgeScroll: true);
    }
    private StackPanel AlbumRail(string title, List<Track> albums, bool featured)
    {
        var section = Ui.Stack(12); var header = new Grid(); header.Children.Add(Ui.Text(title, 23, true));
        var rail = Ui.Stack(20, Orientation.Horizontal); foreach (var track in albums) rail.Children.Add(AlbumCard(track, featured ? 250 : 185, featured));
        var scroll = new ScrollViewer { Content = rail, HorizontalScrollBarVisibility = ScrollBarVisibility.Hidden, VerticalScrollBarVisibility = ScrollBarVisibility.Disabled, HorizontalScrollMode = ScrollMode.Enabled, VerticalScrollMode = ScrollMode.Disabled };
        var arrows = Ui.Stack(6, Orientation.Horizontal); arrows.HorizontalAlignment = HorizontalAlignment.Right;
        arrows.Children.Add(Ui.Icon("\uE76B", "上一组专辑", () => scroll.ChangeView(Math.Max(0, scroll.HorizontalOffset - scroll.ViewportWidth), null, null, false), 16));
        arrows.Children.Add(Ui.Icon("\uE76C", "下一组专辑", () => scroll.ChangeView(scroll.HorizontalOffset + scroll.ViewportWidth, null, null, false), 16));
        header.Children.Add(arrows); section.Children.Add(header); section.Children.Add(scroll); return section;
    }
    private Button AlbumCard(Track track, double size, bool featured = false)
    {
        if (featured) return FeaturedCard(track, size);
        var content = Ui.Stack(5); content.Width = size; var cover = Ui.Cover(track.Cover, size, 9); content.Children.Add(cover);
        var title = Ui.Text(track.Album, featured ? 19 : 14, featured); title.MaxLines = 2; title.TextTrimming = TextTrimming.CharacterEllipsis; content.Children.Add(title);
        var artist = Ui.Text(track.DisplayArtist, featured ? 15 : 13, color: Ui.Muted); artist.MaxLines = 1; artist.TextTrimming = TextTrimming.CharacterEllipsis; content.Children.Add(artist);
        var button = new Button { Content = content, Background = Ui.Brush(0, 0, 0, 0), BorderThickness = new(0), Padding = new(0), CornerRadius = new(10) };
        button.Click += (_, _) => Navigate("album:" + track.AlbumKey); Ui.AddMenu(button, () => AlbumMenu(tracks.Where(x => x.AlbumKey == track.AlbumKey).ToList())); return button;
    }
    private Button FeaturedCard(Track track, double size)
    {
        var grid = new Grid { Width = size, Height = size * 1.34, CornerRadius = new(10), Background = Ui.Brush(255, 53, 49, 58) };
        var image = Ui.Image("", size); image.Name = "FeaturedArtwork"; image.Height = size * 1.34; grid.Children.Add(image);
        var brand = Ui.Stack(3, Orientation.Horizontal); brand.Children.Add(Icons.Create("songs", 15, ink: Ui.Brush(255, 255, 255, 255))); brand.Children.Add(Ui.Text("AM Dowloader", 12, true));
        var badge = new Border { Name = "FeaturedBadge", Child = brand, Padding = new(4, 2, 4, 2), CornerRadius = new(5), HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Top, Margin = new(10) }; grid.Children.Add(badge);
        var text = Ui.Stack(4); text.Margin = new(15); text.VerticalAlignment = VerticalAlignment.Bottom; text.Children.Add(Ui.Text("资料库精选", 12, true));
        var name = Ui.Text(track.Album, 18, true); name.MaxLines = 2; name.TextTrimming = TextTrimming.CharacterEllipsis; text.Children.Add(name);
        var artist = Ui.Text(track.DisplayArtist, 14); artist.MaxLines = 1; artist.TextTrimming = TextTrimming.CharacterEllipsis; text.Children.Add(artist); grid.Children.Add(text);
        var button = new Button { Content = grid, Padding = new(0), BorderThickness = new(0), CornerRadius = new(10), Background = Ui.Brush(0, 0, 0, 0) };
        if (track.Cover.Length > 0) _ = Guard(async () =>
        {
            var artwork = await FeaturedArtworkAsync(track.Cover);
            var ink = artwork.Dark ? Ui.Brush(255, 0, 0, 0) : Ui.Brush(255, 255, 255, 255);
            brand.Children.Clear(); brand.Children.Add(Icons.Create("songs", 15, ink: ink)); brand.Children.Add(Ui.Text("AM Dowloader", 12, true, ink));
            badge.Background = artwork.Backing ? (artwork.Dark ? Ui.Brush(180, 255, 255, 255) : Ui.Brush(180, 0, 0, 0)) : null;
            image.Source = artwork.Image;
        });
        button.Click += (_, _) => Navigate("album:" + track.AlbumKey); Ui.AddMenu(button, () => AlbumMenu(tracks.Where(x => x.AlbumKey == track.AlbumKey).ToList())); return button;
    }
    private sealed record FeaturedArtwork(BitmapImage Image, bool Dark, bool Backing);
    private readonly Dictionary<string, (long Stamp, long Length, Task<FeaturedArtwork> Load)> featuredArtwork = new(StringComparer.OrdinalIgnoreCase);
    private Task<FeaturedArtwork> FeaturedArtworkAsync(string cover)
    {
        var file = new FileInfo(cover); var stamp = file.LastWriteTimeUtc.Ticks; var length = file.Length;
        if (featuredArtwork.TryGetValue(cover, out var cached) && cached.Stamp == stamp && cached.Length == length && !cached.Load.IsFaulted && !cached.Load.IsCanceled) return cached.Load;
        if (featuredArtwork.Count >= 24) featuredArtwork.Remove(featuredArtwork.Keys.First());
        var load = LoadAsync(); featuredArtwork[cover] = (stamp, length, load); return load;
        async Task<FeaturedArtwork> LoadAsync()
        {
            var result = await Library.CallAsync("feature", new() { ["cover"] = cover });
            var source = await StorageFile.GetFileFromPathAsync(J.S(result, "path")); using var stream = await source.OpenReadAsync();
            var bitmap = new BitmapImage { DecodePixelWidth = 640 }; await bitmap.SetSourceAsync(stream);
            return new(bitmap, J.B(result, "dark"), J.B(result, "backing"));
        }
    }
    private Grid AlbumsPage()
    {
        var visible = Filter(tracks); var grid = new GridView { Name = "AlbumsGrid", Padding = new(32, 0, 32, 24), SelectionMode = ListViewSelectionMode.None, IsItemClickEnabled = false, Background = Ui.Brush(0, 0, 0, 0) };
        foreach (var album in visible.GroupBy(x => x.AlbumKey)) grid.Items.Add(AlbumCard(album.First(), 200));
        return PageFrame("专辑", Counts(visible), visible.Count == 0 ? EmptyState(tracks.Count > 0 ? "还没有匹配的音乐" : "把喜爱的音乐留在这里") : grid, Ui.Button("播放全部", () => _ = PlayTracksAsync(visible), icon: "play"), FilterBar(), edgeScroll: visible.Count > 0);
    }
    private Grid SongsPage()
    {
        var source = page == "favourites" ? tracks.Where(x => favourites.Contains(x.Path)).ToList() : tracks;
        if (page == "recent") source = source.OrderByDescending(x => x.Modified).ToList();
        var title = page switch { "recent" => "最近添加", "favourites" => "喜爱的歌曲", _ => "歌曲" };
        var visible = Filter(source);
        return PageFrame(title, source.Count == 0 ? "音乐会在这里，慢慢成为你的收藏。" : Counts(visible), visible.Count == 0 ? EmptyState(source.Count > 0 ? "还没有匹配的音乐" : "把喜爱的音乐留在这里") : TrackTable(visible), Ui.Button("播放全部", () => _ = PlayTracksAsync(visible), icon: "play"), FilterBar());
    }
    private Grid AlbumPage(List<Track> album)
    {
        if (album.Count == 0) return PageFrame("专辑", "", EmptyState());
        album = album.OrderBy(x => x.Disc).ThenBy(x => x.Number).ThenBy(x => x.Title).ToList(); var first = album[0];
        var stack = Ui.Stack(20); var banner = new Grid { Padding = new(24), Background = Ui.Brush(170, 84, 79, 88), CornerRadius = new(10), ColumnSpacing = 24 };
        banner.ColumnDefinitions.Add(new() { Width = new(165) }); banner.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) }); banner.Children.Add(Ui.Cover(first.Cover, 165));
        var detail = Ui.Stack(12); detail.Children.Add(Ui.Text("专辑", 13, true, Ui.Muted)); detail.Children.Add(Ui.Text(first.Album, 32, true)); detail.Children.Add(Ui.Text(first.DisplayArtist, 19, color: Ui.Accent)); detail.Children.Add(Ui.Text(first.Quality + (first.Edition.Length > 0 ? " · " + first.Edition : ""), 13, color: Ui.Muted));
        var actions = Ui.Stack(8, Orientation.Horizontal); actions.Children.Add(Ui.Button("播放", () => _ = PlayTracksAsync(album), true, "play")); actions.Children.Add(Ui.MenuIcon("专辑操作", () => AlbumMenu(album))); detail.Children.Add(actions);
        Grid.SetColumn(detail, 1); banner.Children.Add(detail); Ui.AddMenu(banner, () => AlbumMenu(album)); stack.Children.Add(banner);
        // The list owns scrolling so the surrounding header remains stable when lyrics open.
        var frame = new Grid { Padding = new(32, 24, 32, 24), RowSpacing = 18 }; frame.RowDefinitions.Add(new() { Height = GridLength.Auto }); frame.RowDefinitions.Add(new() { Height = new(1, GridUnitType.Star) }); frame.Children.Add(stack);
        var table = TrackTable(album); Grid.SetRow(table, 1); frame.Children.Add(table); return frame;
    }
    private Grid ArtistsPage()
    {
        var visible = Filter(tracks); var groups = visible.GroupBy(x => x.Artist).OrderBy(x => x.Key, StringComparer.CurrentCultureIgnoreCase).ToList();
        if (groups.Count == 0) return PageFrame("艺人", Counts(visible), EmptyState(tracks.Count > 0 ? "还没有匹配的音乐" : "把喜爱的音乐留在这里"), filtering: FilterBar());
        if (groups.All(x => x.Key != selectedArtist)) { selectedArtist = groups[0].Key; artistDetailOffset = 0; }
        var split = new Grid(); split.ColumnDefinitions.Add(new() { Width = new(205) }); split.ColumnDefinitions.Add(new() { Width = new(1) }); split.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) });
        var artists = new ListView { SelectionMode = ListViewSelectionMode.Single, Background = Ui.Brush(0, 0, 0, 0) };
        ScrollViewer? FindScroll(DependencyObject node)
        {
            if (node is ScrollViewer found) return found;
            for (var i = 0; i < VisualTreeHelper.GetChildrenCount(node); i++) if (FindScroll(VisualTreeHelper.GetChild(node, i)) is { } child) return child;
            return null;
        }
        artists.Loaded += (_, _) => { if (FindScroll(artists) is { } scroll) { scroll.ChangeView(null, artistListOffset, null, true); scroll.ViewChanged += (_, _) => artistListOffset = scroll.VerticalOffset; } };
        artists.Margin = new(0, 0, 10, 0);
        var divider = new Border { Background = Ui.Brush(255, 53, 53, 56) }; Grid.SetColumn(divider, 1); split.Children.Add(divider);
        var details = new ContentControl { Name = "ArtistDetails", HorizontalContentAlignment = HorizontalAlignment.Stretch, VerticalContentAlignment = VerticalAlignment.Stretch, Margin = new(26, 0, 4, 0) }; Grid.SetColumn(details, 2); split.Children.Add(artists); split.Children.Add(details);
        var sections = new List<(Grid Section, Border Image, FrameworkElement Right)>();
        void Resize()
        {
            var width = split.ActualWidth > 0 ? split.ActualWidth : Math.Max(400, pageHost.ActualWidth - 64);
            split.ColumnDefinitions[0].Width = new(Math.Clamp(Math.Round(width * .22), 145, 205));
            var compact = width < 740; var side = compact ? 120 : 156;
            foreach (var (section, image, right) in sections)
            {
                section.ColumnDefinitions[0].Width = compact ? new(1, GridUnitType.Star) : new(side);
                section.ColumnDefinitions[1].Width = compact ? new(0) : new(1, GridUnitType.Star);
                Grid.SetRow(right, compact ? 1 : 0); Grid.SetColumn(right, compact ? 0 : 1);
                image.Width = image.Height = side;
                if (image.Child is Grid artwork) { artwork.Width = artwork.Height = side; foreach (var child in artwork.Children.OfType<Image>()) child.Width = child.Height = side; }
            }
        }
        foreach (var group in groups)
        {
            var row = Ui.Stack(10, Orientation.Horizontal); row.Children.Add(Ui.Cover(group.First().Cover, 34, 17)); var label = Ui.Text(group.Key); label.MaxWidth = 135; label.MaxLines = 1; label.TextTrimming = TextTrimming.CharacterEllipsis; row.Children.Add(label);
            artists.Items.Add(new ListViewItem { Content = row, Tag = group.Key, Padding = new(8), CornerRadius = new(6) });
        }
        void Select()
        {
            var group = groups.First(x => x.Key == selectedArtist); var content = Ui.Stack(22); sections.Clear();
            var heading = new Grid { ColumnSpacing = 12 }; heading.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) }); heading.ColumnDefinitions.Add(new() { Width = GridLength.Auto });
            var name = Ui.Stack(8); name.Children.Add(Ui.Text(selectedArtist, 28, true)); name.Children.Add(Ui.Text($"{group.Select(x => x.AlbumKey).Distinct().Count()} 张专辑 · {group.Count()} 首歌曲", 13, color: Ui.Muted)); heading.Children.Add(name);
            var actions = Ui.Stack(10, Orientation.Horizontal); actions.VerticalAlignment = VerticalAlignment.Top;
            var play = Ui.Icon("play", "播放艺人歌曲", () => _ = PlayTracksAsync(group), 18); play.Foreground = Ui.Accent; actions.Children.Add(play);
            var random = Ui.Icon("shuffle", "随机播放艺人歌曲", () => _ = PlayTracksAsync(group, random: true), 18); random.Foreground = Ui.Accent; actions.Children.Add(random);
            Grid.SetColumn(actions, 1); heading.Children.Add(actions); var headingStack = Ui.Stack(8); headingStack.Children.Add(heading); headingStack.Children.Add(new Border { Height = 1, Background = Ui.Brush(255, 50, 50, 53) }); content.Children.Add(headingStack);
            foreach (var album in group.GroupBy(x => x.AlbumKey))
            {
                var items = album.OrderBy(x => x.Disc).ThenBy(x => x.Number).ToList(); var first = items[0];
                var section = new Grid { ColumnSpacing = 22, RowSpacing = 12 }; section.ColumnDefinitions.Add(new() { Width = new(156) }); section.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) }); section.RowDefinitions.Add(new() { Height = GridLength.Auto }); section.RowDefinitions.Add(new() { Height = GridLength.Auto });
                var cover = Ui.Stack(6); var image = Ui.Cover(first.Cover, 156); image.HorizontalAlignment = HorizontalAlignment.Left; image.Tapped += (_, _) => Navigate("album:" + first.AlbumKey); cover.Children.Add(image); cover.Children.Add(Ui.Text($"{items.Count} 首歌曲 · {Text.Duration(items.Sum(x => x.Duration))}", 12, color: Ui.Muted)); section.Children.Add(cover);
                var right = Ui.Stack(10); var albumHeading = new Grid { ColumnSpacing = 12 }; albumHeading.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) }); albumHeading.ColumnDefinitions.Add(new() { Width = GridLength.Auto }); albumHeading.Children.Add(Ui.Text(first.Album, 21, true));
                var playAlbum = Ui.Icon("play", "播放专辑：" + first.Album, () => _ = PlayTracksAsync(items), 18); playAlbum.Foreground = Ui.Accent; Grid.SetColumn(playAlbum, 1); albumHeading.Children.Add(playAlbum); right.Children.Add(albumHeading); right.Children.Add(Ui.Text(string.Join(" · ", new[] { first.Edition, first.Quality }.Where(x => x.Length > 0)), 13, color: Ui.Muted));
                foreach (var track in items)
                {
                    var row = new Grid { Padding = new(10), Background = Ui.Brush(75, 70, 68, 75), CornerRadius = new(7), ColumnSpacing = 10 };
                    var normal = row.Background; row.BackgroundTransition = new BrushTransition { Duration = TimeSpan.FromMilliseconds(83) };
                    row.PointerEntered += (_, _) => row.Background = Ui.Brush(32, 255, 255, 255); row.PointerExited += (_, _) => row.Background = normal;
                    row.ColumnDefinitions.Add(new() { Width = new(24) }); row.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) }); row.ColumnDefinitions.Add(new() { Width = new(45) }); row.ColumnDefinitions.Add(new() { Width = new(32) });
                    row.Children.Add(Ui.Text(track.Number.ToString())); var text = Ui.Stack(0); text.Children.Add(Ui.Text(track.Title)); text.Children.Add(Ui.Text(track.Artist, 12, color: Ui.Muted)); Grid.SetColumn(text, 1); row.Children.Add(text);
                    var time = Ui.Text(track.TimeText); Grid.SetColumn(time, 2); row.Children.Add(time); var more = Ui.MenuIcon("歌曲操作", () => TrackMenu([track], items, items.IndexOf(track)), 14); Grid.SetColumn(more, 3); row.Children.Add(more);
                    row.DoubleTapped += (_, _) => _ = PlayTracksAsync(items, items.IndexOf(track)); Ui.AddMenu(row, () => TrackMenu([track], items, items.IndexOf(track))); right.Children.Add(row);
                }
                Ui.AddMenu(section, () => AlbumMenu(items)); Grid.SetColumn(right, 1); section.Children.Add(right); content.Children.Add(section); sections.Add((section, image, right));
            }
            Resize(); var scroll = Ui.Scroll(content); scroll.Loaded += (_, _) => scroll.ChangeView(null, artistDetailOffset, null, true);
            scroll.ViewChanged += (_, _) => { if (ReferenceEquals(details.Content, scroll)) artistDetailOffset = scroll.VerticalOffset; }; details.Content = scroll; if (artists.IsLoaded) Ui.Animate(details);
        }
        artists.SelectionChanged += (_, _) => { if (artists.SelectedItem is ListViewItem item) { if (selectedArtist != (string)item.Tag) artistDetailOffset = 0; selectedArtist = (string)item.Tag; Select(); } };
        artists.SelectedIndex = groups.FindIndex(x => x.Key == selectedArtist);
        split.SizeChanged += (_, _) => Resize();
        return PageFrame("艺人", Counts(visible), split, Ui.Button("播放全部", () => _ = PlayTracksAsync(visible), icon: "play"), FilterBar());
    }
    private List<Track> Filter(IEnumerable<Track> source)
    {
        return source.Where(x => (!filters.TryGetValue("format", out var format) || Equals(format, "") || Equals(format, x.FormatName)) &&
            (!filters.TryGetValue("rate", out var rate) || Equals(rate, 0) || Equals(rate, x.Rate)) &&
            (!filters.TryGetValue("bits", out var bits) || Equals(bits, 0) || Equals(bits, x.Bits)) &&
            (!filters.TryGetValue("year", out var year) || Equals(year, 0) || Equals(year, x.Year))).ToList();
    }
    private Grid FilterBar()
    {
        var row = new Grid { Name = "LibraryFilters", ColumnSpacing = 8, RowSpacing = 8 }; for (var i = 0; i < 6; i++) row.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) });
        row.RowDefinitions.Add(new() { Height = GridLength.Auto }); row.RowDefinitions.Add(new() { Height = GridLength.Auto });
        void Add(int column, string key, string label, IEnumerable<(string Label, object Value)> items, object empty)
        {
            var combo = Ui.Combo(new[] { (label, empty) }.Concat(items), filters.GetValueOrDefault(key, empty)); Grid.SetColumn(combo, column); row.Children.Add(combo);
            combo.SelectionChanged += (_, _) => { filters[key] = ((ComboBoxItem)combo.SelectedItem).Tag; RenderPage(); };
        }
        Add(0, "format", "全部格式", tracks.Select(x => x.FormatName).Distinct().Order().Select(x => (x, (object)x)), "");
        Add(1, "rate", "全部采样率", tracks.Where(x => x.Rate > 0).Select(x => x.Rate).Distinct().Order().Select(x => ($"{x / 1000d:g} kHz", (object)x)), 0);
        Add(2, "bits", "全部位深", tracks.Where(x => x.Bits > 0).Select(x => x.Bits).Distinct().Order().Select(x => ($"{x} bit", (object)x)), 0);
        Add(3, "year", "全部年份", tracks.Where(x => x.Year > 0).Select(x => x.Year).Distinct().OrderDescending().Select(x => (x.ToString(), (object)x)), 0);
        var reset = Ui.Button("重置", () => { filters.Clear(); RenderPage(); }); Grid.SetColumn(reset, 4); row.Children.Add(reset);
        var duplicates = Ui.Button("查找重复", () => _ = DuplicatesAsync()); Grid.SetColumn(duplicates, 5); row.Children.Add(duplicates);
        void Resize()
        {
            var compact = (row.ActualWidth > 0 ? row.ActualWidth : pageHost.ActualWidth - 64) < 700;
            for (var i = 0; i < 6; i++) { row.ColumnDefinitions[i].Width = compact && i >= 3 ? new(0) : new(1, GridUnitType.Star); Grid.SetColumn((FrameworkElement)row.Children[i], compact ? i % 3 : i); Grid.SetRow((FrameworkElement)row.Children[i], compact ? i / 3 : 0); }
        }
        Resize(); row.SizeChanged += (_, _) => Resize(); return row;
    }
    private Border TrackTable(List<Track> values, Playlist? playlist = null)
    {
        var rows = new ObservableCollection<TrackRow>(values.Select((x, i) => new TrackRow(x, i, favourites.Contains(x.Path), playlist?.Entries[i])));
        var list = new ListView { ItemsSource = rows, SelectionMode = ListViewSelectionMode.Extended, CanDragItems = true, CanReorderItems = playlist is not null, AllowDrop = playlist is not null, Background = Ui.Brush(0, 0, 0, 0), HorizontalContentAlignment = HorizontalAlignment.Stretch };
        list.Resources["ListViewItemCornerRadius"] = new CornerRadius(7);
        list.ItemContainerStyle = new Style { TargetType = typeof(ListViewItem), BasedOn = (Style)Application.Current.Resources["DefaultListViewItemStyle"], Setters = { new Setter(Control.PaddingProperty, new Thickness(0)), new Setter(FrameworkElement.MarginProperty, new Thickness(16, 0, 12, 0)) } };
        foreach (var state in new[] { "PointerOver", "Selected", "SelectedPointerOver", "Pressed", "SelectedPressed", "SelectedDisabled" }) list.Resources["ListViewItemBackground" + state] = Ui.Brush(0, 0, 0, 0);
        list.ContainerContentChanging += TrackRowHighlight.Attach;
        list.ItemTemplate = (DataTemplate)XamlReader.Load("""
            <DataTemplate xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation">
              <Grid Padding="10,12" ColumnSpacing="12" MinHeight="52" CornerRadius="7" Background="{Binding Background}">
                <Grid.ColumnDefinitions><ColumnDefinition Width="30"/><ColumnDefinition Width="4*"/><ColumnDefinition Width="1.1*"/><ColumnDefinition Width="1.4*"/><ColumnDefinition Width="1.4*"/><ColumnDefinition Width="45"/></Grid.ColumnDefinitions>
                <TextBlock Text="{Binding IndexText}" VerticalAlignment="Center" Foreground="{Binding MarkerBrush}"/>
                <Viewbox Width="14" Height="14" HorizontalAlignment="Left" VerticalAlignment="Center" Visibility="{Binding FavouriteVisibility}">
                  <Canvas Width="24" Height="24"><Path Data="{Binding FavouriteData}" Fill="{Binding MarkerBrush}"/></Canvas>
                </Viewbox>
                <TextBlock Grid.Column="1" Text="{Binding Track.Title}" TextWrapping="Wrap" MaxLines="2" VerticalAlignment="Center"/>
                <TextBlock Grid.Column="2" Text="{Binding Track.Artist}" TextWrapping="Wrap" MaxLines="2" VerticalAlignment="Center"/>
                <TextBlock Grid.Column="3" Text="{Binding Track.Album}" TextWrapping="Wrap" MaxLines="2" VerticalAlignment="Center"/>
                <TextBlock Grid.Column="4" Text="{Binding Track.Quality}" TextWrapping="Wrap" MaxLines="2" VerticalAlignment="Center"/>
                <TextBlock Grid.Column="5" Text="{Binding Track.TimeText}" VerticalAlignment="Center" HorizontalAlignment="Right"/>
              </Grid>
            </DataTemplate>
            """);
        list.DoubleTapped += (_, _) => { if (list.SelectedItem is TrackRow row) _ = PlayTracksAsync(rows.Select(x => x.Track), rows.IndexOf(row)); };
        list.KeyDown += (_, e) => { if (e.Key == Windows.System.VirtualKey.Enter && list.SelectedItem is TrackRow row) { e.Handled = true; _ = PlayTracksAsync(rows.Select(x => x.Track), rows.IndexOf(row)); } };
        list.RightTapped += (_, e) =>
        {
            var node = e.OriginalSource as DependencyObject; while (node is not null && node is not ListViewItem) node = VisualTreeHelper.GetParent(node);
            if (node is not ListViewItem container || container.Content is not TrackRow row) return;
            if (!list.SelectedItems.Contains(row)) list.SelectedItem = row;
            var selected = list.SelectedItems.Cast<TrackRow>().ToList(); var menu = TrackMenu(selected.Select(x => x.Track).ToList(), rows.Select(x => x.Track).ToList(), rows.IndexOf(row));
            if (playlist is not null) menu.Items.Add(Ui.MenuItem("从此歌单移除", () => { foreach (var index in selected.Select(x => rows.IndexOf(x)).OrderDescending()) playlist.Entries.RemoveAt(index); SavePlaylists(); RenderPage(); }));
            e.Handled = true; menu.ShowAt(list, e.GetPosition(list));
        };
        list.DragItemsStarting += (_, e) => { e.Data.SetText("am-tracks:" + JsonSerializer.Serialize(e.Items.Cast<TrackRow>().Select(x => x.Track.Path))); if (playlist is not null) e.Data.Properties["am-playlist-id"] = playlist.Id; e.Data.RequestedOperation = DataPackageOperation.Copy | DataPackageOperation.Move; };
        if (playlist is not null)
        {
            list.DragItemsCompleted += (_, e) => { if (e.DropResult == DataPackageOperation.Move) { playlist.Entries = rows.Select(x => x.Entry!).ToList(); SavePlaylists(); RenderPage(); } };
            list.DragOver += (_, e) => { e.AcceptedOperation = e.DataView.Properties.TryGetValue("am-playlist-id", out var origin) && Equals(origin, playlist.Id) ? DataPackageOperation.Move : DataPackageOperation.Copy; };
        }
        var header = new Grid { Padding = new(22, 12, 22, 12), ColumnSpacing = 12, Background = Ui.Brush(75, 15, 15, 17) };
        foreach (var width in new[] { new GridLength(30), new(4, GridUnitType.Star), new(1.1, GridUnitType.Star), new(1.4, GridUnitType.Star), new(1.4, GridUnitType.Star), new(45) }) header.ColumnDefinitions.Add(new() { Width = width });
        var names = new[] { "", "标题", "艺人", "专辑", "音质", "时长" }; for (var i = 0; i < names.Length; i++) { var text = Ui.Text(names[i], 13, color: Ui.Muted); Grid.SetColumn(text, i); header.Children.Add(text); }
        var grid = new Grid { CornerRadius = new(10) }; grid.RowDefinitions.Add(new() { Height = GridLength.Auto }); grid.RowDefinitions.Add(new() { Height = new(1, GridUnitType.Star) }); grid.Children.Add(header); Grid.SetRow(list, 1); grid.Children.Add(list);
        return new Border { Child = grid, CornerRadius = new(10), Background = Ui.Brush(55, 13, 13, 15) };
    }
    private Grid SearchPage()
    {
        var term = search.Text.Trim(); var local = tracks.Where(x => (x.Title + " " + x.Artist + " " + x.Album).Contains(term, StringComparison.CurrentCultureIgnoreCase)).ToList();
        var grid = new Grid { RowSpacing = 20 }; grid.RowDefinitions.Add(new() { Height = new(1, GridUnitType.Star) }); grid.RowDefinitions.Add(new() { Height = new(1, GridUnitType.Star) });
        grid.Children.Add(TrackTable(local)); var remote = Ui.Stack(8); remote.Children.Add(Ui.Text("Apple Music", 22, true));
        if (catalog.Count == 0) remote.Children.Add(Ui.Text(catalogMessage.Length > 0 ? catalogMessage : "没有找到匹配的歌曲", color: Ui.Muted));
        foreach (var item in catalog)
        {
            var row = Ui.Stack(10, Orientation.Horizontal); row.Children.Add(Ui.Image(J.S(item, "artworkUrl100"), 42)); row.Children.Add(Ui.Text(J.S(item, "trackName") + " · " + J.S(item, "artistName")));
            row.Children.Add(Ui.Button("下载", () => _ = AddDownloadAsync(J.S(item, "trackViewUrl"), Store.Get("codec", "alac")), icon: "add")); remote.Children.Add(row);
        }
        var scroll = Ui.Scroll(remote); Grid.SetRow(scroll, 1); grid.Children.Add(scroll); return PageFrame("搜索", $"“{term}” · 资料库 {local.Count} 首歌曲", grid);
    }
}
public sealed class TrackRow(Track track, int index, bool favourite, PlaylistEntry? entry = null)
{
    public Track Track { get; } = track;
    public PlaylistEntry? Entry { get; } = entry;
    public int OriginalIndex { get; } = index;
    public string IndexText => favourite ? "" : (OriginalIndex + 1).ToString();
    public string FavouriteData => Icons.StarData;
    public Visibility FavouriteVisibility => favourite ? Visibility.Visible : Visibility.Collapsed;
    public Brush MarkerBrush => favourite ? Ui.Accent : Ui.Brush(255, 205, 205, 211);
    public Brush Background => OriginalIndex % 2 == 0 ? Ui.Brush(65, 65, 63, 70) : Ui.Brush(0, 0, 0, 0);
}
