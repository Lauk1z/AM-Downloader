using System.Text.Json;
using AMDownloader.Core;

namespace AMDownloader.WinUI.Services;

public sealed class LibraryService : IAsyncDisposable
{
    private readonly JsonProcess process;
    private readonly string profile;
    public LibraryService(RuntimePaths paths, StateStore store)
    {
        profile = store.DirectoryPath;
        process = new(paths.Python, ["-u", paths.Utility, "--resources", paths.Resources, "--bundle", paths.Bundle], paths.Resources, Path.Combine(paths.Bundle, "deps"));
        process.StartReading();
    }
    public Task<JsonElement> CallAsync(string action, Dictionary<string, object?>? values = null, CancellationToken cancel = default)
    {
        values ??= []; values["action"] = action; values["profile"] = profile;
        return process.RequestAsync(values, cancel);
    }
    public async Task<(List<Track> Tracks, List<string> Errors)> ScanAsync(StateStore store)
    {
        var result = await CallAsync("scan", new() { ["folder"] = store.Get("library", Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyMusic), "AM Dowloader")),
            ["extra"] = store.Get("imported_files", new List<string>()), ["excluded"] = store.Get("removed_files", new List<string>()) });
        return (result.GetProperty("tracks").Deserialize<List<Track>>(StateStore.Json)!, result.GetProperty("errors").Deserialize<List<string>>()!);
    }
    public async Task<string> PrepareAsync(Track track, CancellationToken cancel) => (await CallAsync("prepare", new() { ["track"] = track }, cancel)).GetString()!;
    public async Task<string> BackdropAsync(string cover) => (await CallAsync("backdrop", new() { ["cover"] = cover })).GetString()!;
    public ValueTask DisposeAsync() => process.DisposeAsync();
}
