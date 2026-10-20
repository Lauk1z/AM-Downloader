using System.Collections.ObjectModel;
using System.Text;
using System.Text.Json;
using AMDownloader.Core;
using AMDownloader.WinUI.Views;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Windows.Foundation;
using Windows.ApplicationModel.DataTransfer;
using Microsoft.UI.Xaml.Media;

namespace AMDownloader.WinUI;

public sealed partial class MainWindow
{
    private List<LyricLine> lyricLines = [];
    private readonly List<Button> lyricButtons = [];
    private readonly List<LyricLineView> lyricViews = [];
    private ScrollViewer? lyricScroll;
    private int activeLyric = -1;
    private DateTime manualLyricsUntil;
    private void TogglePanel(string panel)
    {
        openPanel = body.IsPaneOpen && openPanel == panel ? "" : panel;
        RefreshPanel(); body.IsPaneOpen = openPanel.Length > 0;
    }
    private void RefreshPanel()
    {
        if (openPanel.Length == 0) return;
        var panel = new Grid { Padding = new(16, 12, 12, 18), RowSpacing = 14 }; panel.RowDefinitions.Add(new() { Height = GridLength.Auto }); panel.RowDefinitions.Add(new() { Height = new(1, GridUnitType.Star) });
        var header = new Grid(); header.Children.Add(Ui.Text(openPanel == "lyrics" ? "歌词" : "正在播放", 19, true)); var close = Ui.Icon("\uE711", "收起侧栏", () => { openPanel = ""; body.IsPaneOpen = false; }, 14); close.HorizontalAlignment = HorizontalAlignment.Right; header.Children.Add(close); panel.Children.Add(header);
        var content = openPanel == "lyrics" ? BuildLyrics() : BuildPlayingQueue(); Grid.SetRow((FrameworkElement)content, 1); panel.Children.Add(content); body.Pane = panel;
    }
    private async Task LoadLyricsAsync(Track track)
    {
        var path = track.Path; lyricLines = [];
        if (track.Container.Length == 0)
        {
            var source = Path.ChangeExtension(track.Path, ".lrc");
            if (File.Exists(source))
            {
                var raw = await File.ReadAllBytesAsync(source); string text;
                try { text = new UTF8Encoding(false, true).GetString(raw); }
                catch (DecoderFallbackException) { Encoding.RegisterProvider(CodePagesEncodingProvider.Instance); text = Encoding.GetEncoding("gb18030").GetString(raw); }
                if (raw.Length > 1 && raw[0] == 255 && raw[1] == 254) text = Encoding.Unicode.GetString(raw);
                if (Audio.Current?.Path != path) return;
                lyricLines = Lyrics.Parse(text.TrimStart('\ufeff'));
            }
        }
        activeLyric = -1; if (openPanel == "lyrics") RefreshPanel();
    }
    private UIElement BuildLyrics()
    {
        foreach (var view in lyricViews) view.Deactivate();
        lyricButtons.Clear(); lyricViews.Clear(); activeLyric = -1;
        var stack = Ui.Stack(20); stack.Padding = new(0, 90, 0, 160);
        foreach (var line in lyricLines)
        {
            var text = new LyricLineView(line.Content);
            var button = new Button { Content = text, HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Stretch, Padding = new(8, 7, 8, 7), Background = Ui.Brush(0, 0, 0, 0), BorderThickness = new(0) };
            Microsoft.UI.Xaml.Automation.AutomationProperties.SetName(button, line.Content);
            button.Click += async (_, _) => { if (line.Time is long time) { manualLyricsUntil = DateTime.MinValue; await SeekTrackAsync(time); UpdateLyrics(true); } };
            stack.Children.Add(button); lyricButtons.Add(button); lyricViews.Add(text);
        }
        if (lyricLines.Count == 0) stack.Children.Add(Ui.Text("暂无歌词\n将同名 LRC 文件放在音频旁即可显示。", 18, true, Ui.Muted));
        lyricScroll = Ui.Scroll(stack);
        lyricScroll.AddHandler(UIElement.PointerWheelChangedEvent, new Microsoft.UI.Xaml.Input.PointerEventHandler((_, _) => manualLyricsUntil = DateTime.UtcNow.AddSeconds(4)), true);
        lyricScroll.DirectManipulationStarted += (_, _) => manualLyricsUntil = DateTime.UtcNow.AddSeconds(8);
        lyricScroll.Loaded += (_, _) => UpdateLyrics(true);
        return new FadingLyricsViewport(lyricScroll);
    }
    private void UpdateLyrics(bool force = false)
    {
        if (openPanel != "lyrics" || lyricScroll is null || lyricButtons.Count != lyricLines.Count) return;
        var index = Lyrics.Active(lyricLines, Audio.Position);
        var changed = index != activeLyric;
        if (changed)
        {
            if (activeLyric >= 0 && activeLyric < lyricViews.Count) lyricViews[activeLyric].Deactivate();
            activeLyric = index;
            if (index >= 0)
            {
                var end = index + 1 < lyricLines.Count ? lyricLines[index + 1].Time ?? Audio.Duration : Audio.Duration;
                lyricViews[index].Activate(Lyrics.Timing(lyricLines[index], end), end);
            }
        }
        if (index >= 0) lyricViews[index].SetClock(Audio.Position, Audio.State == "playing", changed || force);
        if ((changed || force) && index >= 0 && DateTime.UtcNow >= manualLyricsUntil && lyricScroll.ViewportHeight > 0)
        {
            var button = lyricButtons[index]; var point = button.TransformToVisual((UIElement)lyricScroll.Content).TransformPoint(new Point());
            lyricScroll.ChangeView(null, Math.Max(0, point.Y - lyricScroll.ViewportHeight * .42 + button.ActualHeight / 2), null, false);
        }
    }
    private UIElement BuildPlayingQueue()
    {
        var panel = new Grid { RowSpacing = 12 }; panel.RowDefinitions.Add(new() { Height = GridLength.Auto }); panel.RowDefinitions.Add(new() { Height = new(1, GridUnitType.Star) });
        var summary = Ui.Stack(7); summary.Children.Add(Ui.Text(shuffled ? "伪随机播放 · 本轮歌曲不重复" : "顺序播放 · 拖动调整顺序", 12, color: Ui.Muted));
        summary.Children.Add(Ui.Button("清空队列", () => _ = Guard(async () => { CancelGap(); queue.Clear(); shuffle.Reset(); playIndex = -1; await Audio.LoadAsync(null, false); Store.Set("last_track", ""); SaveQueue(); RefreshPanel(); })));
        panel.Children.Add(summary);
        var pending = shuffled ? shuffle.Upcoming(queue.Select(x => x.Path), Audio.Current?.Path ?? "").Where(x => x != Audio.Current?.Path).ToList() : [];
        var ordered = shuffled ? queue.Where(x => x.Path != Audio.Current?.Path && !pending.Contains(x.Path)).Concat(queue.Where(x => x.Path == Audio.Current?.Path)).Concat(pending.Select(path => queue.First(x => x.Path == path))).ToList() : queue.ToList();
        var rows = new ObservableCollection<QueueRow>(ordered.Select((x, index) => new QueueRow(x, index, x.Path == Audio.Current?.Path)));
        var list = new ListView { ItemsSource = rows, SelectionMode = ListViewSelectionMode.Extended, CanDragItems = true, CanReorderItems = true, AllowDrop = true };
        list.ItemTemplate = (DataTemplate)Microsoft.UI.Xaml.Markup.XamlReader.Load("""
          <DataTemplate xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"><Grid Padding="3,7" ColumnSpacing="8"><Grid.ColumnDefinitions><ColumnDefinition Width="36"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions><Image Width="36" Height="36" Source="{Binding Track.Cover}" Stretch="UniformToFill"/><StackPanel Grid.Column="1"><TextBlock Text="{Binding Track.Title}" Foreground="{Binding Ink}" TextTrimming="CharacterEllipsis"/><TextBlock Text="{Binding Track.Artist}" Opacity=".5" FontSize="12" TextTrimming="CharacterEllipsis"/></StackPanel></Grid></DataTemplate>
          """);
        void Play(QueueRow row) { shuffle.Reset(); _ = Guard(() => SelectTrackAsync(queue.FindIndex(x => x.Path == row.Track.Path), true)); }
        void Reordered(IEnumerable<QueueRow> values) { CancelGap(); queue = values.Select(x => x.Track).ToList(); playIndex = queue.FindIndex(x => x.Path == Audio.Current?.Path); shuffled = false; shuffle.Reset(); SaveQueue(); UpdatePlayer(); RefreshPanel(); }
        list.DoubleTapped += (_, _) => { if (list.SelectedItem is QueueRow row) Play(row); };
        list.DragItemsStarting += (_, e) => { e.Data.Properties["am-now-queue"] = true; e.Data.SetText("am-tracks:" + JsonSerializer.Serialize(e.Items.Cast<QueueRow>().Select(x => x.Track.Path))); e.Data.RequestedOperation = DataPackageOperation.Move; };
        list.DragItemsCompleted += (_, e) => { if (e.DropResult == DataPackageOperation.Move) Reordered(rows); };
        list.DragOver += (_, e) => e.AcceptedOperation = e.DataView.Properties.ContainsKey("am-now-queue") ? DataPackageOperation.Move : DataPackageOperation.Copy;
        list.Drop += async (_, e) =>
        {
            if (e.DataView.Properties.ContainsKey("am-now-queue")) return;
            e.Handled = true; await Guard(async () =>
            {
                var paths = new List<string>();
                if (e.DataView.Contains(StandardDataFormats.Text)) { var text = await e.DataView.GetTextAsync(); if (text.StartsWith("am-tracks:")) paths = JsonSerializer.Deserialize<List<string>>(text[10..])!; }
                else if (e.DataView.Contains(StandardDataFormats.StorageItems)) paths = (await e.DataView.GetStorageItemsAsync()).Select(x => x.Path).ToList();
                var lookup = tracks.ToDictionary(x => Core.Paths.Key(x.Path)); var values = paths.Select(x => lookup.GetValueOrDefault(Core.Paths.Key(x))).OfType<Track>().ToList();
                if (values.Count == 0) { Toast("请先将这些音频导入资料库，再添加到播放队列。"); return; }
                var destination = rows.Count; var node = e.OriginalSource as DependencyObject;
                while (node is not null && node is not ListViewItem) node = VisualTreeHelper.GetParent(node);
                if (node is ListViewItem item && item.Content is QueueRow row) destination = rows.IndexOf(row) + (e.GetPosition(item).Y > item.ActualHeight / 2 ? 1 : 0);
                queue = ordered.ToList(); playIndex = queue.FindIndex(x => x.Path == Audio.Current?.Path); QueueTracks(values, false, destination);
            });
        };
        list.RightTapped += (_, e) =>
        {
            var node = e.OriginalSource as DependencyObject; while (node is not null && node is not ListViewItem) node = VisualTreeHelper.GetParent(node);
            if (node is not ListViewItem container || container.Content is not QueueRow row) return;
            if (!list.SelectedItems.Contains(row)) list.SelectedItem = row;
            var menu = new MenuFlyout();
            var selected = list.SelectedItems.Cast<QueueRow>().Select(x => rows.IndexOf(x)).Order().ToList();
            menu.Items.Add(Ui.MenuItem("播放", () => Play(row)));
            menu.Items.Add(Ui.MenuItem("上移", () => Reordered(OrderedEntries.Move(rows.ToList(), selected, Math.Max(0, selected[0] - 1)))));
            menu.Items.Add(Ui.MenuItem("下移", () => Reordered(OrderedEntries.Move(rows.ToList(), selected, selected[^1] + 2))));
            menu.Items.Add(Ui.MenuItem("移出队列", () => _ = RemoveQueueAsync(selected.Select(i => rows[i].Track.Path).ToHashSet()))); e.Handled = true; menu.ShowAt(list, e.GetPosition(list));
        };
        list.SelectedIndex = ordered.FindIndex(x => x.Path == Audio.Current?.Path); Grid.SetRow(list, 1); panel.Children.Add(list); return panel;
    }
    private async Task RemoveQueueAsync(HashSet<string> paths) => await Guard(async () =>
    {
        var removedCurrent = paths.Contains(Audio.Current?.Path ?? ""); var resume = Audio.State is "playing" or "starting" || trackGap.Running || Audio.Preparing && Audio.PrepareAutoplay;
        var index = playIndex - queue.Take(Math.Max(0, playIndex)).Count(x => paths.Contains(x.Path)); CancelGap(); queue.RemoveAll(x => paths.Contains(x.Path));
        if (queue.Count == 0) { playIndex = -1; shuffle.Reset(); await Audio.LoadAsync(null, false); Store.Set("last_track", ""); }
        else if (removedCurrent)
        {
            var next = shuffled ? shuffle.Step(queue.Select(x => x.Path), Audio.Current?.Path ?? "", 1) : queue[Math.Clamp(index, 0, queue.Count - 1)].Path;
            await SelectTrackAsync(queue.FindIndex(x => x.Path == next), resume);
        }
        playIndex = queue.FindIndex(x => x.Path == Audio.Current?.Path); SaveQueue(); RefreshPanel();
    });
    private async Task ShowOutputChainAsync() => await Guard(async () =>
    {
        if (outputWindow is not null) { outputWindow.Activate(); return; }
        var panel = Ui.Stack(12);
        var fields = new Dictionary<string, TextBlock>();
        void Field(string title, string value)
        {
            if (!fields.TryGetValue(title, out var text)) { panel.Children.Add(Ui.Text(title, 12, true, Ui.Muted)); text = Ui.Text(value, 15); text.IsTextSelectionEnabled = true; fields.Add(title, text); panel.Children.Add(text); }
            else if (text.Text != value) text.Text = value;
        }
        void Refresh()
        {
        var track = Audio.Current; var config = Audio.Config; var actual = Audio.Negotiated;
        Field("源文件", track is null ? "尚未选择歌曲" : track.FormatName + " · " + track.Codec.ToUpperInvariant() + "\n" + track.Quality);
        var decode = track is null ? "选择歌曲后显示解码路径" : Audio.Preparing ? "正在准备镜像／整轨中的曲目" : track.IsDsd && config.Mode != "shared" ? (config.Dsd == "native" ? "DSD 数据直接输出" : "DSD 数据 → DoP 封装（不转为 PCM 音频）") : "FFmpeg → PCM" + (config.Mode == "shared" ? " → Windows 系统混音" : "（保持源采样率）");
        if (track?.Container.Length > 0) decode = (track.Area.Length > 0 ? "SACD 提取 → " : "CUE 分轨缓存 → ") + decode;
        Field("解码与传输", decode);
        var output = config.Mode == "shared" ? "系统共享混音 → 音频设备\n最终采样率与位深未直接测得，由 Windows 和设备决定。" : "尚未建立输出，播放时确认实际规格。";
        if (actual is { } info && config.Mode != "shared") output = config.Mode.ToUpperInvariant() + " · 驱动已确认\n" + (J.S(info, "format") == "dsd" ? $"DSD{J.I(info, "rate") / 44100}" : (J.S(info, "format") == "dop" ? "DoP 传输帧 · " : "") + $"{J.I(info, "bits")} bit / {J.I(info, "rate") / 1000d:g} kHz");
        Field("输出接口", output); Field("输出设备", actual is { } negotiated ? J.S(negotiated, "device") : config.Mode == "shared" ? "Windows 默认音频设备" : config.DeviceName.Length > 0 ? config.DeviceName : config.Device);
        Field("音频处理", config.Mode == "shared" ? $"软件音量 {Audio.Volume}%；系统可能重采样或混音。" + (track?.IsDsd == true ? "DSD 已解码为 PCM。" : "") : "软件音量旁路；未添加均衡或混音。");
        Field("当前状态", Audio.Error.Length > 0 ? Audio.Error : Audio.Preparing ? "正在准备" : Audio.State);
        }
        Refresh(); Audio.Changed += Refresh;
        try { outputWindow = new ToolWindow(this, "音频输出链路", panel, 560, 650, settings: () => Navigate("settings")); outputWindow.Activate(); await outputWindow.Completion; }
        finally { Audio.Changed -= Refresh; outputWindow = null; }
    });
}
public sealed record QueueRow(Track Track, int OriginalIndex, bool Current)
{ public Brush Ink => Current ? Ui.Accent : Ui.Brush(255, 238, 238, 242); }
