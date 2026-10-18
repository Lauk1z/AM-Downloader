using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace AMDownloader.Core;

public sealed record Track
{
    public string Path { get; init; } = "";
    public string Title { get; init; } = "";
    public string Artist { get; init; } = "";
    public string Album { get; init; } = "";
    public double Duration { get; init; }
    public string Cover { get; init; } = "";
    public string Codec { get; init; } = "";
    public int Rate { get; init; }
    public int Bits { get; init; }
    public int Number { get; init; }
    public double Modified { get; init; }
    public string AlbumArtist { get; init; } = "";
    public int Year { get; init; }
    public int Disc { get; init; }
    public string Edition { get; init; } = "";
    public string Container { get; init; } = "";
    public string SourcePath { get; init; } = "";
    public double Start { get; init; }
    public int SourceIndex { get; init; }
    public string Area { get; init; } = "";
    [JsonIgnore] public string FilePath => Container.Length > 0 ? Container : Path;
    [JsonIgnore] public string DisplayArtist => AlbumArtist.Length > 0 ? AlbumArtist : Artist;
    [JsonIgnore] public bool IsDsd => Codec.ToLowerInvariant() is "dsd" or "dst";
    [JsonIgnore] public bool IsLossless => IsDsd || Codec.ToLowerInvariant() is "alac" or "flac" or "pcm" or "ape" or "wavpack" or "tta" or "tak" or "wma lossless";
    [JsonIgnore] public string FormatName => Area.Length > 0 ? "SACD ISO" : Container.Length > 0 ? "CUE" : System.IO.Path.GetExtension(Path).TrimStart('.').ToUpperInvariant();
    [JsonIgnore] public string AlbumKey
    {
        get
        {
            var parent = System.IO.Path.GetDirectoryName(FilePath) ?? "";
            if (Regex.IsMatch(System.IO.Path.GetFileName(parent), @"^(cd|disc|disk)[ _-]*\d+$", RegexOptions.IgnoreCase))
                parent = System.IO.Path.GetDirectoryName(parent) ?? parent;
            return JsonSerializer.Serialize(new[] { Album, DisplayArtist, Edition.Length > 0 ? Edition : Paths.Key(parent) });
        }
    }
    [JsonIgnore] public string Quality
    {
        get
        {
            if (IsDsd) return (Rate > 0 && Rate % 44100 == 0 ? $"DSD{Rate / 44100}" : "DSD") +
                (Codec.Equals("dst", StringComparison.OrdinalIgnoreCase) ? " (DST)" : "") + (Rate > 0 ? $" · 1 bit / {Rate / 1000000d:g} MHz" : "");
            if (!IsLossless) return Codec.Length > 0 ? Codec.ToUpperInvariant() : FormatName;
            var details = string.Join(" / ", new[] { Bits > 0 ? $"{Bits} bit" : "", Rate > 0 ? $"{Rate / 1000d:g} kHz" : "" }.Where(x => x.Length > 0));
            return (Rate > 48000 || Bits > 16 ? "高解析度无损" : "无损") + (details.Length > 0 ? " · " + details : "");
        }
    }
    [JsonIgnore] public string TimeText => Text.Duration(Duration);
}

