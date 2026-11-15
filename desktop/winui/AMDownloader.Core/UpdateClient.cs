using System.Net;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace AMDownloader.Core;

public sealed record AvailableUpdate(ReleaseVersion Version, string Tag, string Notes, Uri Package, long Size, string Sha256);
public sealed record UpdateProgress(string Stage, double Fraction, long Downloaded = 0, long Total = 0);

public sealed class UpdateClient : IDisposable
{
    public const string Repository = "Lauk1z/AM-Downloader";
    public const long MaximumPackageBytes = 2L * 1024 * 1024 * 1024;
    private readonly HttpClient http;
    private readonly bool ownsClient;
    public UpdateClient(HttpClient? client = null)
    {
        ownsClient = client is null;
        http = client ?? new HttpClient(new HttpClientHandler { AllowAutoRedirect = false }) { Timeout = TimeSpan.FromMinutes(30) };
    }
    public async Task<AvailableUpdate?> CheckAsync(ReleaseVersion current, CancellationToken cancel = default)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancel); timeout.CancelAfter(TimeSpan.FromSeconds(25));
        using var response = await GetAsync(new($"https://api.github.com/repos/{Repository}/releases?per_page=100"), false, timeout.Token).ConfigureAwait(false);
        var json = await ReadBoundedAsync(response, 4 * 1024 * 1024, timeout.Token).ConfigureAwait(false);
        return Select(json, current);
    }
    public static AvailableUpdate? Select(byte[] json, ReleaseVersion current)
    {
        using var document = JsonDocument.Parse(json);
        if (document.RootElement.ValueKind != JsonValueKind.Array) throw new InvalidDataException("更新服务器返回了无效的数据。");
        AvailableUpdate? latest = null; ReleaseVersion? invalidPackage = null;
        foreach (var item in document.RootElement.EnumerateArray())
        {
            if (!item.TryGetProperty("draft", out var draft) || draft.ValueKind != JsonValueKind.False || !item.TryGetProperty("tag_name", out var tagValue)) continue;
            var tag = tagValue.GetString() ?? "";
            if (!ReleaseVersion.TryParse(tag, out var version) || version.CompareTo(current) <= 0 || latest is not null && version.CompareTo(latest.Version) <= 0) continue;
            if (!current.IsPreview && (version.IsPreview || item.TryGetProperty("prerelease", out var preview) && preview.ValueKind == JsonValueKind.True)) continue;
            if (!item.TryGetProperty("assets", out var assets) || assets.ValueKind != JsonValueKind.Array) continue;
            var name = $"AM-Downloader-{version}-WinUI3-Windows-x64.zip";
            foreach (var asset in assets.EnumerateArray())
            {
                if (!asset.TryGetProperty("name", out var named) || named.GetString() != name || !asset.TryGetProperty("state", out var state) || state.GetString() != "uploaded") continue;
                if (invalidPackage is null || version.CompareTo(invalidPackage) > 0) invalidPackage = version;
                if (!asset.TryGetProperty("size", out var size) || !size.TryGetInt64(out var bytes) || bytes <= 0 || bytes > MaximumPackageBytes) continue;
                var hash = asset.TryGetProperty("digest", out var digest) ? digest.GetString() ?? "" : "";
                if (!Regex.IsMatch(hash, "^sha256:[0-9a-fA-F]{64}$", RegexOptions.CultureInvariant)) continue;
                var expected = new Uri($"https://github.com/{Repository}/releases/download/{Uri.EscapeDataString(tag)}/{name}");
                if (!asset.TryGetProperty("browser_download_url", out var url) || !Uri.TryCreate(url.GetString(), UriKind.Absolute, out var uri) || uri != expected) continue;
                var notes = item.TryGetProperty("body", out var body) && body.ValueKind == JsonValueKind.String ? body.GetString() ?? "" : "";
                latest = new(version, tag, notes.Length > 32000 ? notes[..32000] : notes, uri, bytes, hash[7..].ToLowerInvariant());
            }
        }
        if (invalidPackage is not null && (latest is null || invalidPackage.CompareTo(latest.Version) > 0)) throw new InvalidDataException("新版本的下载信息不完整或未通过校验，请稍后重试。");
        return latest;
    }
    public async Task<string> DownloadAsync(AvailableUpdate update, string directory, IProgress<UpdateProgress>? progress, CancellationToken cancel)
    {
        Directory.CreateDirectory(directory);
        var temporary = Path.Combine(directory, "package.zip.part"); var final = Path.Combine(directory, "package.zip");
        try
        {
            using var response = await GetAsync(update.Package, true, cancel).ConfigureAwait(false);
            if (response.Content.Headers.ContentLength is long length && length != update.Size) throw new InvalidDataException("更新包大小与发布信息不一致。");
            await using var input = await response.Content.ReadAsStreamAsync(cancel).ConfigureAwait(false);
            using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            long written = 0; var clock = System.Diagnostics.Stopwatch.StartNew(); var buffer = new byte[131072];
            await using (var output = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None, buffer.Length, true))
            {
                while (true)
                {
                    var read = await input.ReadAsync(buffer, cancel).AsTask().WaitAsync(TimeSpan.FromSeconds(60), cancel).ConfigureAwait(false);
                    if (read == 0) break;
                    written += read; if (written > update.Size || written > MaximumPackageBytes) throw new InvalidDataException("更新包超过预期大小。");
                    hash.AppendData(buffer, 0, read); await output.WriteAsync(buffer.AsMemory(0, read), cancel).ConfigureAwait(false);
                    if (clock.ElapsedMilliseconds >= 100) { progress?.Report(new("正在下载", .85 * written / update.Size, written, update.Size)); clock.Restart(); }
                }
                await output.FlushAsync(cancel).ConfigureAwait(false);
            }
            cancel.ThrowIfCancellationRequested();
            if (written != update.Size || !CryptographicOperations.FixedTimeEquals(hash.GetHashAndReset(), Convert.FromHexString(update.Sha256))) throw new InvalidDataException("更新包校验失败，请重新下载。");
            File.Move(temporary, final); progress?.Report(new("下载完成，正在检查文件", .85, written, update.Size)); return final;
        }
        catch { if (File.Exists(temporary)) File.Delete(temporary); throw; }
    }
    private async Task<HttpResponseMessage> GetAsync(Uri uri, bool download, CancellationToken cancel)
    {
        for (var redirects = 0; redirects < 6; ++redirects)
        {
            ValidateUri(uri, download);
            using var request = new HttpRequestMessage(HttpMethod.Get, uri);
            request.Headers.UserAgent.ParseAdd("AMDownloader/" + ReleaseVersion.Current);
            request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue(download ? "application/octet-stream" : "application/vnd.github+json"));
            request.Headers.TryAddWithoutValidation("X-GitHub-Api-Version", "2022-11-28");
            var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancel).ConfigureAwait(false);
            if ((int)response.StatusCode is >= 300 and < 400 && response.Headers.Location is { } location)
            {
                uri = location.IsAbsoluteUri ? location : new(uri, location); response.Dispose(); continue;
            }
            if (!response.IsSuccessStatusCode)
            {
                var status = response.StatusCode; response.Dispose();
                throw new HttpRequestException(status is HttpStatusCode.Forbidden or HttpStatusCode.TooManyRequests ? "GitHub 暂时限制了检查频率，请稍后再试。" : $"更新服务器请求失败（{(int)status}），请稍后重试。");
            }
            return response;
        }
        throw new InvalidDataException("更新下载重定向次数过多。");
    }
    public static void ValidateUri(Uri uri, bool download)
    {
        var valid = uri.Scheme == "https" && uri.IsDefaultPort && uri.UserInfo.Length == 0 && uri.Fragment.Length == 0;
        valid &= download
            ? uri.Host == "release-assets.githubusercontent.com" || uri.Host == "github.com" && uri.AbsolutePath.StartsWith("/" + Repository + "/releases/download/", StringComparison.OrdinalIgnoreCase)
            : uri.Host == "api.github.com" && uri.AbsolutePath.StartsWith("/repos/" + Repository + "/", StringComparison.OrdinalIgnoreCase);
        if (!valid) throw new InvalidDataException("更新地址不是本项目的可信下载地址。");
    }
    private static async Task<byte[]> ReadBoundedAsync(HttpResponseMessage response, int limit, CancellationToken cancel)
    {
        if (response.Content.Headers.ContentLength > limit) throw new InvalidDataException("更新信息过大。");
        await using var input = await response.Content.ReadAsStreamAsync(cancel).ConfigureAwait(false);
        using var output = new MemoryStream(); var buffer = new byte[16384];
        int count; while ((count = await input.ReadAsync(buffer, cancel).ConfigureAwait(false)) > 0)
        { if (output.Length + count > limit) throw new InvalidDataException("更新信息过大。"); output.Write(buffer, 0, count); }
        return output.ToArray();
    }
    public void Dispose() { if (ownsClient) http.Dispose(); }
}
