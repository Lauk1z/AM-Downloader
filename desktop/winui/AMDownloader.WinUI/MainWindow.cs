using System.Text.Json;
using System.Numerics;
using AMDownloader.Core;
using AMDownloader.WinUI.Services;
using AMDownloader.WinUI.Views;
using Microsoft.UI;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Windows.Graphics;

namespace AMDownloader.WinUI;

public sealed partial class MainWindow : Window
{
    private readonly LaunchOptions options;
    internal readonly StateStore Store;
    internal readonly RuntimePaths Paths;
    internal readonly LibraryService Library;
    internal readonly Accounts Accounts;
    internal AudioService Audio = null!;
    private BackendService? backend;
    private readonly Grid root = new();
    private readonly Image backdrop = new() { Stretch = Stretch.UniformToFill, Opacity = .14 };
    private readonly StackPanel navigation = Ui.Stack(3);
    private readonly Border navigationIndicator = new() { Width = 3, Height = 16, CornerRadius = new(1.5), Background = Ui.Accent, HorizontalAlignment = HorizontalAlignment.Left, VerticalAlignment = VerticalAlignment.Top, IsHitTestVisible = false, Visibility = Visibility.Collapsed };
    private Vector3? navigationIndicatorTarget;
    private Microsoft.UI.Composition.Vector3KeyFrameAnimation? navigationMotion;
    private readonly ContentControl pageHost = new() { HorizontalContentAlignment = HorizontalAlignment.Stretch, VerticalContentAlignment = VerticalAlignment.Stretch };
    private readonly SplitView body = new() { PanePlacement = SplitViewPanePlacement.Right, DisplayMode = SplitViewDisplayMode.Inline, OpenPaneLength = 310, CompactPaneLength = 0, IsPaneOpen = false, PaneBackground = Ui.Brush(35, 70, 65, 74) };
    private readonly TextBox search = new() { PlaceholderText = "搜索资料库", Height = 34 };
    private readonly TextBlock notice = Ui.Text("正在读取音乐…", 11, color: Ui.Muted);
    private readonly TextBlock backendStatus = Ui.Text("●  后端待命", 11, color: Ui.Muted);
    private readonly Image playerCover = Ui.Image("", 52);
    private readonly TextBlock playerTitle = Ui.Text("AM Dowloader", 14, true);
    private readonly TextBlock playerArtist = Ui.Text("选择一首音乐开始播放", 13, color: Ui.Muted);
    private readonly Slider progress = new() { MinHeight = 10, Height = 14, Margin = new(-8, -6, -8, -7), Minimum = 0, Maximum = 1 };
    private readonly TextBlock elapsed = Ui.Text("", 10, color: Ui.Muted), remaining = Ui.Text("", 10, color: Ui.Muted);
    private Button playButton = null!, shuffleButton = null!, favouriteButton = null!;
    private StackPanel playerActions = null!;
    private Border volumePanel = null!;
    private Slider volumeSlider = null!;
    private DispatcherTimer volumeTimer = null!;
    private readonly Dictionary<string, Button> navButtons = [];
    private readonly List<FrameworkElement> captionControls = [];
    private DispatcherTimer searchTimer = null!;
    private TrayIcon? tray;
    private bool updatingProgress, seeking, quitting, closeDialogOpen;
    private string page = "home", openPanel = "", backdropSource = "";
    private string activeAlbum = "", selectedArtist = "";
    private double artistListOffset, artistDetailOffset;
    private int searchSerial;
    private List<Track> tracks = [], queue = [];
    private int playIndex = -1;
    private bool shuffled, repeat;
    private readonly ShuffleOrder shuffle = new();
    private HashSet<string> favourites;
    private List<Playlist> playlists;
    private List<DownloadJob> jobs;
    private string? activeJob;
    private bool queuePaused, scanning, scanAgain;
    private readonly InterTrackGap trackGap = new();
    private bool gapWaiting => trackGap.Waiting;
    private ContentDialog? activeDialog;
    private ToolWindow? loginWindow, outputWindow;
    private LoginView? loginView;
    private bool autoLoginAttempted;
    private string logs = "";
    private List<JsonElement> catalog = [];
    private string catalogMessage = "";
    private string speeds = "下载 0.00 kB/s · 解密 0.00 kB/s";
    private readonly Dictionary<string, object?> filters = [];

