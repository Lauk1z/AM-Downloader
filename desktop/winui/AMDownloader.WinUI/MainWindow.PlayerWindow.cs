using System.Runtime.InteropServices;
using AMDownloader.Core;
using AMDownloader.WinUI.Views;
using Microsoft.UI;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.Graphics;
using Windows.Storage;
using Windows.System;

namespace AMDownloader.WinUI;

public sealed partial class MainWindow
{
    private sealed partial class PlayerWindow : Window
    {
        private const int MiniWidth = 356, MiniHeight = 158, ExpandedHeight = 638;
        private readonly MainWindow owner;
        internal readonly Grid Surface = new() { Background = Ui.Brush(255, 93, 90, 93), RequestedTheme = ElementTheme.Dark };
        internal bool IsFullscreen { get; private set; }
        internal bool IsClosed { get; private set; }
        internal string Panel { get; private set; } = "";
        internal Slider SeekSlider = null!, VolumeSlider = null!;
        internal Border CoverFrame = null!;
        internal TextBlock SongTitle = null!, Artist = null!;
        internal ContentControl PanelHost = null!;
        internal Grid Footer = null!;
        internal Image Backdrop = null!;
        private Image cover = null!;
        private TextBlock quality = null!, elapsed = null!, remaining = null!;
        private FrameworkElement qualitySymbol = null!;
        private Button play = null!, lyrics = null!, queueButton = null!;
        private StackPanel captions = null!, album = null!;
        private Grid viewLayout = null!;
        private Flyout? volumeFlyout;
        private readonly DispatcherTimer chromeTimer = new() { Interval = TimeSpan.FromMilliseconds(1200) };
        private RectInt32 miniBounds;
        private bool updating, seeking, history, fullLyrics = true;
        private string coverPath = "\0", backdropPath = "", queueTrack = "";
        private ImageSource? coverSource;
        private BitmapImage? backdropSource;
        private int artworkSerial;
        private readonly SolidColorBrush ink = Ui.Brush(255, 235, 234, 237), secondary = Ui.Brush(255, 198, 196, 201);

