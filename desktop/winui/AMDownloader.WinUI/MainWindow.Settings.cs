using System.Text.Json;
using AMDownloader.Core;
using AMDownloader.WinUI.Services;
using AMDownloader.WinUI.Views;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Windows.Storage.Pickers;

namespace AMDownloader.WinUI;

public sealed partial class MainWindow
{
    private UIElement SettingsPage()
    {
        var stack = Ui.Stack(20); stack.Children.Add(Ui.Text("下载工具    内置 AppleMusicDecrypt · 已集成运行环境", 15, color: Ui.Muted));
        void Row(string title, FrameworkElement control)
        {
            var row = new Grid { ColumnSpacing = 16 }; row.ColumnDefinitions.Add(new() { Width = new(100) }); row.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) }); row.Children.Add(Ui.Text(title, 14)); Grid.SetColumn(control, 1); row.Children.Add(control); stack.Children.Add(row);
        }
        var folder = new TextBox { Text = Store.Get("library", Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyMusic), "AM Dowloader")).Replace('/', '\\') };
        var browse = new Grid { ColumnSpacing = 8 }; browse.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) }); browse.ColumnDefinitions.Add(new() { Width = GridLength.Auto }); browse.Children.Add(folder);
        var choose = Ui.Button("选择文件夹", () => _ = Guard(async () => { var picker = InitPicker(new FolderPicker()); picker.FileTypeFilter.Add("*"); var result = await picker.PickSingleFolderAsync(); if (result is not null) folder.Text = result.Path.Replace('/', '\\'); })); Grid.SetColumn(choose, 1); browse.Children.Add(choose); Row("音乐资料库", browse);
        var codec = Ui.Combo(Formats.Codecs.Select(x => (x.Value, (object)x.Key)), Store.Get("codec", "alac")); Row("默认下载音质", codec);
        var language = Ui.Combo(new[] { ("简体中文", (object)"zh-Hans-CN"), ("繁體中文（香港）", "zh-Hant-HK"), ("English", "en-US"), ("日本語", "ja") }, backendConfig.ValueKind == JsonValueKind.Object ? J.S(backendConfig.GetProperty("region"), "language") : "zh-Hans-CN"); Row("元数据语言", language);
        var rate = Ui.Combo(new[] { 44100, 48000, 96000, 192000 }.Select(x => ($"{x / 1000d:g} kHz", (object)x)), backendConfig.ValueKind == JsonValueKind.Object ? J.I(backendConfig.GetProperty("download"), "maxSampleRate") : 192000); Row("最高采样率", rate);
        var bits = Ui.Combo(new[] { ("16 bit", (object)16), ("24 bit", 24) }, backendConfig.ValueKind == JsonValueKind.Object ? J.I(backendConfig.GetProperty("download"), "maxBitDepth") : 24); Row("最高位深", bits);
        stack.Children.Add(Ui.Text("下载后端    内置本地服务 · 登录后即可下载", color: Ui.Muted));
        var actions = Ui.Stack(12, Orientation.Horizontal);
        actions.Children.Add(Ui.Button("保存设置", () => _ = Guard(async () =>
        {
            Store.Set("library", folder.Text.Replace('/', '\\')); Store.Set("codec", Ui.Selected<string>(codec));
            await Library.CallAsync("save_config", new() { ["state"] = Path.Combine(Store.DirectoryPath, "backend"), ["language"] = Ui.Selected<string>(language), ["rate"] = Ui.Selected<int>(rate), ["bits"] = Ui.Selected<int>(bits) });
            backendConfig = await Library.CallAsync("config", new() { ["state"] = Path.Combine(Store.DirectoryPath, "backend") });
            await ScanAsync(); Toast("设置已保存，原配置已自动备份");
        }), true));
        actions.Children.Add(Ui.Button("登录 Apple 账号", () => _ = LoginAsync())); actions.Children.Add(Ui.Button("重新连接后端", () => _ = Guard(async () => { if (backend is not null) { await BackendEventAsync(JsonSerializer.SerializeToElement(new { @event = "disconnected", message = "正在重新连接下载后端。" })); await backend.RestartAsync(); } }))); stack.Children.Add(actions);
        stack.Children.Add(Ui.Text("修改设置会保留原配置中的其他内容，并自动创建备份。", 12, color: Ui.Muted));
        var close = Ui.Combo(new[] { ("每次询问", (object)"ask"), ("最小化到托盘", "tray"), ("关闭程序", "exit") }, Store.Get("close_action", "ask")); close.SelectionChanged += (_, _) => Store.Set("close_action", Ui.Selected<string>(close)); Row("关闭主窗口时", close);
        stack.Children.Add(Ui.Text("音频输出", 23, true));
        var mode = Ui.Combo(new[] { ("系统共享（兼容模式）", (object)"shared"), ("WASAPI 独占", "wasapi"), ("ASIO（支持原生 DSD）", "asio") }, Audio.Config.Mode);
        var devices = new SafeComboBox { HorizontalAlignment = HorizontalAlignment.Stretch, PlaceholderText = "请选择 DAC 对应的输出设备" }; var dsd = new SafeComboBox { HorizontalAlignment = HorizontalAlignment.Stretch }; var note = Ui.Text("正在读取输出设备…", 12, color: Ui.Muted);
        var available = new List<AudioDevice>();
        var selections = new Dictionary<string, (string Device, string Dsd)> { [Audio.Config.Mode] = (Audio.Config.Device, Audio.Config.Dsd) }; var populatedMode = "";
        void Populate()
        {
            if (populatedMode.Length > 0 && devices.SelectedItem is ComboBoxItem selected && dsd.SelectedItem is ComboBoxItem selectedDsd) selections[populatedMode] = ((string)selected.Tag, (string)selectedDsd.Tag);
            var selectedMode = Ui.Selected<string>(mode); var saved = selections.GetValueOrDefault(selectedMode, (Device: "", Dsd: selectedMode == "asio" ? "native" : selectedMode == "shared" ? "pcm" : "dop"));
            devices.Items.Clear(); dsd.Items.Clear();
            if (selectedMode == "shared") { devices.Items.Add(new ComboBoxItem { Content = "Windows 默认音频设备", Tag = "" }); dsd.Items.Add(new ComboBoxItem { Content = "解码为 PCM", Tag = "pcm" }); }
            else
            {
                foreach (var device in available.Where(x => x.Kind == selectedMode)) devices.Items.Add(new ComboBoxItem { Content = device.Name, Tag = device.Id });
                if (saved.Device.Length > 0 && available.All(x => x.Kind != selectedMode || x.Id != saved.Device)) devices.Items.Add(new ComboBoxItem { Content = "已选设备当前不可用 · 请连接或重新选择", Tag = saved.Device });
                if (selectedMode == "asio") dsd.Items.Add(new ComboBoxItem { Content = "原生 DSD（保持源采样率，支持 DSD512）", Tag = "native" });
                dsd.Items.Add(new ComboBoxItem { Content = "DoP（DSD 数据封装为 PCM 帧传输）", Tag = "dop" });
            }
            devices.SelectedIndex = selectedMode == "shared" ? 0 : devices.Items.Cast<ComboBoxItem>().ToList().FindIndex(x => (string)x.Tag == saved.Device);
            dsd.SelectedIndex = Math.Max(0, dsd.Items.Cast<ComboBoxItem>().ToList().FindIndex(x => (string)x.Tag == saved.Dsd)); devices.IsEnabled = dsd.IsEnabled = selectedMode != "shared";
            populatedMode = selectedMode;
            note.Text = selectedMode == "shared" ? "共享模式保留软件音量，DSD 解码为 PCM。" : "直通输出旁路软件音量，请用 DAC 调节音量。设备不支持时会停止并提示，不自动重采样。DSD 直通支持 DSF 和未压缩 DFF；DST、WavPack DSD 请使用共享模式。DoP 最高档位还取决于 DAC 和 PCM 传输能力。";
        }
        async Task Discover()
        {
            await Guard(async () => { available = (await AudioService.InspectAsync(Paths.AudioHost, "--list")).Where(x => J.S(x, "kind").Length > 0).Select(x => new AudioDevice(J.S(x, "kind"), J.S(x, "id"), J.S(x, "name"))).ToList(); Populate(); });
        }
        mode.SelectionChanged += (_, _) => Populate(); Populate(); _ = Discover(); Row("输出模式", mode); Row("输出设备", devices); Row("DSD 播放方式", dsd);
        actions = Ui.Stack(12, Orientation.Horizontal); actions.Children.Add(Ui.Button("刷新设备", () => _ = Discover()));
        Button? probe = null;
        probe = Ui.Button("检测 DSD 能力", () => _ = Guard(async () =>
        {
            if (Ui.Selected<string>(mode) != "asio" || devices.SelectedItem is not ComboBoxItem device) { Toast("请先选择 ASIO 输出设备。"); return; }
            probe!.IsEnabled = false; CancelGap(); note.Text = "正在释放播放设备并检测 " + device.Content + "…";
            try
            {
                var info = await Audio.ProbeAsioAsync((string)device.Tag);
                note.Text = info.Count > 0 && info[0].TryGetProperty("dsd_rates", out var rates) ? device.Content + (rates.GetArrayLength() > 0 ? " 驱动报告支持：" + string.Join("、", rates.EnumerateArray().Select(x => "DSD" + x.GetInt32())) + "；播放时仍会验证实际通道格式。" : " 未报告可用的原生 DSD 采样率。") : "未获得设备能力，请检查驱动。";
            }
            catch (Exception error) { note.Text = "检测 " + device.Content + " 失败：" + error.Message; throw; }
            finally { probe.IsEnabled = true; }
        })); actions.Children.Add(probe);
        actions.Children.Add(Ui.Button("应用音频设置", () => _ = Guard(async () =>
        {
            if (devices.SelectedItem is not ComboBoxItem device) { Toast("请选择输出设备。"); return; }
            var config = new OutputConfig(Ui.Selected<string>(mode), (string)device.Tag, Ui.Selected<string>(dsd), device.Content.ToString()!);
            if (config.Mode != "shared" && available.All(x => x.Kind != config.Mode || x.Id != config.Device)) { Toast("所选设备当前不可用，请连接设备或重新选择。"); return; }
            CancelGap(); await Audio.ConfigureAsync(config); Store.Set("audio_output", config); Toast("音频输出设置已应用");
        }), true)); stack.Children.Add(actions); stack.Children.Add(note); stack.Children.Add(Ui.Button("查看音频输出链路", () => _ = ShowOutputChainAsync()));
        stack.Children.Add(Ui.Text("歌曲自然结束后，等待 2 秒再播放下一首；手动切歌立即响应。", 12, color: Ui.Muted));
        stack.Children.Add(Ui.Text("本地音频支持：\nAAC（.aac）、AAC／ALAC（.m4a、.m4b）、MP3（.mp3）、MP2（.mp2）、FLAC（.flac）、WAV（.wav）、AIFF／AIFC（.aif、.aiff、.aifc）。\nOgg Vorbis／Opus／FLAC（.ogg、.oga）、Opus（.opus）、Speex（.spx）、WMA（.wma）、Musepack（.mpc、.mpp、.mp+）、AC-3（.ac3）、E-AC-3（.eac3、.ec3）。\nDSD（.dsf、.dff、.dsdiff）、APE（.ape）、WavPack（.wv）、TAK（.tak）、TTA（.tta）。\nCUE 整轨（.cue）和 SACD ISO（.iso）：按曲目导入，按需准备缓存；SACD 保留 DSD。\n共享模式兼容所有现有解码格式；独占输出按设备实际能力选择。", 12, color: Ui.Muted));
        stack.Children.Add(Ui.Button("清理播放缓存", () => _ = Guard(async () =>
        {
            if (Audio.Preparing || Audio.Current?.Container.Length > 0) { Toast("请先选择普通音频或清空播放队列，再清理缓存。"); return; }
            var path = Path.GetFullPath(Path.Combine(Store.DirectoryPath, "audio-cache")); if (Path.GetDirectoryName(path) != Path.GetFullPath(Store.DirectoryPath)) throw new InvalidOperationException("缓存目录校验失败。");
            if (Directory.Exists(path)) await Task.Run(() => Directory.Delete(path, true)); Toast("播放缓存已清理");
        })));
        stack.Children.Add(Ui.Text("AM Dowloader · WinUI 3\n基于 AppleMusicDecrypt 的桌面应用", 12, color: Ui.Muted));
        return PageFrame("设置", "下载歌曲，按你的习惯管理音乐。", Ui.Scroll(stack));
    }
    private readonly Dictionary<string, (TextBlock Title, TextBlock Quality, TextBlock State, TextBlock Progress, Button Action)> downloadRows = [];
    private TextBlock? downloadSummary, downloadSpeeds;
    private TextBox? downloadLog;
    private Button? pauseDownloads;
    private Grid DownloadPage()
    {
        downloadRows.Clear(); var actions = Ui.Stack(12, Orientation.Horizontal);
        pauseDownloads = Ui.Button(queuePaused ? "▶ 继续队列" : "Ⅱ 暂停队列", () => _ = Guard(async () => { queuePaused = !queuePaused; UpdateDownloadView(); await NextJobAsync(); })); actions.Children.Add(pauseDownloads);
        actions.Children.Add(Ui.Button("重试失败", () => _ = Guard(async () => { foreach (var job in jobs.Where(x => x.State is "FAILED" or "cancelled")) job.State = "queued"; queuePaused = false; Store.Set("jobs", jobs); UpdateDownloadView(); await NextJobAsync(); })));
        actions.Children.Add(Ui.Button("清理已完成", () => { jobs.RemoveAll(x => x.State == "DONE"); Store.Set("jobs", jobs); RenderPage(); }));
        var stack = new Grid { RowSpacing = 16 }; foreach (var height in new[] { GridLength.Auto, new(1, GridUnitType.Star), GridLength.Auto, new(150) }) stack.RowDefinitions.Add(new() { Height = height });
        downloadSummary = Ui.Text("", 15, color: Ui.Muted); stack.Children.Add(downloadSummary);
        var list = Ui.Stack(4);
        var header = DownloadRow(); var headers = new[] { "曲目／链接", "音质", "状态", "进度", "操作" };
        for (var i = 0; i < headers.Length; i++) { var text = Ui.Text(headers[i], 13, color: Ui.Muted); Grid.SetColumn(text, i); header.Children.Add(text); } list.Children.Add(header);
        foreach (var job in jobs)
        {
            var row = DownloadRow(); row.CornerRadius = new(7); row.Background = job.State == "FAILED" ? Ui.Brush(110, 124, 65, 85) : Ui.Brush(60, 63, 62, 69);
            var title = Ui.Text(job.Caption); title.MaxLines = 2; var quality = Ui.Text(job.QualityText); var state = Ui.Text(job.StateText); var progress = Ui.Text(job.ProgressText); var action = Ui.Button(job.State is "FAILED" or "cancelled" ? "重试" : "取消", () => _ = JobActionAsync(job)); action.IsEnabled = job.State != "DONE";
            var controls = new FrameworkElement[] { title, quality, state, progress, action }; for (var i = 0; i < controls.Length; i++) { Grid.SetColumn(controls[i], i); row.Children.Add(controls[i]); }
            Ui.AddMenu(row, () => { var menu = new MenuFlyout(); menu.Items.Add(Ui.MenuItem("从队列删除", () => _ = JobActionAsync(job, true))); return menu; }); ToolTipService.SetToolTip(row, job.Error.Length > 0 ? job.Error : job.Url); list.Children.Add(row); downloadRows[job.Id] = (title, quality, state, progress, action);
        }
        var border = new Border { Child = Ui.Scroll(list), CornerRadius = new(10), Background = Ui.Brush(55, 13, 13, 15) }; Grid.SetRow(border, 1); stack.Children.Add(border);
        var status = new Grid(); downloadSpeeds = Ui.Text(speeds, 13, color: Ui.Muted); status.Children.Add(downloadSpeeds); var export = Ui.Button("↓ 导出诊断日志", () => _ = Guard(async () => { var picker = InitPicker(new FileSavePicker { SuggestedFileName = "wrapper-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") }); picker.FileTypeChoices.Add("文本日志", new List<string> { ".txt" }); var file = await picker.PickSaveFileAsync(); if (file is not null) await SendAsync(new { action = "export", path = file.Path }); })); export.HorizontalAlignment = HorizontalAlignment.Right; status.Children.Add(export); Grid.SetRow(status, 2); stack.Children.Add(status);
        downloadLog = new TextBox { Text = logs, IsReadOnly = true, AcceptsReturn = true, TextWrapping = TextWrapping.Wrap, FontFamily = new("Consolas"), FontSize = 12, CornerRadius = new(7) }; ScrollViewer.SetVerticalScrollBarVisibility(downloadLog, ScrollBarVisibility.Auto); Grid.SetRow(downloadLog, 3); stack.Children.Add(downloadLog); UpdateDownloadView();
        return PageFrame("下载队列", "", stack, actions);
    }
    private static Grid DownloadRow()
    { var row = new Grid { Padding = new(10), ColumnSpacing = 12, MinHeight = 48 }; foreach (var width in new[] { new GridLength(6, GridUnitType.Star), new(1.5, GridUnitType.Star), new(1, GridUnitType.Star), new(.8, GridUnitType.Star), new(70) }) row.ColumnDefinitions.Add(new() { Width = width }); return row; }
    private void UpdateDownloadView(bool structure = false)
    {
        if (page != "queue") return; if (structure) { RenderPage(); return; }
        if (downloadSummary is not null) downloadSummary.Text = $"{jobs.Count} 个任务 · {jobs.Count(x => x.State == "DONE")} 个已完成" + (queuePaused ? " · 队列已暂停，当前任务会继续完成" : "");
        if (pauseDownloads is not null) pauseDownloads.Content = queuePaused ? "▶ 继续队列" : "Ⅱ 暂停队列";
        foreach (var job in jobs) if (downloadRows.TryGetValue(job.Id, out var row)) { row.Title.Text = job.Caption; row.Quality.Text = job.QualityText; row.State.Text = job.StateText; row.Progress.Text = job.ProgressText; row.Action.Content = job.State is "FAILED" or "cancelled" ? "重试" : "取消"; row.Action.IsEnabled = job.State != "DONE"; }
        if (downloadSpeeds is not null) downloadSpeeds.Text = speeds;
        if (downloadLog is not null && downloadLog.Text != logs) { downloadLog.Text = logs; downloadLog.SelectionStart = logs.Length; }
    }
    private async Task LoginAsync(AccountEntry? automatic = null) => await Guard(async () =>
    {
        if (loginWindow is not null) { Restore(); loginWindow.Activate(); return; }
        Restore();
        try
        {
            loginView = new LoginView(Accounts, command => { if (!quitting) _ = Guard(async () => { try { await SendAsync(command); } catch (Exception error) { loginView?.BackendFailed(error.Message); throw; } }); }, () => loginWindow?.Close());
            loginWindow = new ToolWindow(this, "登录 Apple 账号", loginView, 490, 680, "取消"); loginWindow.Activate();
            if (automatic is not null) loginView.StartAutomatic(automatic);
            await loginWindow.Completion;
        }
        finally { loginView?.Cancel(); loginView = null; loginWindow = null; }
    });
}
