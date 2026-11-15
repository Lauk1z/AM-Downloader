using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace AMDownloader.Core;

public sealed record AppPackageVersion(string Version, int UpdaterProtocol = 1);
public sealed record UpdateJob(string Id, string Target, string Profile, string Version, int ParentId, long ParentStartedUtc, bool NoBackend);
public sealed record UpdateResult(string Version, bool Success, string Message, int UpdaterId);

public static class UpdatePackage
{
    public static string CacheRoot => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "AMDownloader", "Updates");
    public static string JobDirectory(string id)
    {
        if (!Guid.TryParseExact(id, "N", out _)) throw new InvalidDataException("更新任务编号无效。");
        return Path.Combine(CacheRoot, id);
    }
    public static string ProfileReceipt(string profile) => Path.Combine(CacheRoot, "result-" + Convert.ToHexString(SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(Path.GetFullPath(profile).ToLowerInvariant())))[..24] + ".json");
    public static string LockName(string target) => @"Local\AMDownloader.Update." + Convert.ToHexString(SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(Path.TrimEndingDirectorySeparator(Path.GetFullPath(target)).ToLowerInvariant())))[..24];
    public static bool InstallationBusy(string target)
    {
        using var gate = new Mutex(false, LockName(target));
        try { if (!gate.WaitOne(0)) return true; } catch (AbandonedMutexException) { }
        gate.ReleaseMutex(); return false;
    }
    public static bool Within(string path, string directory) => Path.GetFullPath(path).StartsWith(Path.TrimEndingDirectorySeparator(Path.GetFullPath(directory)) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase);
    public static string SafeFile(string directory, string relative)
    {
        var parts = relative.Replace('\\', '/').Split('/');
        if (parts.Length == 0 || parts.Any(x => x.Length == 0 || x is "." or ".." || x.EndsWith(' ') || x.EndsWith('.') || x.Contains(':') || x.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 ||
            Regex.IsMatch(x.Split('.')[0], "^(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])$", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)))
            throw new InvalidDataException("更新包包含不安全的文件路径。");
        var full = Path.GetFullPath(Path.Combine(directory, Path.Combine(parts)));
        if (!Within(full, directory)) throw new InvalidDataException("更新文件超出安装目录。");
        for (var parent = directory; parent is not null;)
        {
            if ((Directory.Exists(parent) || File.Exists(parent)) && (File.GetAttributes(parent) & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("更新目录包含链接，无法安全替换。");
            var tail = Path.GetRelativePath(parent, full).Split(Path.DirectorySeparatorChar);
            if (tail.Length == 1) break;
            parent = Path.Combine(parent, tail[0]);
        }
        if (File.Exists(full) && (File.GetAttributes(full) & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("更新目标包含文件链接。");
        return full;
    }
    private static bool Protected(string relative) => Path.GetFileName(relative).Equals("preferences.json", StringComparison.OrdinalIgnoreCase) || relative.EndsWith(".qcow2", StringComparison.OrdinalIgnoreCase) ||
        new[] { "downloads", "updates", "cache", "data" }.Contains(relative.Replace('\\', '/').Split('/')[0], StringComparer.OrdinalIgnoreCase);
    public static Dictionary<string, string> ReadManifest(string directory)
    {
        var path = SafeFile(directory, "manifest.sha256.json");
        if (new FileInfo(path).Length > 8 * 1024 * 1024) throw new InvalidDataException("更新文件清单过大。");
        using var doc = JsonDocument.Parse(File.ReadAllText(path)); var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (doc.RootElement.ValueKind != JsonValueKind.Object) throw new InvalidDataException("更新文件清单无效。");
        foreach (var item in doc.RootElement.EnumerateObject())
        {
            SafeFile(directory, item.Name);
            if (Protected(item.Name) || item.Name.Equals("manifest.sha256.json", StringComparison.OrdinalIgnoreCase) || item.Value.ValueKind != JsonValueKind.String ||
                !Regex.IsMatch(item.Value.GetString()!, "^[0-9a-fA-F]{64}$", RegexOptions.CultureInvariant) || !result.TryAdd(item.Name, item.Value.GetString()!.ToLowerInvariant()))
                throw new InvalidDataException("更新文件清单包含重复或受保护的文件。");
        }
        if (result.Count is 0 or > 20000) throw new InvalidDataException("更新文件数量无效。");
        return result;
    }
    public static string Digest(string path)
    { using var stream = File.OpenRead(path); return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant(); }
    public static void VerifyDirectory(string directory, Dictionary<string, string> manifest, CancellationToken cancel = default)
    {
        var files = Directory.EnumerateFiles(directory, "*", SearchOption.AllDirectories).Select(x => Path.GetRelativePath(directory, x).Replace('\\', '/')).ToHashSet(StringComparer.OrdinalIgnoreCase);
        if (!files.SetEquals(manifest.Keys.Append("manifest.sha256.json"))) throw new InvalidDataException("更新包内容与文件清单不一致。");
        foreach (var (relative, hash) in manifest)
        {
            cancel.ThrowIfCancellationRequested(); var file = SafeFile(directory, relative);
            if (Digest(file) != hash) throw new InvalidDataException("更新文件校验失败：" + relative);
        }
    }
    public static async Task<string> ExtractAsync(string archive, string work, string version, IProgress<UpdateProgress>? progress, CancellationToken cancel)
    {
        return await Task.Run(async () =>
        {
            var destination = Path.Combine(work, "payload"); Directory.CreateDirectory(destination);
            using var zip = ZipFile.OpenRead(archive);
            if (zip.Entries.Count is 0 or > 24000) throw new InvalidDataException("更新包文件数量无效。");
            var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase); string? top = null; long total = 0;
            foreach (var item in zip.Entries)
            {
                cancel.ThrowIfCancellationRequested(); var name = item.FullName.Replace('\\', '/').TrimEnd('/');
                SafeFile(destination, name);
                if (!names.Add(name) || ((item.ExternalAttributes >> 16) & 0xF000) == 0xA000 || (item.ExternalAttributes & 0x400) != 0) throw new InvalidDataException("更新包包含重复路径或文件链接。");
                var parts = name.Split('/'); top ??= parts[0]; if (parts[0] != top || item.Name.Length > 0 && parts.Length < 2) throw new InvalidDataException("更新包目录结构无效。");
                total = checked(total + item.Length);
                if (total > 4L * 1024 * 1024 * 1024 || item.Length > UpdateClient.MaximumPackageBytes) throw new InvalidDataException("更新包解压大小超限。");
            }
            long completed = 0; var clock = System.Diagnostics.Stopwatch.StartNew();
            foreach (var item in zip.Entries)
            {
                cancel.ThrowIfCancellationRequested(); var name = item.FullName.Replace('\\', '/').TrimEnd('/'); var target = SafeFile(destination, name);
                if (item.Name.Length == 0) { Directory.CreateDirectory(target); continue; }
                Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                await using (var input = item.Open())
                await using (var output = new FileStream(target, FileMode.CreateNew, FileAccess.Write, FileShare.None, 131072, true))
                {
                    var buffer = new byte[131072]; long written = 0; int count;
                    while ((count = await input.ReadAsync(buffer, cancel).ConfigureAwait(false)) > 0)
                    {
                        written += count; if (written > item.Length) throw new InvalidDataException("更新包文件大小不匹配。");
                        await output.WriteAsync(buffer.AsMemory(0, count), cancel).ConfigureAwait(false);
                    }
                    if (written != item.Length) throw new InvalidDataException("更新文件不完整。");
                }
                completed += item.Length;
                if (clock.ElapsedMilliseconds >= 100) { progress?.Report(new("正在解压更新", .85 + .09 * completed / Math.Max(1, total))); clock.Restart(); }
            }
            var source = SafeFile(destination, top!); var manifest = ReadManifest(source);
            foreach (var required in new[] { "AM Downloader WinUI.exe", "AM Downloader WinUI.dll", "AMDownloader.Updater.exe", "app-version.json" })
                if (!manifest.ContainsKey(required)) throw new InvalidDataException("更新包缺少运行文件：" + required);
            progress?.Report(new("正在校验更新文件", .95)); VerifyDirectory(source, manifest, cancel);
            var metadata = JsonSerializer.Deserialize<AppPackageVersion>(File.ReadAllText(Path.Combine(source, "app-version.json")), StateStore.Json);
            if (metadata?.Version != version || metadata.UpdaterProtocol != 1) throw new InvalidDataException("更新包版本或更新协议不匹配。");
            progress?.Report(new("校验完成，正在准备重启", .98)); return source;
        }, cancel).ConfigureAwait(false);
    }
    public static void WriteJob(string work, UpdateJob job)
    {
        if (!Path.GetFullPath(work).Equals(Path.GetFullPath(JobDirectory(job.Id)), StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("更新工作目录无效。");
        Directory.CreateDirectory(work); File.WriteAllText(Path.Combine(work, "job.json"), JsonSerializer.Serialize(job, StateStore.Json));
    }
    public static UpdateJob ReadJob(string id) => JsonSerializer.Deserialize<UpdateJob>(File.ReadAllText(Path.Combine(JobDirectory(id), "job.json")), StateStore.Json) ?? throw new InvalidDataException("更新任务无效。");
    public static void SignalReady(string? id, string profile, string target)
    {
        if (id is null) return;
        var job = ReadJob(id);
        if (!Path.TrimEndingDirectorySeparator(Path.GetFullPath(job.Target)).Equals(Path.TrimEndingDirectorySeparator(Path.GetFullPath(target)), StringComparison.OrdinalIgnoreCase) ||
            !Path.TrimEndingDirectorySeparator(Path.GetFullPath(job.Profile)).Equals(Path.TrimEndingDirectorySeparator(Path.GetFullPath(profile)), StringComparison.OrdinalIgnoreCase) || job.Version != ReleaseVersion.Current)
            throw new InvalidDataException("更新启动信息不匹配。");
        File.WriteAllText(Path.Combine(JobDirectory(id), "ready.json"), JsonSerializer.Serialize(new { pid = Environment.ProcessId, version = ReleaseVersion.Current }, StateStore.Json));
    }
}

public sealed class UpdateTransaction
{
    private readonly string source, target, backup, profile;
    private readonly List<(string Path, bool Existed)> touched = [];
    public UpdateTransaction(string source, string target, string backup, string profile)
    {
        this.source = Path.GetFullPath(source); this.target = Path.TrimEndingDirectorySeparator(Path.GetFullPath(target)); this.backup = Path.GetFullPath(backup); this.profile = Path.GetFullPath(profile);
        if (this.target.Equals(Path.GetPathRoot(this.target), StringComparison.OrdinalIgnoreCase) || this.target.Equals(this.profile, StringComparison.OrdinalIgnoreCase) || this.target.Equals(this.source, StringComparison.OrdinalIgnoreCase) || this.source.Equals(this.backup, StringComparison.OrdinalIgnoreCase) ||
            UpdatePackage.Within(this.source, this.target) || UpdatePackage.Within(this.backup, this.target) || !File.Exists(Path.Combine(this.target, "AM Downloader WinUI.exe"))) throw new InvalidDataException("安装目录不适合自动更新。");
    }
    public void Apply(Action<string>? beforeCopy = null)
    {
        var next = UpdatePackage.ReadManifest(source); UpdatePackage.VerifyDirectory(source, next);
        var previous = UpdatePackage.ReadManifest(target);
        var writes = next.Where(x => !File.Exists(Target(x.Key)) || UpdatePackage.Digest(Target(x.Key)) != x.Value).Select(x => x.Key).Append("manifest.sha256.json").ToList();
        var deletes = previous.Where(x => !next.ContainsKey(x.Key) && File.Exists(Target(x.Key)) && UpdatePackage.Digest(Target(x.Key)) == x.Value).Select(x => x.Key).ToList();
        foreach (var relative in writes.Concat(deletes))
        {
            var path = Target(relative); var exists = File.Exists(path);
            if (exists && relative != "manifest.sha256.json" && !previous.ContainsKey(relative)) throw new IOException("安装目录存在同名自定义文件：" + relative);
            if (exists) { var saved = UpdatePackage.SafeFile(backup, relative); Directory.CreateDirectory(Path.GetDirectoryName(saved)!); File.Copy(path, saved, false); }
        }
        try
        {
            foreach (var relative in writes)
            {
                var path = Target(relative); beforeCopy?.Invoke(relative); touched.Add((relative, File.Exists(path)));
                Directory.CreateDirectory(Path.GetDirectoryName(path)!); File.Copy(UpdatePackage.SafeFile(source, relative), path, true);
            }
            foreach (var relative in deletes) { touched.Add((relative, true)); File.Delete(Target(relative)); }
            foreach (var (relative, hash) in next) if (UpdatePackage.Digest(Target(relative)) != hash) throw new IOException("更新文件写入校验失败：" + relative);
        }
        catch { Rollback(); throw; }
    }
    public void Rollback()
    {
        foreach (var (relative, existed) in touched.AsEnumerable().Reverse())
        {
            var path = Target(relative);
            if (existed)
            {
                var original = UpdatePackage.SafeFile(backup, relative);
                if (!File.Exists(path) || UpdatePackage.Digest(path) != UpdatePackage.Digest(original)) File.Copy(original, path, true);
            }
            else if (File.Exists(path)) File.Delete(path);
        }
        touched.Clear();
    }
    private string Target(string relative)
    {
        var path = UpdatePackage.SafeFile(target, relative);
        if (path.Equals(profile, StringComparison.OrdinalIgnoreCase) || UpdatePackage.Within(path, profile)) throw new InvalidDataException("更新文件会覆盖个人资料目录。");
        return path;
    }
}
