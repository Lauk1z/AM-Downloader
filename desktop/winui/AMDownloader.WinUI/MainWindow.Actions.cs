using System.Text.Json;
using AMDownloader.Core;
using AMDownloader.WinUI.Views;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage.Pickers;

namespace AMDownloader.WinUI;

public sealed partial class MainWindow
{
    private T InitPicker<T>(T picker) where T : class
    { WinRT.Interop.InitializeWithWindow.Initialize(picker, WinRT.Interop.WindowNative.GetWindowHandle(this)); return picker; }
    private async Task ImportFilesAsync() => await Guard(async () =>
    {
        var picker = InitPicker(new FileOpenPicker()); foreach (var extension in Formats.Extensions) picker.FileTypeFilter.Add(extension);
        await ImportPathsAsync((await picker.PickMultipleFilesAsync()).Select(x => x.Path));
    });
    private async Task ImportFolderAsync() => await Guard(async () =>
    {
        var picker = InitPicker(new FolderPicker()); picker.FileTypeFilter.Add("*"); var folder = await picker.PickSingleFolderAsync(); if (folder is not null) await ImportPathsAsync([folder.Path]);
    });
    private async Task ImportPathsAsync(IEnumerable<string> sources) => await Guard(async () =>
    {
        var incoming = await Task.Run(() => sources.SelectMany(path => Directory.Exists(path) ? Directory.EnumerateFiles(path, "*", new EnumerationOptions { RecurseSubdirectories = true, IgnoreInaccessible = true }) : new[] { path }).Where(Formats.Importable).Distinct(StringComparer.OrdinalIgnoreCase).ToList());
        if (incoming.Count == 0) return;
        Store.Set("imported_files", Store.Get("imported_files", new List<string>()).Concat(incoming).Distinct(StringComparer.OrdinalIgnoreCase).ToList());
        var keys = incoming.Select(Core.Paths.Key).ToHashSet(); Store.Set("removed_files", Store.Get("removed_files", new List<string>()).Where(x => !keys.Contains(Core.Paths.Key(Core.Paths.Source(x)))).ToList());
        await ScanAsync(); Toast($"已导入 {incoming.Count} 个文件");
    });
    private async Task AddMusicAsync() => await Guard(async () =>
    {
        var panel = Ui.Stack(14); panel.Width = 410; panel.Children.Add(Ui.Text("粘贴歌曲、专辑、艺人或歌单链接，每行一个。", color: Ui.Muted));
        var links = new TextBox { PlaceholderText = "https://music.apple.com/…", AcceptsReturn = true, Height = 130, TextWrapping = TextWrapping.Wrap }; panel.Children.Add(links);
        var validation = Ui.Text("", 12, color: Ui.Accent); panel.Children.Add(validation);
        var clipboard = Clipboard.GetContent();
        if (clipboard.Contains(StandardDataFormats.Text)) { try { var candidate = await clipboard.GetTextAsync(); Formats.ValidateLinks(candidate); links.Text = candidate; } catch (ArgumentException) { } catch (System.Runtime.InteropServices.COMException) { } }
        var codec = Ui.Combo(Formats.Codecs.Select(x => (x.Value, (object)x.Key)), Store.Get("codec", "alac")); panel.Children.Add(codec);
        var imports = Ui.Stack(8, Orientation.Horizontal); var command = "";
        imports.Children.Add(Ui.Button("导入本地音频", () => { command = "files"; activeDialog?.Hide(); })); imports.Children.Add(Ui.Button("导入文件夹", () => { command = "folder"; activeDialog?.Hide(); })); panel.Children.Add(imports);
        var result = await ShowDialogAsync("添加音乐", panel, "加入下载队列", validate: (_, e) => { try { Formats.ValidateLinks(links.Text); } catch (ArgumentException error) { e.Cancel = true; validation.Text = error.Message; } });
        if (command == "files") { await ImportFilesAsync(); return; } if (command == "folder") { await ImportFolderAsync(); return; }
        if (result == ContentDialogResult.Primary) await AddDownloadAsync(links.Text, Ui.Selected<string>(codec));
    });
    private async Task AddDownloadAsync(string text, string codec) => await Guard(async () =>
    {
        var urls = Formats.ValidateLinks(text); Store.Set("codec", codec);
        foreach (var url in urls) jobs.Add(new DownloadJob { Url = url, Codec = codec });
        queuePaused = false; Store.Set("jobs", jobs); Navigate("queue"); await NextJobAsync();
    });
    private MenuFlyout TrackMenu(List<Track> selected, List<Track>? playbackContext = null, int index = 0)
    {
        var menu = new MenuFlyout(); if (selected.Count == 0) return menu;
        menu.Items.Add(Ui.MenuItem("播放", () => _ = PlayTracksAsync(playbackContext ?? selected, index)));
        menu.Items.Add(Ui.MenuItem("下一首播放", () => QueueTracks(selected, true))); menu.Items.Add(Ui.MenuItem("最后播放", () => QueueTracks(selected, false)));
        menu.Items.Add(new MenuFlyoutSeparator());
        var all = selected.All(x => favourites.Contains(x.Path));
        menu.Items.Add(Ui.MenuItem(all ? "取消喜爱" : "喜爱", () => { foreach (var track in selected) { if (all) favourites.Remove(track.Path); else favourites.Add(track.Path); } Store.Set("favourites", favourites.ToList()); UpdatePlayer(); RenderPage(); }));
        var add = new MenuFlyoutSubItem { Text = "添加到歌单" };
        add.Items.Add(Ui.MenuItem("新建歌单…", () => _ = CreatePlaylistAsync(selected)));
        foreach (var list in playlists) add.Items.Add(Ui.MenuItem(list.Name, () => { list.Entries.AddRange(selected.Select(PlaylistEntry.From)); SavePlaylists(); Toast("已添加到“" + list.Name + "”"); })); menu.Items.Add(add);
        menu.Items.Add(Ui.MenuItem("前往专辑", () => Navigate("album:" + selected[0].AlbumKey)));
        menu.Items.Add(Ui.MenuItem("打开所在文件夹", () => _ = Guard(() =>
        {
            var folder = Path.GetDirectoryName(selected[0].FilePath)!;
            System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo("explorer.exe") { UseShellExecute = false, ArgumentList = { folder } });
            return Task.CompletedTask;
        })));
        menu.Items.Add(Ui.MenuItem("标签与封面编辑…", () => _ = EditAlbumAsync(selected)));
        menu.Items.Add(new MenuFlyoutSeparator()); menu.Items.Add(Ui.MenuItem("从资料库移除", () => _ = RemoveTracksAsync(selected, false)));
        var delete = Ui.MenuItem("删除本地文件…", () => _ = RemoveTracksAsync(selected, true)); delete.IsEnabled = selected.All(x => x.Container.Length == 0); menu.Items.Add(delete); return menu;
    }
    private MenuFlyout AlbumMenu(List<Track> album)
    {
        var menu = TrackMenu(album); var redundant = menu.Items.OfType<MenuFlyoutItem>().FirstOrDefault(x => x.Text == "前往专辑"); if (redundant is not null) menu.Items.Remove(redundant); return menu;
    }
    private void PlayerMenu() { if (Audio.Current is { } track) TrackMenu([track]).ShowAt(playButton); }
    private async Task RemoveTracksAsync(List<Track> selected, bool delete) => await Guard(async () =>
    {
        if (delete && selected.Any(x => x.Container.Length > 0)) return;
        var result = await ShowDialogAsync(delete ? "删除本地文件" : "从资料库移除", Ui.Text(delete ? $"将 {selected.Count} 个音频文件移到回收站？" : $"移除 {selected.Count} 首歌曲？本地文件会保留。"), "确定");
        if (result != ContentDialogResult.Primary) return;
        if (selected.Any(x => x.Path == Audio.Current?.Path)) { CancelGap(); await Audio.LoadAsync(null, false); }
        if (delete) await Task.Run(() => { foreach (var path in selected.Select(x => x.Path).Distinct()) Microsoft.VisualBasic.FileIO.FileSystem.DeleteFile(path, Microsoft.VisualBasic.FileIO.UIOption.OnlyErrorDialogs, Microsoft.VisualBasic.FileIO.RecycleOption.SendToRecycleBin); });
        Store.Set("removed_files", Store.Get("removed_files", new List<string>()).Concat(selected.Select(x => Core.Paths.Key(x.Path))).Distinct().ToList());
        await ScanAsync(); SaveQueue();
    });
    private async Task EditAlbumAsync(List<Track> album) => await Guard(async () =>
    {
        var panel = Ui.Stack(12); panel.Width = 620; var first = album[0]; var common = new Dictionary<string, TextBox>(); var changed = new HashSet<string>();
        foreach (var field in new[] { ("album", "专辑", first.Album), ("album_artist", "专辑艺人", first.AlbumArtist), ("year", "年份", first.Year > 0 ? first.Year.ToString() : "0"), ("edition", "版本／分组", first.Edition) })
        {
            var input = new TextBox { Header = field.Item2, Text = field.Item3 }; common[field.Item1] = input; panel.Children.Add(input); input.TextChanged += (_, _) => { if (input.Text == field.Item3) changed.Remove(field.Item1); else changed.Add(field.Item1); };
        }
        var coverPath = ""; var coverLabel = Ui.Text("封面保持不变", 12, color: Ui.Muted);
        panel.Children.Add(Ui.Button("替换封面…", () => _ = Guard(async () => { var picker = InitPicker(new FileOpenPicker()); foreach (var ext in new[] { ".png", ".jpg", ".jpeg", ".webp" }) picker.FileTypeFilter.Add(ext); var file = await picker.PickSingleFileAsync(); if (file is not null) { coverPath = file.Path; coverLabel.Text = file.Name; } }))); panel.Children.Add(coverLabel);
        var edits = new List<(TextBox Title, TextBox Artist, NumberBox Disc, NumberBox Number)>();
        foreach (var track in album)
        {
            var row = new Grid { ColumnSpacing = 6 }; foreach (var width in new[] { new GridLength(3, GridUnitType.Star), new(2, GridUnitType.Star), new(75), new(75) }) row.ColumnDefinitions.Add(new() { Width = width });
            var title = new TextBox { Text = track.Title, Header = "歌名" }; var artist = new TextBox { Text = track.Artist, Header = "艺人" }; var disc = new NumberBox { Value = track.Disc, Minimum = 0, Header = "碟号" }; var number = new NumberBox { Value = track.Number, Minimum = 0, Header = "曲序" };
            var controls = new FrameworkElement[] { title, artist, disc, number }; for (var i = 0; i < controls.Length; i++) { Grid.SetColumn(controls[i], i); row.Children.Add(controls[i]); } panel.Children.Add(row); edits.Add((title, artist, disc, number));
        }
        panel.Children.Add(Ui.Text("写入前自动备份原文件；不支持写入的格式和镜像曲目使用资料库覆盖信息。", 12, color: Ui.Muted));
        var validation = Ui.Text("", 12, color: Ui.Accent); panel.Children.Add(validation);
        var scroll = Ui.Scroll(panel); scroll.MaxHeight = 640;
        if (await ShowDialogAsync("标签与封面编辑", scroll, "保存修改", validate: (_, e) =>
        {
            var validYear = int.TryParse(common["year"].Text, out var year) && year is >= 0 and <= 9999;
            var validNumbers = edits.All(x => new[] { x.Disc.Value, x.Number.Value }.All(n => double.IsFinite(n) && n >= 0 && n <= 99999 && n == Math.Truncate(n)));
            if (!validYear || !validNumbers) { e.Cancel = true; validation.Text = "年份应为 0–9999；碟号和曲序应为 0–99999 的整数。"; }
        }) != ContentDialogResult.Primary) return;
        var changes = edits.Select(edit =>
        {
            var values = new Dictionary<string, object?> { ["title"] = edit.Title.Text, ["artist"] = edit.Artist.Text, ["disc"] = checked((int)edit.Disc.Value), ["number"] = checked((int)edit.Number.Value) };
            foreach (var key in changed) values[key] = key == "year" ? int.Parse(common[key].Text) : common[key].Text; return values;
        }).ToList();
        var resume = Audio.State is "playing" or "starting"; var current = Audio.Current?.Path; var position = Audio.Position;
        var affectsPlayback = album.Any(x => x.Path == current);
        if (affectsPlayback) await Audio.LoadAsync(null, false);
        try { await Library.CallAsync("edit", new() { ["tracks"] = album, ["changes"] = changes, ["cover"] = coverPath }); await ScanAsync(); }
        finally
        {
            if (affectsPlayback && Audio.Current is null && tracks.FirstOrDefault(x => x.Path == current) is { } replacement)
            { await Audio.LoadAsync(replacement, false); await Audio.SeekAsync(position); if (resume) await Audio.PlayAsync(); }
        }
        Toast("标签与封面已保存，原文件备份位于同一目录");
    });
    private async Task DuplicatesAsync() => await Guard(async () =>
    {
        Toast("正在比对文件指纹和歌曲信息…"); var result = await Library.CallAsync("duplicates", new() { ["tracks"] = tracks });
        var panel = Ui.Stack(14); panel.Width = 570;
        foreach (var group in result.EnumerateArray())
        { panel.Children.Add(Ui.Text(J.S(group, "kind"), 16, true)); foreach (var track in group.GetProperty("tracks").Deserialize<List<Track>>(StateStore.Json)!) panel.Children.Add(Ui.Text(track.Title + " · " + track.Quality + "\n" + track.Path, 13, color: Ui.Muted)); }
        if (panel.Children.Count == 0) panel.Children.Add(Ui.Text("未发现重复文件或相近版本。"));
        var scroll = Ui.Scroll(panel); scroll.MaxHeight = 600; await ShowDialogAsync("重复文件与专辑版本", scroll, "完成", close: "");
    });
    private void SavePlaylists() { Store.Set("playlists", playlists); BuildNavigation(); }
    private void PlaylistCreationMenu()
    { var menu = new MenuFlyout(); menu.Items.Add(Ui.MenuItem("新建歌单…", () => _ = CreatePlaylistAsync())); menu.Items.Add(Ui.MenuItem("导入 M3U 歌单…", () => _ = ImportM3uAsync())); menu.ShowAt(pageHost); }
    private async Task CreatePlaylistAsync(IEnumerable<Track>? initial = null) => await Guard(async () =>
    {
        var name = new TextBox { Text = "新建歌单", Width = 340 }; if (await ShowDialogAsync("新建歌单", name, "创建") != ContentDialogResult.Primary || name.Text.Trim().Length == 0) return;
        var list = new Playlist { Name = name.Text.Trim(), Entries = initial?.Select(PlaylistEntry.From).ToList() ?? [] }; playlists.Add(list); SavePlaylists(); Navigate(list.Id);
    });
    private MenuFlyout PlaylistMenu(Playlist list)
    {
        var menu = new MenuFlyout(); menu.Items.Add(Ui.MenuItem("重命名…", () => _ = Guard(async () => { var name = new TextBox { Text = list.Name, Width = 340 }; if (await ShowDialogAsync("重命名歌单", name, "保存") == ContentDialogResult.Primary && name.Text.Trim().Length > 0) { list.Name = name.Text.Trim(); SavePlaylists(); RenderPage(); } })));
        menu.Items.Add(Ui.MenuItem("导出 M3U…", () => _ = ExportM3uAsync(list)));
        menu.Items.Add(Ui.MenuItem("删除歌单…", () => _ = Guard(async () => { if (await ShowDialogAsync("删除歌单", Ui.Text("删除“" + list.Name + "”？音乐文件会保留。"), "删除") == ContentDialogResult.Primary) { playlists.Remove(list); SavePlaylists(); Navigate("home"); } }))); return menu;
    }
    private Grid PlaylistPage(Playlist? playlist)
    {
        if (playlist is null) return PageFrame("歌单", "", EmptyState());
        var lookup = tracks.ToDictionary(x => x.Path); var items = playlist.Entries.Select(x => lookup.GetValueOrDefault(x.Path) ?? new Track { Path = x.Path, Title = x.Title + " [文件缺失]", Artist = x.Artist, Duration = x.Duration }).ToList();
        var actions = Ui.Stack(8, Orientation.Horizontal); actions.Children.Add(Ui.Button("播放", () => _ = PlayTracksAsync(items.Where(x => lookup.ContainsKey(x.Path))), icon: "play")); actions.Children.Add(Ui.MenuIcon("歌单操作", () => PlaylistMenu(playlist)));
        var content = items.Count > 0 ? (UIElement)TrackTable(items, playlist) : EmptyState("把歌曲拖入此歌单", "可以从歌曲列表拖入，或右键歌曲选择“添加到歌单”。");
        var page = PageFrame(playlist.Name, $"{items.Count} 首歌曲 · 拖放调整顺序", content, actions); page.AllowDrop = true;
        page.DragOver += (_, e) => { if (!e.DataView.Properties.TryGetValue("am-playlist-id", out var origin) || !Equals(origin, playlist.Id)) e.AcceptedOperation = DataPackageOperation.Copy; };
        page.Drop += async (_, e) => { if (e.DataView.Properties.TryGetValue("am-playlist-id", out var origin) && Equals(origin, playlist.Id)) return; e.Handled = true; await DropIntoPlaylistAsync(playlist, e.DataView); }; return page;
    }
    private async Task DropIntoPlaylistAsync(Playlist playlist, DataPackageView data) => await Guard(async () =>
    {
        var values = new List<Track>();
        if (data.Contains(StandardDataFormats.Text))
        { var text = await data.GetTextAsync(); if (text.StartsWith("am-tracks:")) { var paths = JsonSerializer.Deserialize<List<string>>(text[10..])!; values = paths.Select(path => tracks.FirstOrDefault(x => x.Path == path)).OfType<Track>().ToList(); } }
        else if (data.Contains(StandardDataFormats.StorageItems))
        { var files = (await data.GetStorageItemsAsync()).Select(x => x.Path).ToList(); await ImportPathsAsync(files); values = tracks.Where(track => files.Any(file => Core.Paths.Key(track.FilePath) == Core.Paths.Key(file) || Directory.Exists(file) && Core.Paths.Key(track.FilePath).StartsWith(Core.Paths.Key(file) + "\\"))).ToList(); }
        playlist.Entries.AddRange(values.Select(PlaylistEntry.From)); SavePlaylists(); if (page == playlist.Id) RenderPage();
    });
    private async Task ImportM3uAsync() => await Guard(async () =>
    {
        var picker = InitPicker(new FileOpenPicker()); picker.FileTypeFilter.Add(".m3u"); picker.FileTypeFilter.Add(".m3u8"); var file = await picker.PickSingleFileAsync(); if (file is null) return;
        var result = M3u.Read(file.Path); await ImportPathsAsync(result.Entries.Select(x => Core.Paths.Source(x.Path)).Where(File.Exists));
        var list = new Playlist { Name = result.Name, Entries = result.Entries }; playlists.Add(list); SavePlaylists(); Navigate(list.Id); if (result.Warnings.Count > 0) Toast(string.Join("；", result.Warnings));
    });
    private async Task ExportM3uAsync(Playlist playlist) => await Guard(async () =>
    {
        var picker = InitPicker(new FileSavePicker { SuggestedFileName = playlist.Name }); picker.FileTypeChoices.Add("M3U8 歌单", new List<string> { ".m3u8" }); var file = await picker.PickSaveFileAsync(); if (file is null) return;
        M3u.Write(file.Path, playlist.Name, playlist.Entries); Toast("歌单已导出");
    });
}
