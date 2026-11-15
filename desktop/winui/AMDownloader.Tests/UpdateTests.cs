using System.IO.Compression;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using AMDownloader.Core;

internal static class UpdateTests
{
    public static async Task RunAsync(string root, Action<bool, string> check)
    {
        ReleaseVersion V(string value) { check(ReleaseVersion.TryParse(value, out var result), "valid version " + value); return result; }
        var current = V("v2.0.0-preview.6"); var next = V("2.0.0-preview.7");
        check(V("2.0.0-preview.10").CompareTo(V("2.0.0-preview.9")) > 0, "numeric prerelease order");
        check(V("2.0.0").CompareTo(next) > 0 && current.CompareTo(next) < 0, "stable and preview ordering");
        foreach (var value in new[] { "2.0", "02.0.0", "2.0.0-preview.01", "v2.0.0/evil", "2.0.0-preview..6" }) check(!ReleaseVersion.TryParse(value, out _), "invalid version rejected");
        var bytes = Encoding.UTF8.GetBytes("verified update payload"); var hash = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
        var release = Release(next.ToString(), bytes.Length, hash);
        AvailableUpdate? Select(params object[] items) => UpdateClient.Select(JsonSerializer.SerializeToUtf8Bytes(items), current);
        var offer = Select(release)!; check(offer.Version == next && offer.Sha256 == hash, "compatible newer release selected");
        check(Select(Release("2.0.0-preview.5", 1, hash)) is null, "no downgrade");
        check(Select(Release(next.ToString(), 1, hash, draft: true)) is null, "draft release ignored");
        check(UpdateClient.Select(JsonSerializer.SerializeToUtf8Bytes(new[] { Release("2.1.0-preview.1", 1, hash) }), V("2.0.0")) is null, "stable channel excludes preview");
        check(Select(release, Release("2.0.0", 1, hash))?.Version == V("2.0.0"), "stable upgrade offered to preview");
        Throws(() => Select(Release(next.ToString(), 1, "")), "missing release hash not reported as up to date");
        Throws(() => Select(Release(next.ToString(), 1, hash, url: "https://example.com/update.zip")), "foreign release asset rejected");
        foreach (var url in new[] { "http://github.com/Lauk1z/AM-Downloader/releases/download/x/y", "https://github.com/other/repo/releases/download/x/y", "https://release-assets.githubusercontent.com:8443/x", "https://evil.test/x" })
            Throws(() => UpdateClient.ValidateUri(new(url), true), "untrusted URL rejected");
        UpdateClient.ValidateUri(new("https://release-assets.githubusercontent.com/release-assets/1/x?token=public-download"), true);
        using var http = new HttpClient(new Handler((request, _) => Task.FromResult(request.RequestUri!.Host == "api.github.com"
            ? new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(JsonSerializer.SerializeToUtf8Bytes(new[] { release })) }
            : new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(bytes) })));
        using var client = new UpdateClient(http);
        check((await client.CheckAsync(current))?.Version == next, "HTTP release check");
        var stages = new List<UpdateProgress>(); var path = await client.DownloadAsync(offer, Path.Combine(root, "download"), new Reports(stages.Add), default);
        check(File.ReadAllBytes(path).SequenceEqual(bytes) && stages.Last().Fraction == .85, "verified download and completion progress");
        await RejectAsync(() => client.DownloadAsync(offer with { Sha256 = new string('0', 64) }, Path.Combine(root, "bad-hash"), null, default), "hash mismatch rejected");
        check(!Directory.GetFiles(Path.Combine(root, "bad-hash")).Any(), "bad payload removed");
        await RejectAsync(() => client.DownloadAsync(offer with { Size = bytes.Length + 1 }, Path.Combine(root, "bad-length"), null, default), "truncated payload rejected");
        using var cancelled = new CancellationTokenSource(); cancelled.Cancel();
        await RejectAsync(() => client.DownloadAsync(offer, Path.Combine(root, "cancel"), null, cancelled.Token), "cancelled download stops");
        using var redirectHttp = new HttpClient(new Handler((_, _) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.Redirect) { Headers = { Location = new("https://evil.test/update.zip") } })));
        using var redirectClient = new UpdateClient(redirectHttp);
        await RejectAsync(() => redirectClient.DownloadAsync(offer, Path.Combine(root, "redirect"), null, default), "foreign HTTP redirect rejected");

        var source = Path.Combine(root, "source"); var target = Path.Combine(root, "installed"); var profile = Path.Combine(target, "personal");
        Directory.CreateDirectory(profile); File.WriteAllText(Path.Combine(profile, "preferences.json"), "private-settings"); File.WriteAllBytes(Path.Combine(profile, "accounts.dat"), [7, 6, 5]);
        MakePackage(source, next.ToString(), "new"); MakePackage(target, current.ToString(), "old");
        File.WriteAllText(Path.Combine(target, "removed.dll"), "obsolete"); File.WriteAllText(Path.Combine(target, "user-modified.txt"), "original"); Manifest(target, profile);
        File.WriteAllText(Path.Combine(target, "user-modified.txt"), "keep my changes"); File.WriteAllText(Path.Combine(target, "user-song.flac"), "personal audio");
        var before = Snapshot(target);
        var transaction = new UpdateTransaction(source, target, Path.Combine(root, "backup-failed"), profile);
        Throws(() => transaction.Apply(name => { if (name == "new-feature.dll") throw new IOException("simulated write failure"); }), "interrupted apply rolls back");
        check(Same(before, Snapshot(target)), "rollback restores exact old installation and private data");
        transaction = new(source, target, Path.Combine(root, "backup-success"), profile); transaction.Apply();
        check(File.ReadAllText(Path.Combine(target, "AM Downloader WinUI.dll")) == "new", "new binaries installed");
        check(!File.Exists(Path.Combine(target, "removed.dll")) && File.ReadAllText(Path.Combine(target, "user-modified.txt")) == "keep my changes", "obsolete tracked file removed, modified file preserved");
        check(File.ReadAllText(Path.Combine(profile, "preferences.json")) == "private-settings" && File.ReadAllBytes(Path.Combine(profile, "accounts.dat")).SequenceEqual(new byte[] { 7, 6, 5 }) && File.ReadAllText(Path.Combine(target, "user-song.flac")) == "personal audio", "profile, account and local audio preserved");
        transaction.Rollback(); check(Same(before, Snapshot(target)), "startup failure rollback restores exact files");
        File.WriteAllText(Path.Combine(target, "new-feature.dll"), "custom");
        Throws(() => new UpdateTransaction(source, target, Path.Combine(root, "backup-conflict"), profile).Apply(), "custom filename collision blocked"); File.Delete(Path.Combine(target, "new-feature.dll"));
        using (var held = new FileStream(Path.Combine(target, "app-version.json"), FileMode.Open, FileAccess.Read, FileShare.Read))
            Throws(() => new UpdateTransaction(source, target, Path.Combine(root, "backup-locked"), profile).Apply(), "locked installation not overwritten");
        check(Same(before, Snapshot(target)), "locked-file failure leaves old installation intact");
        foreach (var relative in new[] { "../secret", "/root", "C:/secret", "sub/../../secret", "CON.txt", "folder/thing.", "file:stream" }) Throws(() => UpdatePackage.SafeFile(root, relative), "unsafe path rejected");

        var zip = Path.Combine(root, "package.zip");
        using (var archive = ZipFile.Open(zip, ZipArchiveMode.Create)) foreach (var file in Directory.EnumerateFiles(source)) archive.CreateEntryFromFile(file, "package/" + Path.GetFileName(file));
        var extracted = await UpdatePackage.ExtractAsync(zip, Path.Combine(root, "extract"), next.ToString(), null, default);
        check(UpdatePackage.ReadManifest(extracted).Count == 5, "valid complete archive extracted");
        await RejectAsync(() => UpdatePackage.ExtractAsync(zip, Path.Combine(root, "wrong-version"), "3.0.0", null, default), "archive version mismatch rejected");
        await RejectAsync(() => UpdatePackage.ExtractAsync(zip, Path.Combine(root, "cancel-extract"), next.ToString(), null, cancelled.Token), "extraction cancellation");
        foreach (var sample in new[] { "traversal", "duplicate", "symlink", "tamper" })
        {
            var malformed = Path.Combine(root, sample + ".zip"); File.Copy(zip, malformed);
            using (var archive = ZipFile.Open(malformed, ZipArchiveMode.Update))
            {
                var entry = archive.CreateEntry(sample switch { "traversal" => "package/../../outside", "duplicate" => "package/AM DOWNLOADER WINUI.DLL", "symlink" => "package/link", _ => "package/unknown.dll" });
                if (sample == "symlink") entry.ExternalAttributes = 0xA1FF << 16;
                using var stream = new StreamWriter(entry.Open()); stream.Write("untrusted");
            }
            await RejectAsync(() => UpdatePackage.ExtractAsync(malformed, Path.Combine(root, sample), next.ToString(), null, default), "malformed archive " + sample);
        }
        void Throws(Action action, string label)
        { var failed = false; try { action(); } catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or InvalidDataException) { failed = true; } check(failed, label); }
        async Task RejectAsync(Func<Task> action, string label)
        { var failed = false; try { await action(); } catch (Exception ex) when (ex is IOException or InvalidDataException or OperationCanceledException) { failed = true; } check(failed, label); }
    }
    internal static object Release(string version, int size, string hash, bool draft = false, string? url = null) => new
    {
        tag_name = "v" + version, draft, prerelease = version.Contains('-'), body = "## 更新\n- 小窗与全屏播放",
        assets = new[] { new { name = $"AM-Downloader-{version}-WinUI3-Windows-x64.zip", state = "uploaded", size, digest = "sha256:" + hash, browser_download_url = url ?? $"https://github.com/{UpdateClient.Repository}/releases/download/v{version}/AM-Downloader-{version}-WinUI3-Windows-x64.zip" } }
    };
    private static void MakePackage(string directory, string version, string value)
    {
        Directory.CreateDirectory(directory);
        foreach (var file in new[] { "AM Downloader WinUI.exe", "AM Downloader WinUI.dll", "AMDownloader.Updater.exe" }) File.WriteAllText(Path.Combine(directory, file), value);
        File.WriteAllText(Path.Combine(directory, "app-version.json"), JsonSerializer.Serialize(new AppPackageVersion(version), StateStore.Json));
        if (value == "new") File.WriteAllText(Path.Combine(directory, "new-feature.dll"), "feature");
        Manifest(directory);
    }
    private static void Manifest(string directory, string? exclude = null) => File.WriteAllText(Path.Combine(directory, "manifest.sha256.json"), JsonSerializer.Serialize(Directory.GetFiles(directory, "*", SearchOption.AllDirectories)
        .Where(x => Path.GetFileName(x) != "manifest.sha256.json" && (exclude is null || !UpdatePackage.Within(x, exclude))).ToDictionary(x => Path.GetRelativePath(directory, x).Replace('\\', '/'), UpdatePackage.Digest)));
    private static Dictionary<string, string> Snapshot(string directory) => Directory.GetFiles(directory, "*", SearchOption.AllDirectories).ToDictionary(x => Path.GetRelativePath(directory, x), UpdatePackage.Digest);
    private static bool Same(Dictionary<string, string> a, Dictionary<string, string> b) => a.Count == b.Count && a.All(x => b.GetValueOrDefault(x.Key) == x.Value);
    private sealed class Reports(Action<UpdateProgress> action) : IProgress<UpdateProgress> { public void Report(UpdateProgress value) => action(value); }
    private sealed class Handler(Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> action) : HttpMessageHandler
    { protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancel) => action(request, cancel); }
}