    public MainWindow(LaunchOptions options)
    {
        this.options = options; Store = new(options.Profile); Paths = new(options.Resources); Library = new(Paths, Store); Accounts = new(Store);
        favourites = Store.Get("favourites", new List<string>()).ToHashSet(); playlists = Store.Get("playlists", new List<Playlist>());
        jobs = Store.Get("jobs", new List<DownloadJob>()); foreach (var job in jobs) if (job.State is not ("DONE" or "FAILED" or "cancelled")) job.State = "queued";
        queuePaused = jobs.Count > 0;
        Audio = new(Paths, Library, Store, Dispatch); Audio.Changed += UpdatePlayer; Audio.Ended += TrackEnded; Audio.Failed += Toast;
        trackGap.Ready += () => _ = SkipAsync(1); trackGap.Changed += UpdatePlayer;
        Title = "AM Dowloader · 音乐";
        var scale = GetDpiForWindow(WinRT.Interop.WindowNative.GetWindowHandle(this)) / 96d;
        var work = DisplayArea.GetFromWindowId(AppWindow.Id, DisplayAreaFallback.Nearest).WorkArea;
        AppWindow.Resize(new SizeInt32((int)Math.Min(1440 * scale, work.Width * .94), (int)Math.Min(900 * scale, work.Height * .94)));
        AppWindow.SetIcon(Path.Combine(AppContext.BaseDirectory, "Assets", "app.ico"));
        ExtendsContentIntoTitleBar = true;
        AppWindow.TitleBar.ButtonBackgroundColor = Colors.Transparent; AppWindow.TitleBar.ButtonInactiveBackgroundColor = Colors.Transparent;
        AppWindow.TitleBar.ButtonForegroundColor = ColorHelper.FromArgb(255, 200, 200, 207);
        AppWindow.TitleBar.PreferredHeightOption = TitleBarHeightOption.Standard;
        BuildShell(); AppWindow.Closing += OnClosing;
        tray = new TrayIcon(WinRT.Interop.WindowNative.GetWindowHandle(this), Path.Combine(AppContext.BaseDirectory, "Assets", "app.ico"), HandleTray);
        AppWindow.Changed += (_, e) => { if (e.DidSizeChange) Dispatch(UpdateDragRegions); };
        root.Loaded += (_, _) => UpdateDragRegions();
        searchTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(280) };
        searchTimer.Tick += (_, _) => { searchTimer.Stop(); _ = SearchChangedAsync(); };
        search.TextChanged += (_, _) => { searchTimer.Stop(); searchTimer.Start(); };
        search.KeyDown += (_, e) => { if (e.Key == Windows.System.VirtualKey.Enter) { searchTimer.Stop(); _ = SearchChangedAsync(); } };
    }
    private void BuildShell()
    {
        root.Background = Ui.Brush(255, 32, 32, 34); root.Children.Add(backdrop);
        var shell = new Grid(); shell.ColumnDefinitions.Add(new() { Width = new(224) }); shell.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) }); root.Children.Add(shell);
        var sidebar = new Grid { Background = Ui.Brush(100, 38, 36, 43), Padding = new(8, 13, 8, 12), RowSpacing = 12 };
        foreach (var height in new[] { GridLength.Auto, GridLength.Auto, new(1, GridUnitType.Star), GridLength.Auto, GridLength.Auto, GridLength.Auto }) sidebar.RowDefinitions.Add(new() { Height = height });
        var branding = new Grid { Margin = new(10, 0, 0, 0), ColumnSpacing = 8 }; branding.ColumnDefinitions.Add(new() { Width = new(23) }); branding.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) }); branding.ColumnDefinitions.Add(new() { Width = new(29) });
        branding.Children.Add(Ui.Image(Path.Combine(AppContext.BaseDirectory, "Assets", "app.svg"), 23)); var brandName = Ui.Text("AM Dowloader", 16, true); brandName.TextWrapping = TextWrapping.NoWrap; Grid.SetColumn(brandName, 1); branding.Children.Add(brandName); var refresh = Ui.Icon("\uE72C", "重新扫描资料库", () => _ = ScanAsync(), 17); Grid.SetColumn(refresh, 2); branding.Children.Add(refresh); sidebar.Children.Add(branding); captionControls.AddRange([refresh, search]);
        Grid.SetRow(search, 1); sidebar.Children.Add(search);
        var navSurface = new Grid(); navSurface.Children.Add(navigation); navSurface.Children.Add(navigationIndicator);
        navigation.Loaded += (_, _) => UpdateNavigationSelection(false); navigation.SizeChanged += (_, _) => UpdateNavigationSelection(false);
        var navScroll = Ui.Scroll(navSurface); Grid.SetRow(navScroll, 2); sidebar.Children.Add(navScroll);
        notice.Margin = backendStatus.Margin = new(12, 0, 4, 0); Grid.SetRow(notice, 3); Grid.SetRow(backendStatus, 4); sidebar.Children.Add(notice); sidebar.Children.Add(backendStatus);
        var footer = new Grid(); footer.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) }); footer.ColumnDefinitions.Add(new() { Width = GridLength.Auto });
        footer.Children.Add(Ui.Button("⚙  设置", () => Navigate("settings"))); var add = Ui.Icon("\uE710", "添加音乐 · Ctrl+L", () => _ = AddMusicAsync(), 16); Grid.SetColumn(add, 1); footer.Children.Add(add); Grid.SetRow(footer, 5); sidebar.Children.Add(footer); shell.Children.Add(sidebar);
        var main = new Grid(); main.RowDefinitions.Add(new() { Height = new(64) }); main.RowDefinitions.Add(new() { Height = new(1, GridUnitType.Star) }); Grid.SetColumn(main, 1); shell.Children.Add(main);
        main.Children.Add(BuildPlayer()); body.Content = pageHost; Grid.SetRow(body, 1); main.Children.Add(body);
        Content = root; BuildNavigation();
        root.AllowDrop = true; root.DragOver += (_, e) => { if (e.AcceptedOperation == Windows.ApplicationModel.DataTransfer.DataPackageOperation.None && e.DataView.Contains(Windows.ApplicationModel.DataTransfer.StandardDataFormats.StorageItems)) e.AcceptedOperation = Windows.ApplicationModel.DataTransfer.DataPackageOperation.Copy; };
        root.Drop += async (_, e) => { if (e.DataView.Contains(Windows.ApplicationModel.DataTransfer.StandardDataFormats.StorageItems)) { var items = await e.DataView.GetStorageItemsAsync(); await ImportPathsAsync(items.Select(x => x.Path)); } };
        AddShortcut(Windows.System.VirtualKey.L, true, () => _ = AddMusicAsync()); AddShortcut(Windows.System.VirtualKey.O, true, () => _ = ImportFilesAsync());
        AddShortcut(Windows.System.VirtualKey.F, true, () => search.Focus(FocusState.Keyboard));
        AddShortcut(Windows.System.VirtualKey.Right, true, () => _ = SkipAsync(1)); AddShortcut(Windows.System.VirtualKey.Left, true, () => _ = SkipAsync(-1));
        AddShortcut(Windows.System.VirtualKey.F11, false, ToggleFullscreen);
    }
    private Grid BuildPlayer()
    {
        var bar = new Grid { Background = Ui.Brush(40, 68, 65, 70), Padding = new(12, 6, 14, 6), ColumnSpacing = 10 };
        foreach (var width in new[] { new GridLength(27, GridUnitType.Star), new(53, GridUnitType.Star), new(20, GridUnitType.Star), new(125) }) bar.ColumnDefinitions.Add(new() { Width = width });
        var transport = Ui.Stack(2, Orientation.Horizontal); transport.HorizontalAlignment = HorizontalAlignment.Center;
        shuffleButton = Ui.Icon("\uE8B1", "随机播放 · 每轮不重复", () => { CancelGap(); shuffled = !shuffled; shuffle.Reset(); UpdatePlayer(); RefreshPanel(); });
        playButton = Ui.Icon("\uE768", "播放 / 暂停", () => _ = TogglePlayAsync(), 28);
        foreach (var item in new[] { shuffleButton, Ui.Icon("\uE892", "上一首", () => _ = SkipAsync(-1), 25), playButton, Ui.Icon("\uE893", "下一首", () => _ = SkipAsync(1), 25), Ui.Icon("\uE8EE", "循环播放列表", () => { repeat = !repeat; Toast(repeat ? "循环播放已开启" : "循环播放已关闭"); }, 20) }) transport.Children.Add(item);
        bar.Children.Add(transport);
        var playing = new Grid { Background = Ui.Brush(150, 60, 60, 63), CornerRadius = new(5), ColumnSpacing = 6 };
        playing.ColumnDefinitions.Add(new() { Width = new(52) }); playing.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) });
        playing.Children.Add(playerCover); var details = new Grid { Padding = new(2, 2, 5, 0) }; Grid.SetColumn(details, 1); playing.Children.Add(details);
        details.RowDefinitions.Add(new() { Height = new(1, GridUnitType.Star) }); details.RowDefinitions.Add(new() { Height = new(0) }); details.RowDefinitions.Add(new() { Height = new(4) });
        var titleRow = new Grid(); titleRow.ColumnDefinitions.Add(new() { Width = new(28) }); titleRow.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) }); titleRow.ColumnDefinitions.Add(new() { Width = new(28) });
        var quality = Ui.Icon("lossless", "音质与音频输出链路", () => _ = ShowOutputChainAsync(), 19); titleRow.Children.Add(quality);
        var labels = Ui.Stack(2); labels.HorizontalAlignment = HorizontalAlignment.Center; labels.VerticalAlignment = VerticalAlignment.Center; playerTitle.TextWrapping = playerArtist.TextWrapping = TextWrapping.NoWrap; playerTitle.TextTrimming = playerArtist.TextTrimming = TextTrimming.CharacterEllipsis;
        var title = Ui.Stack(2, Orientation.Horizontal); title.HorizontalAlignment = HorizontalAlignment.Center; title.Children.Add(playerTitle); var menuButton = Ui.Icon("\uE712", "歌曲操作", PlayerMenu, 15); menuButton.Padding = new(3, 0, 3, 0); menuButton.Foreground = Ui.Accent; title.Children.Add(menuButton); labels.Children.Add(title); labels.Children.Add(playerArtist); Grid.SetColumn(labels, 1); titleRow.Children.Add(labels);
        favouriteButton = Ui.Icon("\uE734", "喜爱歌曲", ToggleCurrentFavourite, 12); Grid.SetColumn(favouriteButton, 2); titleRow.Children.Add(favouriteButton); details.Children.Add(titleRow);
        var times = new Grid { VerticalAlignment = VerticalAlignment.Bottom, Opacity = 0, IsHitTestVisible = false }; times.Children.Add(elapsed); remaining.HorizontalAlignment = HorizontalAlignment.Right; times.Children.Add(remaining); details.Children.Add(times);
        playing.PointerEntered += (_, _) => times.Opacity = 1; playing.PointerExited += (_, _) => times.Opacity = 0;
        Grid.SetRow(progress, 2); details.Children.Add(progress);
        progress.Background = Ui.Brush(255, 103, 103, 107); progress.Foreground = Ui.Brush(255, 217, 217, 222); progress.Margin = new(0, -4, 0, -4); progress.MinHeight = 0; progress.Height = 12;
        progress.Template = (ControlTemplate)Microsoft.UI.Xaml.Markup.XamlReader.Load("""
          <ControlTemplate xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" TargetType="Slider">
            <Grid x:Name="SliderContainer" Background="Transparent"><Grid x:Name="HorizontalTemplate">
              <Grid.ColumnDefinitions><ColumnDefinition Width="Auto"/><ColumnDefinition Width="Auto"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
              <Rectangle x:Name="HorizontalTrackRect" Grid.ColumnSpan="3" Height="2" Fill="{TemplateBinding Background}" VerticalAlignment="Center"/>
              <Rectangle x:Name="HorizontalDecreaseRect" Height="2" Fill="{TemplateBinding Foreground}" VerticalAlignment="Center"/>
              <Thumb x:Name="HorizontalThumb" Grid.Column="1" Width="1" Height="10" Opacity="0"/>
            </Grid></Grid>
          </ControlTemplate>
          """);
        progress.AddHandler(UIElement.PointerPressedEvent, new PointerEventHandler((_, _) => seeking = true), true);
        progress.AddHandler(UIElement.PointerReleasedEvent, new PointerEventHandler(async (_, _) => { if (seeking) { seeking = false; await SeekTrackAsync((long)progress.Value); } }), true);
        progress.ValueChanged += async (_, _) => { if (!updatingProgress && !seeking && Audio.Current is not null) await SeekTrackAsync((long)progress.Value); };
        Grid.SetColumn(playing, 1); bar.Children.Add(playing);
        var actions = new Grid(); playerActions = Ui.Stack(2, Orientation.Horizontal); playerActions.HorizontalAlignment = HorizontalAlignment.Center;
        playerActions.Children.Add(Ui.Icon("\uE767", "音量", ShowVolume)); playerActions.Children.Add(Ui.Icon("\uE8F2", "歌词", () => TogglePanel("lyrics"))); playerActions.Children.Add(Ui.Icon("\uE8FD", "正在播放", () => TogglePanel("playing"))); actions.Children.Add(playerActions);
        volumeSlider = new Slider { Minimum = 0, Maximum = 100, Value = Audio.Volume, MinWidth = 0, Height = 32, MinHeight = 0, VerticalAlignment = VerticalAlignment.Center };
        volumeSlider.ValueChanged += async (_, _) => { if (volumePanel.Visibility == Visibility.Visible) { await Audio.SetVolumeAsync((int)volumeSlider.Value); Store.Set("volume", (int)volumeSlider.Value); } };
        var volume = new Grid { ColumnSpacing = 6 }; volume.ColumnDefinitions.Add(new() { Width = new(24) }); volume.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) }); volume.ColumnDefinitions.Add(new() { Width = new(24) });
        var volumeLow = Ui.Icon("volume-low", "收起音量", HideVolume, 18); volumeLow.Padding = new(3); volumeLow.HorizontalAlignment = HorizontalAlignment.Stretch; volume.Children.Add(volumeLow);
        Grid.SetColumn(volumeSlider, 1); volume.Children.Add(volumeSlider);
        var volumeHigh = (FrameworkElement)Icons.Create("volume", 18, ink: Ui.Muted); volumeHigh.HorizontalAlignment = HorizontalAlignment.Center; volumeHigh.VerticalAlignment = VerticalAlignment.Center; Grid.SetColumn(volumeHigh, 2); volume.Children.Add(volumeHigh);
        volumePanel = new Border { Child = volume, Padding = new(8, 4, 8, 4), Background = Ui.Brush(255, 43, 42, 47), CornerRadius = new(6), Visibility = Visibility.Collapsed, VerticalAlignment = VerticalAlignment.Center }; actions.Children.Add(volumePanel);
        volumeTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(450) }; volumeTimer.Tick += (_, _) => HideVolume();
        volumePanel.PointerEntered += (_, _) => volumeTimer.Stop(); volumePanel.PointerExited += (_, _) => volumeTimer.Start();
        volumePanel.KeyDown += (_, e) => { if (e.Key == Windows.System.VirtualKey.Escape) { HideVolume(); e.Handled = true; } };
        root.AddHandler(UIElement.PointerPressedEvent, new PointerEventHandler((_, e) => { if (volumePanel.Visibility != Visibility.Visible) return; var point = e.GetCurrentPoint(volumePanel).Position; if (point.X < 0 || point.X > volumePanel.ActualWidth || point.Y < 0 || point.Y > volumePanel.ActualHeight) HideVolume(); }), true);
        Grid.SetColumn(actions, 2); bar.Children.Add(actions);
        var drag = new Grid { Background = new SolidColorBrush(Colors.Transparent) }; Grid.SetColumn(drag, 3); bar.Children.Add(drag);
        captionControls.AddRange([transport, playing, actions]); bar.SizeChanged += (_, _) => Dispatch(UpdateDragRegions);
        return bar;
    }
    private void BuildNavigation()
    {
        navigation.Children.Clear(); navButtons.Clear();
        void Nav(string key, string title, bool indent = false)
        {
            var button = Ui.Button(title, () => Navigate(key)); button.HorizontalAlignment = HorizontalAlignment.Stretch; button.HorizontalContentAlignment = HorizontalAlignment.Stretch; button.BorderThickness = new(0); button.Padding = new(0); button.MinHeight = 36;
            button.Background = page == key ? Ui.Brush(255, 52, 52, 57) : new SolidColorBrush(Colors.Transparent);
            var row = new Grid { Padding = new(indent ? 22 : 2, 8, 8, 8), ColumnSpacing = 8 }; row.ColumnDefinitions.Add(new() { Width = new(3) }); row.ColumnDefinitions.Add(new() { Width = new(20) }); row.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) });
            var symbol = key switch { "home" => "home", "recent" => "recent", "artists" => "artist", "albums" => "album", "songs" => "songs", "favourites" => "favourites", "queue" => "download", _ => "playlist" };
            UIElement graphic = key.StartsWith("album:") && tracks.FirstOrDefault(x => x.AlbumKey == key[6..]) is { } album ? Ui.Cover(album.Cover, 20, 2) : Icons.Create(symbol, 19);
            Grid.SetColumn((FrameworkElement)graphic, 1); row.Children.Add(graphic);
            var name = Ui.Text(title.Contains("   ") ? title[(title.IndexOf("   ", StringComparison.Ordinal) + 3)..] : title, 14); name.TextTrimming = TextTrimming.CharacterEllipsis; name.TextWrapping = TextWrapping.NoWrap; Grid.SetColumn(name, 2); row.Children.Add(name); button.Content = row;
            navigation.Children.Add(button); navButtons[key] = button;
        }
        Nav("home", "⌂   主页"); navigation.Children.Add(Ui.Text("▤   资料库", 13, true, Ui.Muted));
        Nav("recent", "◷   最近添加", true); Nav("artists", "♩   艺人", true); Nav("albums", "▢   专辑", true); Nav("songs", "♫   歌曲", true);
        var heading = new Grid { Margin = new(12, 12, 4, 0) }; heading.Children.Add(Ui.Text("☷   播放列表", 13, true, Ui.Muted));
        var plus = Ui.Icon("\uE710", "新建或导入歌单", PlaylistCreationMenu, 14); plus.HorizontalAlignment = HorizontalAlignment.Right; heading.Children.Add(plus); navigation.Children.Add(heading);
        Nav("favourites", "☆   喜爱的歌曲", true); Nav("queue", "↓   下载队列", true);
        foreach (var list in playlists)
        {
            Nav(list.Id, "☷   " + list.Name, true); var button = navButtons[list.Id]; button.AllowDrop = true;
            button.DragOver += (_, e) => e.AcceptedOperation = Windows.ApplicationModel.DataTransfer.DataPackageOperation.Copy;
            button.Drop += async (_, e) => { e.Handled = true; await DropIntoPlaylistAsync(list, e.DataView); };
            Ui.AddMenu(button, () => PlaylistMenu(list));
        }
        foreach (var album in tracks.GroupBy(x => x.AlbumKey).Take(4)) { var key = "album:" + album.Key; Nav(key, album.First().Album); Ui.AddMenu(navButtons[key], () => AlbumMenu(album.ToList())); }
        navigation.UpdateLayout(); UpdateNavigationSelection(false);
    }
    private void UpdateNavigationSelection(bool animate)
    {
        foreach (var (key, button) in navButtons) button.Background = key == page ? Ui.Brush(255, 52, 52, 57) : Ui.Brush(0, 0, 0, 0);
        if (!navButtons.TryGetValue(page, out var selected) || !selected.IsLoaded)
        { navigationIndicator.Visibility = Visibility.Collapsed; return; }
        var row = (Grid)selected.Content;
        var point = row.TransformToVisual(navigation).TransformPoint(new(row.Padding.Left, (row.ActualHeight - navigationIndicator.Height) / 2));
        var target = new Vector3((float)point.X, (float)point.Y, 0);
        var visible = navigationIndicator.Visibility == Visibility.Visible; navigationIndicator.Visibility = Visibility.Visible;
        if (visible && navigationIndicatorTarget == target) return;
        navigationIndicatorTarget = target;
        if (!animate || !visible) { if (navigationMotion is not null) navigationIndicator.StopAnimation(navigationMotion); navigationIndicator.Translation = target; return; }
        var compositor = CompositionTarget.GetCompositorForCurrentThread(); var motion = compositor.CreateVector3KeyFrameAnimation();
        motion.Target = "Translation"; motion.InsertExpressionKeyFrame(0, "this.StartingValue");
        motion.InsertKeyFrame(1, target, compositor.CreateCubicBezierEasingFunction(new(.2f, 0), new(0, 1)));
        motion.Duration = TimeSpan.FromMilliseconds(250); navigationMotion = motion; navigationIndicator.StartAnimation(motion);
    }
    private void AddShortcut(Windows.System.VirtualKey key, bool ctrl, Action action)
    { var shortcut = new KeyboardAccelerator { Key = key, Modifiers = ctrl ? Windows.System.VirtualKeyModifiers.Control : Windows.System.VirtualKeyModifiers.None }; shortcut.Invoked += (_, e) => { e.Handled = true; action(); }; root.KeyboardAccelerators.Add(shortcut); }
    private void UpdateDragRegions()
    {
        if (!AppWindowTitleBar.IsCustomizationSupported() || root.XamlRoot is null || fullscreen) return;
        var scale = root.XamlRoot.RasterizationScale;
        var areas = new List<Windows.Foundation.Rect> { new(0, 0, Math.Max(0, root.ActualWidth - AppWindow.TitleBar.RightInset / scale), 64) };
        foreach (var control in captionControls.Where(x => x.ActualWidth > 0 && x.ActualHeight > 0))
        {
            var point = control.TransformToVisual(root).TransformPoint(new()); var hit = new Windows.Foundation.Rect(point.X - 1, point.Y - 1, control.ActualWidth + 2, control.ActualHeight + 2);
            var remaining = new List<Windows.Foundation.Rect>();
            foreach (var area in areas)
            {
                var left = Math.Max(area.Left, hit.Left); var top = Math.Max(area.Top, hit.Top); var right = Math.Min(area.Right, hit.Right); var bottom = Math.Min(area.Bottom, hit.Bottom);
                if (right <= left || bottom <= top) { remaining.Add(area); continue; }
                if (top > area.Top) remaining.Add(new(area.Left, area.Top, area.Width, top - area.Top));
                if (bottom < area.Bottom) remaining.Add(new(area.Left, bottom, area.Width, area.Bottom - bottom));
                if (left > area.Left) remaining.Add(new(area.Left, top, left - area.Left, bottom - top));
                if (right < area.Right) remaining.Add(new(right, top, area.Right - right, bottom - top));
            }
            areas = remaining;
        }
        AppWindow.TitleBar.SetDragRectangles(areas.Select(x => new RectInt32((int)Math.Ceiling(x.X * scale), (int)Math.Ceiling(x.Y * scale), (int)Math.Floor(x.Width * scale), (int)Math.Floor(x.Height * scale))).Where(x => x.Width > 0 && x.Height > 0).ToArray());
    }
    internal void Dispatch(Action action) => DispatcherQueue.TryEnqueue(() => action());
    internal void Toast(string message) { notice.Text = message.Length > 100 ? message[..100] : message; ToolTipService.SetToolTip(notice, message); }
    [System.Runtime.InteropServices.DllImport("user32.dll")] private static extern uint GetDpiForWindow(nint window);
}
