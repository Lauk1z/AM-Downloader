using System.Text.Json;
using System.Numerics;
using AMDownloader.Core;
using AMDownloader.WinUI.Services;
using AMDownloader.WinUI.Views;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Windowing;

namespace AMDownloader.WinUI;

public sealed partial class MainWindow
{
    private readonly SemaphoreSlim dialogs = new(1, 1);
    private JsonElement backendConfig;
    private bool fullscreen;
    private async Task Guard(Func<Task> action)
    { try { await action(); } catch (OperationCanceledException) { } catch (Exception error) { Log(error.Message); Toast(error.Message); } }
    public async Task InitializeAsync() => await Guard(async () =>
    {
        Navigate("home");
        var result = await Library.CallAsync("initialize"); backendConfig = result.GetProperty("config");
        backend = new(Paths, result.GetProperty("state").GetString()!);
        backend.Event += value => Dispatch(() => _ = Guard(() => BackendEventAsync(value)));
        backend.Log += line => Dispatch(() => Log(line));
        if (!options.NoBackend) _ = Guard(() => SendAsync(new { action = "start" }));
        await ScanAsync();
        var lookup = tracks.ToDictionary(x => x.Path);
        queue = Store.Get("playback_queue", new List<string>()).Distinct().Where(lookup.ContainsKey).Select(x => lookup[x]).ToList();
        var last = Store.Get("last_track", "");
        if (lookup.TryGetValue(last, out var track))
        {
            if (queue.All(x => x.Path != last)) queue.Add(track);
            playIndex = queue.FindIndex(x => x.Path == last); await Audio.LoadAsync(track, false);
            await LoadLyricsAsync(track);
            if (track.Cover.Length > 0) { Ui.SetImage(backdrop, await Library.BackdropAsync(track.Cover)); backdropSource = track.Cover; }
        }
        RenderPage(); UpdatePlayer();
        if (options.Smoke is not null) await RunSmokeAsync(options.Smoke);
    });
    private async Task ScanAsync() => await Guard(async () =>
    {
        if (scanning) { scanAgain = true; return; }
        scanning = true;
        try
        {
            do
            {
                scanAgain = false; Toast("正在更新音乐资料库…");
                var result = await Library.ScanAsync(Store); tracks = result.Tracks;
                var lookup = tracks.ToDictionary(x => x.Path);
                queue = queue.Where(x => lookup.ContainsKey(x.Path)).Select(x => lookup[x.Path]).ToList();
                playIndex = queue.FindIndex(x => x.Path == Audio.Current?.Path);
                if (result.Errors.Count > 0) Log(string.Join('\n', result.Errors));
                BuildNavigation(); RenderPage(); RefreshPanel(); Toast($"{tracks.Count} 首歌曲");
            } while (scanAgain);
        }
        finally { scanning = false; }
    });
    private void Navigate(string target)
    {
        var changed = page != target;
        page = target;
        if (target.StartsWith("album:")) activeAlbum = target[6..];
        UpdateNavigationSelection(true); RenderPage(changed);
    }
    private void RenderPage(bool transition = false)
    {
        pageHost.Content = page switch
        {
            "home" => HomePage(), "artists" => ArtistsPage(), "albums" => AlbumsPage(),
            "settings" => SettingsPage(), "queue" => DownloadPage(), "search" => SearchPage(),
            _ when page.StartsWith("album:") => AlbumPage(tracks.Where(x => x.AlbumKey == activeAlbum).ToList()),
            _ when page.StartsWith("playlist:") => PlaylistPage(playlists.FirstOrDefault(x => x.Id == page)),
            _ => SongsPage()
        };
        if (transition && pageHost.Content is UIElement element)
        {
            element.Translation = new(0, 8, 0);
            var compositor = CompositionTarget.GetCompositorForCurrentThread(); var motion = compositor.CreateVector3KeyFrameAnimation();
            motion.Target = "Translation"; motion.InsertKeyFrame(0, new Vector3(0, 8, 0));
            motion.InsertKeyFrame(1, Vector3.Zero, compositor.CreateCubicBezierEasingFunction(new(.2f, 0), new(0, 1)));
            motion.Duration = TimeSpan.FromMilliseconds(180); element.StartAnimation(motion);
        }
    }
    private async Task SearchChangedAsync() => await Guard(async () =>
    {
        var term = search.Text.Trim(); ++searchSerial;
        if (term.Length == 0) { Navigate("home"); return; }
        catalog.Clear(); catalogMessage = "正在搜索 Apple Music…"; Navigate("search");
        if (options.NoBackend) { catalogMessage = "诊断模式未连接下载后端"; return; }
        await SendAsync(new { action = "search", serial = searchSerial, term, country = Store.Get("country", "CN") });
    });
    private async Task PlayTracksAsync(IEnumerable<Track> values, int index = 0, bool random = false) => await Guard(async () =>
    {
        var original = values.ToList(); var selectedPath = original.ElementAtOrDefault(index)?.Path;
        var selection = original.Where(x => File.Exists(Core.Paths.Source(x.Path))).DistinctBy(x => Core.Paths.Key(x.Path)).ToList(); if (selection.Count == 0) return;
        CancelGap(); queue = selection; shuffled = random; shuffle.Reset(); playIndex = Math.Max(0, queue.FindIndex(x => x.Path == selectedPath));
        if (random) playIndex = Random.Shared.Next(queue.Count);
        await SelectTrackAsync(playIndex, true);
    });
    private async Task SelectTrackAsync(int index, bool autoplay)
    {
        CancelGap(); if (index < 0 || index >= queue.Count) return;
        playIndex = index; var track = queue[index];
        Store.Set("last_track", track.Path); SaveQueue();
        var recent = Store.Get("recently_played", new List<string>()); recent.Remove(track.Path); recent.Insert(0, track.Path); Store.Set("recently_played", recent.Take(100).ToList());
        await Audio.LoadAsync(track, autoplay); if (Audio.Current?.Path != track.Path) return;
        RefreshPanel(); await LoadLyricsAsync(track);
        if (track.Cover.Length > 0 && backdropSource != track.Cover)
        {
            var expected = track.Path; var blurred = await Library.BackdropAsync(track.Cover);
            if (Audio.Current?.Path == expected) { Ui.SetImage(backdrop, blurred); backdropSource = track.Cover; }
        }
    }
    private async Task TogglePlayAsync() => await Guard(async () =>
    {
        if (gapWaiting) { if (trackGap.Running) trackGap.Pause(); else trackGap.Start(); return; }
        if (Audio.Preparing) { Audio.TogglePrepareAutoplay(); return; }
        if (Audio.State is "playing" or "starting") await Audio.PauseAsync();
        else if (Audio.Current is not null) await Audio.PlayAsync();
        else await PlayTracksAsync(tracks);
    });
    private async Task SkipAsync(int direction) => await Guard(async () =>
    {
        CancelGap(); if (queue.Count == 0) return;
        int index;
        if (shuffled)
        {
            var path = shuffle.Step(queue.Select(x => x.Path), Audio.Current?.Path ?? "", direction);
            index = queue.FindIndex(x => x.Path == path);
        }
        else index = (playIndex + direction + queue.Count) % queue.Count;
        await SelectTrackAsync(index, true);
    });
    private void TrackEnded()
    {
        if (queue.Count == 0 || (!shuffled && !repeat && playIndex >= queue.Count - 1)) return;
        trackGap.Start();
    }
    private void CancelGap() => trackGap.Cancel();
    private async Task SeekTrackAsync(long position) => await Guard(async () =>
    {
        var resume = trackGap.Running; CancelGap(); await Audio.SeekAsync(position);
        if (resume) await Audio.PlayAsync();
    });
    private void SaveQueue() => Store.Set("playback_queue", queue.Select(x => x.Path).ToList());
    private void QueueTracks(IEnumerable<Track> values, bool next, int? destination = null)
    {
        var incoming = values.Where(x => x.Path != Audio.Current?.Path).DistinctBy(x => x.Path).ToList(); if (incoming.Count == 0) return;
        var insert = destination ?? (next ? Math.Clamp(playIndex + 1, 0, queue.Count) : queue.Count);
        var keys = incoming.Select(x => x.Path).ToHashSet(); insert -= queue.Take(insert).Count(x => keys.Contains(x.Path));
        queue.RemoveAll(x => keys.Contains(x.Path)); queue.InsertRange(Math.Clamp(insert, 0, queue.Count), incoming);
        playIndex = queue.FindIndex(x => x.Path == Audio.Current?.Path); shuffled = false; shuffle.Reset();
        if (Audio.Current is null) _ = SelectTrackAsync(0, false);
        SaveQueue(); RefreshPanel(); Toast(next ? "已加入下一首播放" : "已加入播放队列");
    }
    private void UpdatePlayer()
    {
        var track = Audio.Current;
        playerTitle.Text = track?.Title ?? "AM Dowloader";
        playerArtist.Text = track is null ? "选择一首音乐开始播放" : track.Artist + " — " + track.Album;
        if (playerCover.Tag as string != track?.Cover) { Ui.SetImage(playerCover, track?.Cover ?? ""); playerCover.Tag = track?.Cover; }
        Ui.SetGlyph(playButton, Audio.State is "playing" or "starting" || trackGap.Running || Audio.Preparing && Audio.PrepareAutoplay ? "\uE769" : "\uE768", 28);
        shuffleButton.Foreground = shuffled ? Ui.Accent : Ui.Muted;
        favouriteButton.Foreground = track is not null && favourites.Contains(track.Path) ? Ui.Accent : Ui.Muted;
        updatingProgress = true; progress.IsEnabled = track is not null && !Audio.Preparing; progress.Maximum = Math.Max(1, Audio.Duration); if (!seeking) progress.Value = Audio.Position; updatingProgress = false;
        elapsed.Text = track is null ? "" : Text.Duration(Audio.Position / 1000d); remaining.Text = track is null ? "" : "−" + Text.Duration((Audio.Duration - Audio.Position) / 1000d);
        tray?.Update(track is null ? "AM Dowloader" : track.Title + " · " + track.Artist,
            Audio.State is "playing" or "starting" || trackGap.Running || Audio.Preparing && Audio.PrepareAutoplay,
            track is not null || tracks.Count > 0, queue.Count > 0);
        UpdateLyrics();
    }
    private void ToggleCurrentFavourite()
    { if (Audio.Current is { } track) { if (!favourites.Add(track.Path)) favourites.Remove(track.Path); Store.Set("favourites", favourites.ToList()); UpdatePlayer(); if (page == "favourites") RenderPage(); } }
    private void ShowVolume()
    {
        if (volumePanel.Visibility == Visibility.Visible) { HideVolume(); return; }
        volumeTimer.Stop(); volumeSlider.Value = Audio.Volume; volumeSlider.IsEnabled = Audio.Config.Mode == "shared";
        ToolTipService.SetToolTip(volumeSlider, Audio.Config.Mode == "shared" ? "系统共享音量" : "独占输出直通 · 请调节 DAC 音量");
        playerActions.Visibility = Visibility.Collapsed; volumePanel.Visibility = Visibility.Visible; Ui.Animate(volumePanel);
    }
    private void HideVolume() { volumeTimer.Stop(); volumePanel.Visibility = Visibility.Collapsed; playerActions.Visibility = Visibility.Visible; }
    private void ToggleFullscreen() { fullscreen = !fullscreen; AppWindow.SetPresenter(fullscreen ? AppWindowPresenterKind.FullScreen : AppWindowPresenterKind.Overlapped); Ui.Animate(root); }
    public void Restore() { AppWindow.Show(); TrayIcon.Show(WinRT.Interop.WindowNative.GetWindowHandle(this)); Activate(); }
    private void HandleTray(string command)
    {
        switch (command)
        {
            case "show": Restore(); break; case "play": _ = TogglePlayAsync(); break; case "previous": _ = SkipAsync(-1); break; case "next": _ = SkipAsync(1); break;
            case "queue": Restore(); if (openPanel != "playing" || !body.IsPaneOpen) TogglePanel("playing"); break;
            case "output": Restore(); _ = ShowOutputChainAsync(); break;
            case "tray": MinimizeToTray(); break;
            case "quit": _ = ExitAsync(); break;
        }
    }
    private void MinimizeToTray() { HideVolume(); if (tray?.Available == true) AppWindow.Hide(); else (AppWindow.Presenter as OverlappedPresenter)?.Minimize(); }
    private async void OnClosing(AppWindow sender, AppWindowClosingEventArgs args)
    {
        if (quitting) return;
        args.Cancel = true; if (closeDialogOpen) return;
        var choice = Store.Get("close_action", "ask");
        if (choice == "tray") { MinimizeToTray(); return; }
        if (choice == "exit") { await ExitAsync(); return; }
        closeDialogOpen = true;
        try
        {
            var remember = new CheckBox { Content = "记住我的选择" };
            var panel = Ui.Stack(); panel.Children.Add(Ui.Text("最小化到托盘将继续播放音乐和下载。")); panel.Children.Add(remember);
            var result = await ShowDialogAsync("关闭 AM Dowloader", panel, "最小化到托盘", "关闭程序", "取消");
            if (result == ContentDialogResult.None) return;
            var action = result == ContentDialogResult.Primary ? "tray" : "exit";
            if (remember.IsChecked == true) Store.Set("close_action", action);
            if (action == "tray") MinimizeToTray(); else await ExitAsync();
        }
        finally { closeDialogOpen = false; }
    }
    private async Task ExitAsync()
    {
        if (quitting) return; quitting = true; CancelGap(); SaveQueue(); Store.Set("jobs", jobs); searchTimer.Stop(); volumeTimer.Stop(); activeDialog?.Hide(); loginWindow?.Close(); outputWindow?.Close();
        await Audio.DisposeAsync();
        if (backend is not null) await backend.DisposeAsync();
        await Library.DisposeAsync(); tray?.Dispose(); tray = null; Close(); Application.Current.Exit();
    }
    private async Task<ContentDialogResult> ShowDialogAsync(string title, UIElement content, string primary = "确定", string secondary = "", string close = "取消", Action<ContentDialog, ContentDialogButtonClickEventArgs>? validate = null, string? jobId = null)
    {
        await dialogs.WaitAsync();
        try
        {
            if (quitting || jobId is not null && (activeJob != jobId || jobs.All(x => x.Id != jobId))) return ContentDialogResult.None;
            activeDialog = new ContentDialog { XamlRoot = root.XamlRoot, Title = title, Content = content, PrimaryButtonText = primary, SecondaryButtonText = secondary, CloseButtonText = close, DefaultButton = ContentDialogButton.Primary, Tag = jobId };
            Ui.UseAccentResources(activeDialog);
            if (validate is not null) activeDialog.PrimaryButtonClick += (dialog, e) => validate(dialog, e);
            return await activeDialog.ShowAsync();
        }
        finally { activeDialog = null; dialogs.Release(); }
    }
    private async Task SendAsync(object command)
    { if (backend is null) throw new InvalidOperationException("下载后端尚未就绪。"); await backend.SendAsync(command); }
    private void Log(string line)
    { if (line.Length == 0) return; logs += Text.Redact(line) + "\n"; if (logs.Length > 40000) logs = logs[^30000..]; UpdateDownloadView(); }
    private async Task NextJobAsync()
    {
        if (activeJob is not null || queuePaused || quitting) return;
        var job = jobs.FirstOrDefault(x => x.State == "queued"); if (job is null) return;
        activeJob = job.Id; job.State = "starting"; job.ActualCodec = job.Quality = ""; Store.Set("jobs", jobs); UpdateDownloadView();
        try { await SendAsync(new { action = "download", id = job.Id, url = job.Url, codec = job.Codec, output_dir = Store.Get("library", Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyMusic), "AM Dowloader")) }); }
        catch (Exception error) { job.State = "FAILED"; job.Error = Text.Redact(error.Message); activeJob = null; queuePaused = true; Store.Set("jobs", jobs); UpdateDownloadView(); Log(error.Message); Toast(error.Message); }
    }
    private async Task JobActionAsync(DownloadJob job, bool remove = false) => await Guard(async () =>
    {
        if (remove) jobs.Remove(job);
        else if (job.State is "FAILED" or "cancelled") { job.State = "queued"; job.Error = ""; queuePaused = false; }
        else if (job.Id != activeJob && job.State != "DONE") job.State = "cancelled";
        if (job.Id == activeJob) { if (Equals(activeDialog?.Tag, job.Id)) activeDialog?.Hide(); await SendAsync(new { action = "cancel" }); }
        Store.Set("jobs", jobs); UpdateDownloadView(true); await NextJobAsync();
    });
    private async Task BackendEventAsync(JsonElement value)
    {
        var kind = J.S(value, "event"); var jobId = J.S(value, "job_id"); var job = jobs.FirstOrDefault(x => x.Id == jobId);
        switch (kind)
        {
            case "backend":
                var state = J.S(value, "state"); backendStatus.Text = state switch { "starting" => "●  后端启动中", "ready" => "●  后端已连接", _ => "●  连接失败" };
                Log(J.S(value, "message"));
                if (state == "ready")
                {
                    var regions = value.GetProperty("regions").Deserialize<List<string>>()!;
                    if (regions.Count > 0) backendStatus.Text = "●  已登录 · " + string.Join(" / ", regions);
                    else if (!autoLoginAttempted && loginView is null)
                    {
                        autoLoginAttempted = true; var account = Accounts.History.FirstOrDefault(x => x.Automatic && x.Secret.Length > 0);
                        if (account is not null) _ = LoginAsync(account);
                    }
                }
                break;
            case "stage": case "track":
                if (job is null) break;
                var stage = J.S(value, "stage"); if (stage.Length > 0 && stage is not ("DONE" or "FAILED")) job.State = stage;
                UpdateJob(job, value); UpdateDownloadView(); break;
            case "format_fallback":
                if (job is null || activeJob != job.Id) break;
                job.State = "awaiting_format"; UpdateJob(job, value); UpdateDownloadView();
                var result = await ShowDialogAsync("没有所选下载格式", Ui.Text($"{job.Caption}\n\n所选格式不可用。是否自动下载最高规格的可用音频？\n\n可用规格：{J.S(value, "quality")}", 15), "下载最高可用规格", close: "取消下载", jobId: job.Id);
                if (activeJob == job.Id) await SendAsync(new { action = "format_response", job_id = job.Id, request_id = J.S(value, "request_id"), accepted = result == ContentDialogResult.Primary });
                break;
            case "format_selected":
                if (job is not null) { job.ActualCodec = J.S(value, "codec"); job.Quality = J.S(value, "quality"); job.State = "WAITING"; Store.Set("jobs", jobs); UpdateDownloadView(); } break;
            case "finished":
                if (Equals(activeDialog?.Tag, jobId)) activeDialog?.Hide();
                if (job is not null) { job.State = J.S(value, "state"); UpdateJob(job, value); }
                if (activeJob == jobId) activeJob = null;
                Store.Set("jobs", jobs); UpdateDownloadView(true);
                if (job?.State == "DONE") _ = ScanAsync();
                await NextJobAsync(); break;
            case "log": Log(J.S(value, "text")); break;
            case "speed": speeds = $"下载 {J.S(value, "download")} · 解密 {J.S(value, "decrypt")}"; UpdateDownloadView(); break;
            case "catalog":
                if (J.I(value, "serial") != searchSerial) break;
                catalog = value.GetProperty("results").EnumerateArray().Select(x => x.Clone()).ToList(); catalogMessage = J.S(value, "error"); if (page == "search") RenderPage(); break;
            case "twofa": case "login":
                loginView?.Receive(value);
                if (kind == "login" && J.B(value, "ok")) backendStatus.Text = "●  已登录 · " + string.Join(" / ", value.GetProperty("regions").Deserialize<List<string>>()!);
                break;
            case "exported": Toast("诊断日志已导出：" + J.S(value, "path")); break;
            case "fatal": case "error": case "disconnected":
                var message = J.S(value, "message"); if (message.Length == 0) message = "下载后端已断开，可以重新连接后重试。";
                Log(message); Toast(message); loginView?.BackendFailed(message);
                if (activeJob is not null) { if (Equals(activeDialog?.Tag, activeJob)) activeDialog?.Hide(); var active = jobs.FirstOrDefault(x => x.Id == activeJob); if (active is not null) { active.State = "FAILED"; active.Error = message; } activeJob = null; Store.Set("jobs", jobs); UpdateDownloadView(); }
                break;
        }
    }
    private static void UpdateJob(DownloadJob job, JsonElement value)
    {
        if (J.S(value, "title") is { Length: > 0 } title) job.Title = title;
        if (J.S(value, "artist") is { Length: > 0 } artist) job.Artist = artist;
        if (value.TryGetProperty("completed", out var completed)) job.Completed = completed.GetInt32();
        if (value.TryGetProperty("total", out var total)) job.Total = total.GetInt32();
        if (J.S(value, "error") is { Length: > 0 } error) job.Error = Text.Redact(error);
    }
}
internal static class J
{
    internal static string S(JsonElement value, string key) => value.ValueKind == JsonValueKind.Object && value.TryGetProperty(key, out var item) && item.ValueKind == JsonValueKind.String ? item.GetString() ?? "" : "";
    internal static int I(JsonElement value, string key) => value.TryGetProperty(key, out var item) && item.TryGetInt32(out var result) ? result : 0;
    internal static bool B(JsonElement value, string key) => value.TryGetProperty(key, out var item) && item.ValueKind == JsonValueKind.True;
}