public sealed record PlaylistEntry(string Path, string Title = "", string Artist = "", double Duration = 0)
{
    public static PlaylistEntry From(Track track) => new(track.Path, track.Title, track.Artist, track.Duration);
}
public sealed class Playlist
{
    public string Id { get; set; } = "playlist:" + Guid.NewGuid().ToString("N");
    public string Name { get; set; } = "新建歌单";
    public List<PlaylistEntry> Entries { get; set; } = [];
}
public sealed class DownloadJob
{
    public string Id { get; set; } = Guid.NewGuid().ToString("N");
    public string Url { get; set; } = "";
    public string Codec { get; set; } = "alac";
    public double Created { get; set; } = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000d;
    public string State { get; set; } = "queued";
    public string Title { get; set; } = "";
    public string Artist { get; set; } = "";
    public string Error { get; set; } = "";
    public string ActualCodec { get; set; } = "";
    public string Quality { get; set; } = "";
    public int Completed { get; set; }
    public int Total { get; set; }
    [JsonIgnore] public string Caption => Title.Length > 0 ? Title + (Artist.Length > 0 ? " · " + Artist : "") : Url;
    [JsonIgnore] public string QualityText => Quality.Length > 0 ? Quality : Formats.Codecs.GetValueOrDefault(ActualCodec.Length > 0 ? ActualCodec : Codec, Codec);
    [JsonIgnore] public string StateText => Formats.Stages.GetValueOrDefault(State, State);
    [JsonIgnore] public string ProgressText => Total > 0 ? $"{Completed} / {Total}" : "—";
}
public sealed record OutputConfig(string Mode = "shared", string Device = "", string Dsd = "native", string DeviceName = "");
public sealed record AudioDevice(string Kind, string Id, string Name);
public sealed record AccountEntry(string Username, string Secret = "", bool Automatic = false);

public static class Formats
{
    public static readonly Dictionary<string, string> Codecs = new()
    { ["alac"]="ALAC · 无损", ["aac"]="AAC · 256 kbps", ["ec3"]="Dolby Atmos", ["ac3"]="Dolby Digital", ["aac-binaural"]="AAC · 空间音频", ["aac-downmix"]="AAC · 混音", ["aac-legacy"]="AAC · 兼容模式" };
    public static readonly Dictionary<string, string> Stages = new()
    { ["queued"]="等待开始", ["starting"]="启动本地后端", ["resolving"]="读取曲目信息", ["WAITING"]="获取播放地址", ["awaiting_format"]="等待确认下载格式", ["DOWNLOADING"]="下载中", ["DECRYPTING"]="解密中", ["DONE"]="已完成", ["FAILED"]="失败", ["cancelled"]="已取消" };
    public static readonly HashSet<string> Extensions = new(".m4a .m4b .mp3 .mp2 .flac .wav .aac .opus .ogg .oga .spx .dsf .dff .dsdiff .aif .aiff .aifc .ape .wv .tta .tak .wma .mpc .mpp .mp+ .ac3 .eac3 .ec3 .cue .iso".Split(' '), StringComparer.OrdinalIgnoreCase);
    public static bool Importable(string path) => Extensions.Contains(System.IO.Path.GetExtension(path));
    public static List<string> ValidateLinks(string text)
    {
        var urls = text.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries).Distinct().ToList();
        if (urls.Count == 0) throw new ArgumentException("请粘贴 Apple Music 的歌曲、专辑、歌单或艺人链接。");
        foreach (var url in urls)
            if (!Uri.TryCreate(url, UriKind.Absolute, out var uri) || uri.Scheme != "https" || uri.Host is not ("music.apple.com" or "geo.music.apple.com") ||
                !uri.AbsolutePath.Split('/').Any(x => x is "song" or "album" or "playlist" or "artist"))
                throw new ArgumentException("请输入完整的 https://music.apple.com/ 歌曲、专辑、歌单或艺人链接。");
        return urls;
    }
}
public static class Paths
{
    public static string Key(string value) => System.IO.Path.GetFullPath(value).TrimEnd('\\').ToLowerInvariant();
    public static string Source(string path) => Regex.Replace(path, @"#amtrack=(?:\d+|(?:stereo|multichannel)-\d+)$", "");
}
public static class Text
{
    public static string Duration(double seconds) => $"{Math.Max(0, (int)seconds) / 60}:{Math.Max(0, (int)seconds) % 60:00}";
    public static string Redact(string text)
    {
        text = Regex.Replace(text, @"\x1b\[[0-9;]*m", "");
        text = Regex.Replace(text, "(?i)(music-token|authorization|password|cookie|two_step_code)([\\s:=\"']+)[^\\s,\"']+", "$1$2[已隐藏]");
        text = Regex.Replace(text, @"https?://\S+", "[链接已隐藏]");
        return Regex.Replace(text, @"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}", "[账号已隐藏]");
    }
}
