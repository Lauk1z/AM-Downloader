using System.Collections.ObjectModel;
using System.Text.Json;
using AMDownloader.Core;
using AMDownloader.WinUI.Views;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Windows.ApplicationModel.DataTransfer;

namespace AMDownloader.WinUI;

public sealed partial class MainWindow
{
    private sealed partial class PlayerWindow
    {
        private readonly List<Button> lyricButtons = [];
        private readonly List<LyricLineView> lyricViews = [];
        private List<LyricLine> lines = [];
        internal ScrollViewer? LyricScroll;
        internal ListView? QueueList;
        private int activeLyric = -1;
        private DateTime manualLyricsUntil;
        private double lyricFont = 23;
        internal bool ShowingHistory => history;
        private void DeactivateLyrics() { foreach (var view in lyricViews) view.Deactivate(); lyricViews.Clear(); lyricButtons.Clear(); LyricScroll = null; activeLyric = -1; }
        internal void RefreshLyrics()
        {
            if (IsClosed || PanelHost is null || !(IsFullscreen ? fullLyrics : Panel == "lyrics")) return;
            PanelHost.Content = BuildLyrics();
        }
        private UIElement BuildLyrics()
        {
            DeactivateLyrics(); lines = owner.Audio.Current?.Path == owner.lyricTrackPath ? owner.lyricLines : [];
            var size = IsFullscreen ? lyricFont : 23;
            var stack = Ui.Stack(IsFullscreen ? Math.Clamp(size * .65, 18, 38) : 23); stack.Padding = IsFullscreen ? new(0, 90, 0, 180) : new(0, 18, 0, 100);
            foreach (var line in lines)
            {
                var view = new LyricLineView(line.Content, owner.LyricsMode, size);
                var button = new Button { Content = view, HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Stretch, Padding = new(8, 7, 8, 7), Background = Ui.Brush(0, 0, 0, 0), BorderThickness = new(0), CornerRadius = new(6) };
                AutomationProperties.SetName(button, line.Content);
                button.Resources["ButtonBackgroundPointerOver"] = Ui.Brush(14, 255, 255, 255); button.Resources["ButtonBackgroundPressed"] = Ui.Brush(24, 255, 255, 255);
                button.Click += async (_, _) => { if (line.Time is long time) { manualLyricsUntil = DateTime.MinValue; await owner.SeekTrackAsync(time); UpdateLyrics(true); } };
                stack.Children.Add(button); lyricButtons.Add(button); lyricViews.Add(view);
            }
            if (lines.Count == 0) stack.Children.Add(Ui.Text("暂无歌词", 20, true, secondary));
            LyricScroll = Ui.Scroll(stack);
            LyricScroll.VerticalScrollBarVisibility = ScrollBarVisibility.Hidden;
            LyricScroll.AddHandler(UIElement.PointerWheelChangedEvent, new PointerEventHandler((_, _) => manualLyricsUntil = DateTime.UtcNow.AddSeconds(4)), true);
            LyricScroll.DirectManipulationStarted += (_, _) => manualLyricsUntil = DateTime.UtcNow.AddSeconds(8);
            LyricScroll.Loaded += (_, _) => UpdateLyrics(true);
            return new FadingLyricsViewport(LyricScroll);
        }
        private void UpdateLyrics(bool force = false)
        {
            if (LyricScroll is null || lyricButtons.Count != lines.Count || owner.Audio.Current?.Path != owner.lyricTrackPath) return;
            var index = Lyrics.Active(lines, owner.Audio.Position); var changed = index != activeLyric;
            if (changed)
            {
                if (activeLyric >= 0 && activeLyric < lyricViews.Count) lyricViews[activeLyric].Deactivate(); activeLyric = index;
                if (index >= 0) { var end = index + 1 < lines.Count ? lines[index + 1].Time ?? owner.Audio.Duration : owner.Audio.Duration; lyricViews[index].Activate(Lyrics.Timing(lines[index], end), end); }
            }
            if (index >= 0) lyricViews[index].SetClock(owner.Audio.Position, owner.Audio.State == "playing", changed || force);
            if ((changed || force) && !IsAnimating && index >= 0 && DateTime.UtcNow >= manualLyricsUntil && LyricScroll.ViewportHeight > 0)
            {
                var button = lyricButtons[index]; var point = button.TransformToVisual((UIElement)LyricScroll.Content).TransformPoint(new());
                LyricScroll.ChangeView(null, Math.Max(0, point.Y - LyricScroll.ViewportHeight * .42 + button.ActualHeight / 2), null, false);
            }
        }
        internal void RefreshQueue() { if (!IsClosed && !IsFullscreen && Panel == "queue" && PanelHost is not null) PanelHost.Content = BuildQueue(); }
        internal void SelectHistory(bool value) { history = value; RefreshQueue(); }
        private List<Track> PendingTracks() => owner.shuffled
            ? owner.shuffle.Upcoming(owner.queue.Select(x => x.Path), owner.Audio.Current?.Path ?? "").Where(x => x != owner.Audio.Current?.Path).Select(path => owner.queue.First(x => x.Path == path)).ToList()
            : owner.queue.Skip(Math.Max(0, owner.playIndex + 1)).ToList();
        private UIElement BuildQueue()
        {
            var panel = new Grid { RowSpacing = 12, Padding = new(0, 8, 0, 2) };
            panel.RowDefinitions.Add(new() { Height = new(31) }); panel.RowDefinitions.Add(new() { Height = new(24) }); panel.RowDefinitions.Add(new() { Height = new(1, GridUnitType.Star) });
            var tabs = new Grid { Background = Ui.Brush(18, 255, 255, 255), CornerRadius = new(5), Padding = new(2) }; tabs.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) }); tabs.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) });
            foreach (var (label, value) in new[] { ("待播清单", false), ("历史记录", true) })
            {
                var button = Ui.Button(label, () => SelectHistory(value)); button.Padding = new(4, 0, 4, 0); button.MinHeight = 0; button.Height = 27; button.FontSize = 13;
                var highlight = Ui.Brush(24, 255, 255, 255);
                button.Background = history == value ? highlight : Ui.Brush(0, 0, 0, 0); button.Foreground = ink; button.BorderThickness = new(0); button.CornerRadius = new(4); button.HorizontalAlignment = HorizontalAlignment.Stretch;
                button.Resources["ButtonBackgroundPointerOver"] = highlight; button.Resources["ButtonBackgroundPressed"] = Ui.Brush(36, 255, 255, 255);
                AutomationProperties.SetName(button, label); Grid.SetColumn(button, value ? 1 : 0); tabs.Children.Add(button);
            }
            panel.Children.Add(tabs);
            var heading = new Grid(); heading.Children.Add(Ui.Text(history ? "历史记录" : "待播清单", 13, color: secondary));
            var clear = Ui.Button("清除", () =>
            {
                if (history) owner.Store.Set("recently_played", new List<string>());
                else { owner.CancelGap(); owner.queue = owner.shuffled ? owner.queue.Where(x => x.Path == owner.Audio.Current?.Path).ToList() : owner.queue.Take(Math.Max(0, owner.playIndex + 1)).ToList(); owner.playIndex = owner.queue.FindIndex(x => x.Path == owner.Audio.Current?.Path); owner.shuffle.Reset(); owner.SaveQueue(); owner.RefreshPanel(); }
                RefreshQueue();
            });
            clear.FontSize = 13; clear.Padding = new(4, 0, 4, 0); clear.MinHeight = 0; clear.Height = 24; clear.Foreground = Ui.Accent; clear.Background = Ui.Brush(0, 0, 0, 0); clear.BorderThickness = new(0); clear.HorizontalAlignment = HorizontalAlignment.Right; heading.Children.Add(clear); Grid.SetRow(heading, 1); panel.Children.Add(heading);
            var lookup = owner.tracks.Concat(owner.queue).DistinctBy(x => x.Path).ToDictionary(x => x.Path);
            var values = history ? owner.Store.Get("recently_played", new List<string>()).Select(path => lookup.GetValueOrDefault(path)).OfType<Track>().ToList() : PendingTracks();
            clear.IsEnabled = values.Count > 0;
            var rows = new ObservableCollection<Track>(values);
            QueueList = new ListView { ItemsSource = rows, IsItemClickEnabled = true, SelectionMode = ListViewSelectionMode.Single, CanDragItems = !history, CanReorderItems = !history, AllowDrop = !history, Background = Ui.Brush(0, 0, 0, 0) };
            ScrollViewer.SetVerticalScrollBarVisibility(QueueList, ScrollBarVisibility.Hidden);
            ScrollViewer.SetHorizontalScrollBarVisibility(QueueList, ScrollBarVisibility.Disabled);
            QueueList.ItemContainerStyle = new Style { TargetType = typeof(ListViewItem), BasedOn = (Style)Application.Current.Resources["DefaultListViewItemStyle"], Setters = { new Setter(Microsoft.UI.Xaml.Controls.Control.PaddingProperty, new Thickness(0)), new Setter(Microsoft.UI.Xaml.Controls.Control.CornerRadiusProperty, new CornerRadius(6)), new Setter(Microsoft.UI.Xaml.Controls.Control.HorizontalContentAlignmentProperty, HorizontalAlignment.Stretch) } };
            foreach (var key in new[] { "ListViewItemBackgroundPointerOver", "ListViewItemBackgroundSelected", "ListViewItemBackgroundSelectedPointerOver", "ListViewItemBackgroundPressed" }) QueueList.Resources[key] = Ui.Brush(22, 255, 255, 255);
            QueueList.Resources["ListViewItemSelectionIndicatorBrush"] = Ui.Brush(0, 0, 0, 0);
            QueueList.ItemTemplate = (DataTemplate)Microsoft.UI.Xaml.Markup.XamlReader.Load("""
              <DataTemplate xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">
                <Grid Padding="4,6" ColumnSpacing="8" Background="Transparent" BorderThickness="0,0,0,1" BorderBrush="#12FFFFFF">
                  <Grid.ColumnDefinitions><ColumnDefinition Width="42"/><ColumnDefinition Width="*"/><ColumnDefinition Width="40"/></Grid.ColumnDefinitions>
                  <Border CornerRadius="4"><Image Source="{Binding Cover}" Width="42" Height="42" Stretch="UniformToFill"/></Border>
                  <StackPanel Grid.Column="1" Spacing="3" VerticalAlignment="Center"><TextBlock Text="{Binding Title}" Foreground="#EEEDEF" FontSize="13" TextTrimming="CharacterEllipsis"/><TextBlock Foreground="#BFC0C3" FontSize="12" TextTrimming="CharacterEllipsis"><Run Text="{Binding Artist}"/><Run Text=" — "/><Run Text="{Binding Album}"/></TextBlock></StackPanel>
                  <Grid Grid.Column="2"><TextBlock x:Name="Duration" Text="{Binding TimeText}" Foreground="#CFCDD1" FontSize="13" VerticalAlignment="Center" HorizontalAlignment="Right"/><Button x:Name="More" Visibility="Collapsed" Width="32" Height="30" MinWidth="0" MinHeight="0" Padding="6" Background="Transparent" BorderThickness="0" HorizontalAlignment="Right"/></Grid>
                </Grid>
              </DataTemplate>
              """);
            QueueList.ContainerContentChanging += (_, args) =>
            {
                if (args.InRecycleQueue) return;
                args.RegisterUpdateCallback((_, changed) =>
                {
                    if (changed.Item is Track item) AutomationProperties.SetName(changed.ItemContainer, item.Title + " — " + item.Artist);
                    if (changed.ItemContainer.ContentTemplateRoot is not Grid row || row.Tag is true) return; row.Tag = true;
                    var more = FindElement<Button>(row, "More")!; var duration = FindElement<TextBlock>(row, "Duration")!;
                    Ui.SetGlyph(more, "more", 16); more.Foreground = Ui.Accent; AutomationProperties.SetName(more, "歌曲操作");
                    row.PointerEntered += (_, _) => { more.Visibility = Visibility.Visible; duration.Visibility = Visibility.Collapsed; };
                    row.PointerExited += (_, _) => { more.Visibility = Visibility.Collapsed; duration.Visibility = Visibility.Visible; };
                    more.Click += (_, _) => { if (more.DataContext is Track track) { FlyoutBase.SetAttachedFlyout(more, QueueMenu(track)); FlyoutBase.ShowAttachedFlyout(more); } };
                });
            };
            QueueList.ItemClick += (_, args) => PlayQueueTrack((Track)args.ClickedItem);
            QueueList.DragItemsStarting += (_, e) => { e.Data.Properties["am-player-queue"] = true; e.Data.SetText(JsonSerializer.Serialize(e.Items.Cast<Track>().Select(x => x.Path))); e.Data.RequestedOperation = DataPackageOperation.Move; };
            QueueList.DragOver += (_, e) => e.AcceptedOperation = e.DataView.Properties.ContainsKey("am-player-queue") ? DataPackageOperation.Move : DataPackageOperation.None;
            QueueList.DragItemsCompleted += (_, e) =>
            {
                if (e.DropResult != DataPackageOperation.Move || history) return;
                var pending = values.Select(x => x.Path).ToHashSet(); owner.queue = owner.queue.Where(x => !pending.Contains(x.Path) && x.Path != owner.Audio.Current?.Path).Concat(owner.queue.Where(x => x.Path == owner.Audio.Current?.Path)).Concat(rows).ToList(); owner.playIndex = owner.queue.FindIndex(x => x.Path == owner.Audio.Current?.Path);
                owner.CancelGap(); owner.shuffled = false; owner.shuffle.Reset(); owner.SaveQueue(); owner.UpdatePlayer(); owner.RefreshPanel();
            };
            QueueList.RightTapped += (_, e) =>
            {
                var node = e.OriginalSource as DependencyObject; while (node is not null && node is not ListViewItem) node = VisualTreeHelper.GetParent(node);
                if (node is not ListViewItem { Content: Track track }) return; e.Handled = true; QueueMenu(track).ShowAt(QueueList, e.GetPosition(QueueList));
            };
            Grid.SetRow(QueueList, 2); panel.Children.Add(QueueList);
            if (values.Count == 0) { var empty = Ui.Text(history ? "还没有播放记录" : "待播清单为空", 14, color: secondary); empty.HorizontalAlignment = HorizontalAlignment.Center; Grid.SetRow(empty, 2); panel.Children.Add(empty); }
            return panel;
        }
        private void PlayQueueTrack(Track track)
        {
            var index = owner.queue.FindIndex(x => x.Path == track.Path);
            owner.shuffle.Reset(); _ = index >= 0 ? owner.Guard(() => owner.SelectTrackAsync(index, true)) : owner.PlayTracksAsync([track]);
        }
        private MenuFlyout QueueMenu(Track track)
        {
            var menu = new MenuFlyout(); menu.Items.Add(Ui.MenuItem("播放", () => PlayQueueTrack(track))); menu.Items.Add(Ui.MenuItem("下一首播放", () => owner.QueueTracks([track], true)));
            if (history) menu.Items.Add(Ui.MenuItem("最后播放", () => owner.QueueTracks([track], false)));
            else menu.Items.Add(Ui.MenuItem("移出待播清单", () => _ = owner.RemoveQueueAsync([track.Path])));
            return menu;
        }
    }
}