        internal PlayerWindow(MainWindow owner)
        {
            this.owner = owner; Title = "AM Dowloader · 播放"; Content = Surface;
            hwnd = WinRT.Interop.WindowNative.GetWindowHandle(this); nativeProcedure = NativeMessage; SetWindowSubclass(hwnd, nativeProcedure, 73, 0);
            AppWindow.SetIcon(Path.Combine(AppContext.BaseDirectory, "Assets/app.ico"));
            ConfigureMini();
            var origin = owner.AppWindow.Position; var originalSize = owner.AppWindow.Size;
            AppWindow.Move(new(origin.X + Math.Max(0, originalSize.Width - (int)(MiniWidth * Scale)), origin.Y + (int)(32 * Scale)));
            ResizeMini(); BuildView();
            Surface.KeyboardAcceleratorPlacementMode = KeyboardAcceleratorPlacementMode.Hidden;
            Shortcut(VirtualKey.F11, false, () => ShowMode(!IsFullscreen));
            Shortcut(VirtualKey.M, true, () => { if (IsFullscreen) ShowMode(false); else Close(); });
            Shortcut(VirtualKey.Escape, false, () => { if (IsFullscreen) ShowMode(false); else Close(); });
            Shortcut(VirtualKey.Space, false, () => _ = owner.TogglePlayAsync());
            Shortcut(VirtualKey.Left, true, () => _ = owner.SkipAsync(-1)); Shortcut(VirtualKey.Right, true, () => _ = owner.SkipAsync(1));
            Surface.PointerEntered += (_, _) => { chromeTimer.Stop(); captions.Visibility = Visibility.Visible; };
            Surface.PointerExited += (_, e) => { var p = e.GetCurrentPoint(Surface).Position; if (!IsFullscreen && (p.X < 0 || p.Y < 0 || p.X >= Surface.ActualWidth || p.Y >= Surface.ActualHeight)) chromeTimer.Start(); };
            Surface.GotFocus += (_, _) => { chromeTimer.Stop(); captions.Visibility = Visibility.Visible; };
            chromeTimer.Tick += (_, _) => { chromeTimer.Stop(); if (!IsFullscreen) captions.Visibility = Visibility.Collapsed; };
            Surface.AddHandler(UIElement.PointerPressedEvent, new PointerEventHandler((_, e) => BeginWindowDrag(e)), true);
            Surface.AddHandler(UIElement.PointerMovedEvent, new PointerEventHandler((_, e) => MoveWindowDrag(e)), true);
            Surface.AddHandler(UIElement.PointerReleasedEvent, new PointerEventHandler((_, e) => EndWindowDrag(e)), true);
            Surface.PointerCanceled += (_, e) => EndWindowDrag(e); Surface.PointerCaptureLost += (_, _) => dragPointer = null;
            Surface.SizeChanged += (_, _) => ResizeFullscreen();
            Activated += (_, _) => { if (!IsClosed) ApplyChrome(); };
            AppWindow.Changed += (_, e) => { if (e.DidPresenterChange && !IsClosed) ApplyChrome(); };
            Closed += (_, _) => { IsClosed = true; dragPointer = null; Surface.ReleasePointerCaptures(); ++artworkSerial; ++panelSerial; StopMotion(); RemoveWindowSubclass(hwnd, nativeProcedure, 73); chromeTimer.Stop(); volumeFlyout?.Hide(); DeactivateLyrics(); };
            UpdatePlayer();
        }
        private double Scale => Surface.XamlRoot?.RasterizationScale ?? GetDpiForWindow(WinRT.Interop.WindowNative.GetWindowHandle(this)) / 96d;
        private void ConfigureMini()
        {
            var presenter = OverlappedPresenter.Create(); presenter.SetBorderAndTitleBar(false, false);
            presenter.IsResizable = false; presenter.IsMaximizable = false; presenter.IsMinimizable = true; presenter.IsAlwaysOnTop = true;
            AppWindow.SetPresenter(presenter);
            ApplyChrome();
        }
        internal void ShowMode(bool fullscreen)
        {
            if (IsClosed) return;
            volumeFlyout?.Hide();
            if (AppWindow.Presenter is OverlappedPresenter { State: OverlappedPresenterState.Minimized } minimizedPresenter) minimizedPresenter.Restore();
            if (fullscreen != IsFullscreen)
            {
                var current = CurrentRect; ++panelSerial; StopMotion();
                if (fullscreen) miniBounds = MiniTargetBounds();
                IsFullscreen = fullscreen;
                var target = fullscreen ? DisplayArea.GetFromWindowId(AppWindow.Id, DisplayAreaFallback.Nearest).OuterBounds : miniBounds;
                if (!fullscreen) { ConfigureMini(); AppWindow.MoveAndResize(current); }
                resizingMode = true; frozenLyricsWidth = target.Width / Scale * .41;
                if (fullscreen) lyricFont = Math.Clamp(target.Width / Scale * .021, 28, 60);
                BuildView(); UpdatePlayer(); Fade(viewLayout, true, 300);
                AnimateBounds(target, 360, () =>
                {
                    if (fullscreen) AppWindow.SetPresenter(AppWindowPresenterKind.FullScreen);
                    ApplyChrome(); resizingMode = false; PanelHost.Width = double.NaN; PanelHost.HorizontalAlignment = HorizontalAlignment.Stretch; ResizeFullscreen();
                });
            }
            AppWindow.Show(); if (AppWindow.Presenter is OverlappedPresenter mini && mini.State == OverlappedPresenterState.Minimized) mini.Restore();
            Activate();
        }
        internal new void Close() { if (!IsClosed) base.Close(); }
        private void Shortcut(VirtualKey key, bool ctrl, Action action)
        { var shortcut = new KeyboardAccelerator { Key = key, Modifiers = ctrl ? VirtualKeyModifiers.Control : VirtualKeyModifiers.None }; shortcut.Invoked += (_, e) => { e.Handled = true; action(); }; Surface.KeyboardAccelerators.Add(shortcut); }
        private void BuildView()
        {
            DeactivateLyrics(); Surface.Children.Clear();
            Backdrop = new Image { Source = backdropSource, Stretch = Stretch.UniformToFill, IsHitTestVisible = false }; Surface.Children.Add(Backdrop);
            Surface.Children.Add(new Border { IsHitTestVisible = false, Background = new AcrylicBrush { TintColor = ColorHelper.FromArgb(255, 96, 92, 96), TintOpacity = .35, TintLuminosityOpacity = .62, FallbackColor = ColorHelper.FromArgb(190, 96, 92, 96) } });
            PanelHost = new ContentControl { HorizontalContentAlignment = HorizontalAlignment.Stretch, VerticalContentAlignment = VerticalAlignment.Stretch, Name = "PlayerPanel" };
            CoverFrame = Ui.Cover("", IsFullscreen ? 400 : 60, IsFullscreen ? 9 : 4); cover = ((Grid)CoverFrame.Child).Children.OfType<Image>().Single(); cover.Source = coverSource;
            SongTitle = Ui.Text("", IsFullscreen ? 17 : 14, color: ink); SongTitle.TextAlignment = TextAlignment.Center; SongTitle.TextWrapping = TextWrapping.NoWrap; SongTitle.TextTrimming = TextTrimming.CharacterEllipsis;
            Artist = Ui.Text("", IsFullscreen ? 16 : 13, color: secondary); Artist.TextAlignment = TextAlignment.Center; Artist.TextWrapping = TextWrapping.NoWrap; Artist.TextTrimming = TextTrimming.CharacterEllipsis;
            quality = Ui.Text("", 12, true, secondary); qualitySymbol = (FrameworkElement)Icons.Create("lossless", 15, ink: secondary);
            var format = Ui.Stack(4, Orientation.Horizontal); format.HorizontalAlignment = HorizontalAlignment.Center; format.Children.Add(qualitySymbol); format.Children.Add(quality);
            var info = Ui.Stack(IsFullscreen ? 12 : 4); info.HorizontalAlignment = HorizontalAlignment.Stretch; info.Children.Add(SongTitle); info.Children.Add(Artist); info.Children.Add(format);
            Footer = BuildFooter();
            if (!IsFullscreen)
            {
                var layout = viewLayout = new Grid { Padding = new(18, 16, 18, 12), RowSpacing = 4 };
                layout.RowDefinitions.Add(new() { Height = new(64) }); layout.RowDefinitions.Add(new() { Height = new(1, GridUnitType.Star) }); layout.RowDefinitions.Add(new() { Height = new(56) });
                var header = new Grid(); CoverFrame.HorizontalAlignment = HorizontalAlignment.Left; header.Children.Add(CoverFrame);
                info.Margin = new(60, 0, 60, 0); SongTitle.MaxWidth = 132; SongTitle.HorizontalAlignment = HorizontalAlignment.Center; info.VerticalAlignment = VerticalAlignment.Center; header.Children.Add(info); layout.Children.Add(header);
                Grid.SetRow(PanelHost, 1); layout.Children.Add(PanelHost); Grid.SetRow(Footer, 2); layout.Children.Add(Footer); Surface.Children.Add(layout);
            }
            else
            {
                var fullBody = viewLayout = new Grid { Padding = new(0, 36, 0, 36) }; fullBody.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) }); fullBody.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) });
                album = Ui.Stack(16); album.VerticalAlignment = VerticalAlignment.Center; album.HorizontalAlignment = HorizontalAlignment.Center; album.Children.Add(CoverFrame); album.Children.Add(info); album.Children.Add(Footer);
                fullBody.Children.Add(album); Grid.SetColumn(PanelHost, 1); fullBody.Children.Add(PanelHost); Surface.Children.Add(fullBody);
            }
            captions = Ui.Stack(0, Orientation.Horizontal); captions.HorizontalAlignment = HorizontalAlignment.Right; captions.VerticalAlignment = VerticalAlignment.Top; captions.Margin = new(0, 2, 2, 0);
            if (!IsFullscreen) captions.Children.Add(Caption("minimize", "最小化播放窗口", () => (AppWindow.Presenter as OverlappedPresenter)?.Minimize()));
            captions.Children.Add(Caption(IsFullscreen ? "shrink-player" : "expand-player", IsFullscreen ? "退出全屏" : "全屏播放", () => ShowMode(!IsFullscreen)));
            captions.Children.Add(Caption("close", "关闭播放窗口，返回主界面", Close)); Surface.Children.Add(captions);
            ResizeFullscreen(); RefreshPanel();
        }
        private Button Caption(string icon, string label, Action action)
        { var button = Control(icon, label, action, 13); button.Width = 36; button.Height = 25; button.Padding = new(7); return button; }
        private Button Control(string icon, string label, Action action, double size = 20)
        {
            var button = Ui.Icon(icon, label, action, size); button.Foreground = ink;
            button.Resources["ButtonBackgroundPointerOver"] = Ui.Brush(24, 255, 255, 255); button.Resources["ButtonBackgroundPressed"] = Ui.Brush(40, 255, 255, 255);
            return button;
        }
        private Grid BuildFooter()
        {
            var footer = new Grid { RowSpacing = 2, Margin = IsFullscreen ? new(0) : new(8, 0, 8, 0) }; footer.RowDefinitions.Add(new() { Height = new(20) }); footer.RowDefinitions.Add(new() { Height = new(34) });
            var timeline = new Grid { ColumnSpacing = 8 }; timeline.ColumnDefinitions.Add(new() { Width = new(38) }); timeline.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) }); timeline.ColumnDefinitions.Add(new() { Width = new(42) });
            elapsed = Ui.Text("", 12, color: secondary); remaining = Ui.Text("", 12, color: secondary); remaining.TextAlignment = TextAlignment.Right;
            SeekSlider = new Slider { Minimum = 0, Maximum = 1, MinHeight = 0, Height = 20, MinWidth = 0, IsThumbToolTipEnabled = false, Background = Ui.Brush(45, 235, 232, 237), Foreground = ink };
            AutomationProperties.SetName(SeekSlider, "播放进度");
            SeekSlider.Template = (ControlTemplate)Microsoft.UI.Xaml.Markup.XamlReader.Load("""
              <ControlTemplate xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" TargetType="Slider">
                <Grid x:Name="SliderContainer" Background="Transparent"><Grid x:Name="HorizontalTemplate">
                  <Grid.ColumnDefinitions><ColumnDefinition Width="Auto"/><ColumnDefinition Width="Auto"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
                  <Rectangle x:Name="HorizontalTrackRect" Grid.ColumnSpan="3" Height="3" RadiusX="1.5" RadiusY="1.5" Fill="{TemplateBinding Background}" VerticalAlignment="Center"/>
                  <Rectangle x:Name="HorizontalDecreaseRect" Height="3" RadiusX="1.5" RadiusY="1.5" Fill="{TemplateBinding Foreground}" VerticalAlignment="Center"/>
                  <Thumb x:Name="HorizontalThumb" Grid.Column="1" Width="1" Height="20" Opacity="0"/>
                </Grid></Grid>
              </ControlTemplate>
              """.Replace("Height=\"3\"", IsFullscreen ? "Height=\"6\"" : "Height=\"3\"").Replace("RadiusX=\"1.5\" RadiusY=\"1.5\"", IsFullscreen ? "RadiusX=\"3\" RadiusY=\"3\"" : "RadiusX=\"1.5\" RadiusY=\"1.5\""));
            void CommitSeek() { if (seeking) { seeking = false; _ = owner.SeekTrackAsync((long)SeekSlider.Value); } }
            SeekSlider.AddHandler(UIElement.PointerPressedEvent, new PointerEventHandler((_, _) => seeking = true), true);
            SeekSlider.AddHandler(UIElement.PointerReleasedEvent, new PointerEventHandler((_, _) => CommitSeek()), true); SeekSlider.PointerCaptureLost += (_, _) => CommitSeek();
            SeekSlider.ValueChanged += (_, _) => { if (!updating && !seeking && owner.Audio.Current is not null) _ = owner.SeekTrackAsync((long)SeekSlider.Value); };
            timeline.Children.Add(elapsed); Grid.SetColumn(SeekSlider, 1); timeline.Children.Add(SeekSlider); Grid.SetColumn(remaining, 2); timeline.Children.Add(remaining); footer.Children.Add(timeline);
            var controls = new Grid(); foreach (var width in new[] { new GridLength(1, GridUnitType.Star), GridLength.Auto, new(1, GridUnitType.Star) }) controls.ColumnDefinitions.Add(new() { Width = width });
            var left = Ui.Stack(10, Orientation.Horizontal); var volume = Control("volume", "音量", () => { }, 19);
            VolumeSlider = new Slider { Minimum = 0, Maximum = 100, Width = 160, MinHeight = 28, Foreground = ink };
            AutomationProperties.SetName(VolumeSlider, "播放窗口音量");
            foreach (var key in new[] { "SliderThumbBackground", "SliderThumbBackgroundPointerOver", "SliderThumbBackgroundPressed" }) VolumeSlider.Resources[key] = ink;
            VolumeSlider.ValueChanged += (_, _) => { if (!updating && owner.Audio.Config.Mode == "shared") _ = owner.Guard(async () => { await owner.Audio.SetVolumeAsync((int)VolumeSlider.Value); owner.Store.Set("volume", (int)VolumeSlider.Value); }); };
            volumeFlyout = new Flyout { Content = VolumeSlider, Placement = FlyoutPlacementMode.Top }; volume.Flyout = volumeFlyout; left.Children.Add(volume);
            var more = Control("more", "播放选项", () => { }, 15); more.Click += (_, _) => { FlyoutBase.SetAttachedFlyout(more, MoreMenu()); FlyoutBase.ShowAttachedFlyout(more); }; left.Children.Add(more); controls.Children.Add(left);
            var transport = Ui.Stack(3, Orientation.Horizontal); play = Control("play", "播放 / 暂停", () => _ = owner.TogglePlayAsync(), 25);
            transport.Children.Add(Control("previous", "上一首", () => _ = owner.SkipAsync(-1), 24)); transport.Children.Add(play); transport.Children.Add(Control("next", "下一首", () => _ = owner.SkipAsync(1), 24)); Grid.SetColumn(transport, 1); controls.Children.Add(transport);
            var right = Ui.Stack(10, Orientation.Horizontal); right.HorizontalAlignment = HorizontalAlignment.Right;
            lyrics = Control("lyrics", "歌词", () => TogglePanel("lyrics"), 20); queueButton = Control("queue", "待播清单与历史记录", () => TogglePanel("queue"), 20); right.Children.Add(lyrics); if (!IsFullscreen) right.Children.Add(queueButton);
            Grid.SetColumn(right, 2); controls.Children.Add(right); Grid.SetRow(controls, 1); footer.Children.Add(controls); return footer;
        }
        private MenuFlyout MoreMenu()
        {
            var menu = new MenuFlyout();
            var shuffle = new ToggleMenuFlyoutItem { Text = "随机播放 · 每轮不重复", IsChecked = owner.shuffled };
            shuffle.Click += (_, _) => { owner.CancelGap(); owner.shuffled = !owner.shuffled; owner.shuffle.Reset(); owner.UpdatePlayer(); owner.RefreshPanel(); }; menu.Items.Add(shuffle);
            var repeat = new MenuFlyoutSubItem { Text = "循环播放" };
            foreach (var (name, one, all) in new[] { ("关闭", false, false), ("单曲循环", true, false), ("列表循环", false, true) })
            { var item = new ToggleMenuFlyoutItem { Text = name, IsChecked = owner.repeatOne == one && owner.repeat == all }; item.Click += (_, _) => { owner.repeatOne = one; owner.repeat = all; owner.UpdatePlayer(); }; repeat.Items.Add(item); }
            menu.Items.Add(repeat); menu.Items.Add(new MenuFlyoutSeparator()); menu.Items.Add(Ui.MenuItem("返回主界面", Close)); return menu;
        }
        internal void TogglePanel(string panel)
        {
            volumeFlyout?.Hide(); ++panelSerial;
            if (IsFullscreen)
            {
                if (panel != "lyrics") return; fullLyrics = !fullLyrics;
                if (fullLyrics) { RefreshPanel(); Fade(PanelHost, true); }
                else Fade(PanelHost, false, completed: RefreshPanel);
            }
            else
            {
                resizingMode = false;
                Panel = Panel == panel ? "" : panel;
                if (Panel.Length > 0) { RefreshPanel(); Fade(PanelHost, true); AnimateBounds(MiniTargetBounds(), 260); }
                else { Fade(PanelHost, false); AnimateBounds(MiniTargetBounds(), 260, RefreshPanel); }
            }
            UpdatePlayer();
        }
        private void RefreshPanel()
        {
            DeactivateLyrics();
            PanelHost.Visibility = (IsFullscreen ? fullLyrics : Panel.Length > 0) ? Visibility.Visible : Visibility.Collapsed;
            PanelHost.Content = (IsFullscreen && fullLyrics) || (!IsFullscreen && Panel == "lyrics") ? BuildLyrics() : !IsFullscreen && Panel == "queue" ? BuildQueue() : null;
        }
        private void ResizeMini() => AppWindow.MoveAndResize(MiniTargetBounds());
        private RectInt32 MiniTargetBounds()
        {
            var area = DisplayArea.GetFromWindowId(AppWindow.Id, DisplayAreaFallback.Nearest).WorkArea;
            var size = new SizeInt32((int)Math.Min(MiniWidth * Scale, area.Width), (int)Math.Min((Panel.Length > 0 ? ExpandedHeight : MiniHeight) * Scale, area.Height));
            var position = AppWindow.Position; return new(Math.Clamp(position.X, area.X, Math.Max(area.X, area.X + area.Width - size.Width)), Math.Clamp(position.Y, area.Y, Math.Max(area.Y, area.Y + area.Height - size.Height)), size.Width, size.Height);
        }
        private void ResizeFullscreen()
        {
            if (!IsFullscreen || Surface.ActualWidth <= 0 || album is null) return;
            var width = Surface.ActualWidth; var height = Surface.ActualHeight;
            var coverSize = Math.Clamp(Math.Min(width * .30, height - 300), 96, 900);
            CoverFrame.Width = CoverFrame.Height = cover.Width = cover.Height = coverSize;
            if (CoverFrame.Child is Grid picture) picture.Width = picture.Height = coverSize;
            album.Width = Math.Max(270, coverSize); album.Margin = new(width * .06, 8, 0, 8);
            Footer.Width = Math.Max(270, coverSize * .82); Footer.HorizontalAlignment = HorizontalAlignment.Center;
            PanelHost.Margin = new(width * .02, 32, width * .07, 24);
            if (resizingMode) { PanelHost.Width = frozenLyricsWidth; PanelHost.HorizontalAlignment = HorizontalAlignment.Left; return; }
            var font = Math.Clamp(width * .021, 28, 60);
            if (Math.Abs(lyricFont - font) > .5) { lyricFont = font; if (fullLyrics) RefreshLyrics(); }
        }
        internal void UpdatePlayer()
        {
            if (IsClosed || play is null) return;
            var track = owner.Audio.Current; SongTitle.Text = track?.Title ?? "尚未播放"; Artist.Text = track is null ? "选择一首音乐开始播放" : track.Artist + " — " + track.Album;
            quality.Text = track?.Quality.Split('·')[0].Trim() ?? ""; qualitySymbol.Visibility = track?.IsLossless == true ? Visibility.Visible : Visibility.Collapsed; ToolTipService.SetToolTip(quality, track?.Quality ?? "");
            Ui.SetGlyph(play, owner.Audio.State is "playing" or "starting" || owner.trackGap.Running || owner.Audio.Preparing && owner.Audio.PrepareAutoplay ? "pause" : "play", 25);
            play.IsEnabled = track is not null || owner.tracks.Count > 0;
            lyrics.Background = (IsFullscreen ? fullLyrics : Panel == "lyrics") ? Ui.Brush(28, 255, 255, 255) : Ui.Brush(0, 0, 0, 0); queueButton.Background = Panel == "queue" ? Ui.Brush(28, 255, 255, 255) : Ui.Brush(0, 0, 0, 0);
            updating = true;
            try { SeekSlider.Maximum = Math.Max(1, owner.Audio.Duration); SeekSlider.IsEnabled = track is not null && !owner.Audio.Preparing; if (!seeking) SeekSlider.Value = owner.Audio.Position; VolumeSlider.Value = owner.Audio.Volume; VolumeSlider.IsEnabled = owner.Audio.Config.Mode == "shared"; }
            finally { updating = false; }
            ToolTipService.SetToolTip(VolumeSlider, VolumeSlider.IsEnabled ? "音量" : "独占直通输出，请调节 DAC 音量");
            elapsed.Text = Text.Duration(owner.Audio.Position / 1000d); remaining.Text = "−" + Text.Duration(Math.Max(0, owner.Audio.Duration - owner.Audio.Position) / 1000d);
            var path = track?.Cover ?? "";
            if (coverPath != path)
            {
                coverPath = path; Ui.SetImage(cover, path); if (cover.Source is BitmapImage bitmap) bitmap.DecodePixelWidth = 1600; coverSource = cover.Source; _ = LoadBackdropAsync(path, ++artworkSerial);
            }
            if (queueTrack != track?.Path) { queueTrack = track?.Path ?? ""; RefreshQueue(); RefreshLyrics(); }
            UpdateLyrics();
        }
        private async Task LoadBackdropAsync(string path, int serial)
        {
            try
            {
                if (path.Length == 0) { backdropSource = null; Backdrop.Source = null; return; }
                if (backdropPath == path && backdropSource is not null) { Backdrop.Source = backdropSource; return; }
                var processed = (await owner.Library.CallAsync("backdrop", new() { ["cover"] = path })).GetString()!;
                using var stream = await (await StorageFile.GetFileFromPathAsync(processed)).OpenReadAsync(); var bitmap = new BitmapImage(); await bitmap.SetSourceAsync(stream);
                if (IsClosed || serial != artworkSerial) return;
                backdropPath = path; backdropSource = bitmap; Backdrop.Source = bitmap; Ui.Animate(Backdrop);
            }
            catch (Exception error) { if (!IsClosed && !owner.quitting) owner.Log("播放背景加载失败：" + error.Message); }
        }
        [DllImport("dwmapi.dll")] private static extern int DwmSetWindowAttribute(nint window, uint attribute, ref int value, int size);
        private static T? FindElement<T>(DependencyObject parent, string name) where T : FrameworkElement
        {
            if (parent is T element && element.Name == name) return element;
            for (var i = 0; i < VisualTreeHelper.GetChildrenCount(parent); i++) if (FindElement<T>(VisualTreeHelper.GetChild(parent, i), name) is { } found) return found;
            return null;
        }
    }
}
