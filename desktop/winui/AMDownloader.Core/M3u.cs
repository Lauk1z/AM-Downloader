using System.Text;
using System.Text.RegularExpressions;

namespace AMDownloader.Core;

public static class M3u
{
    public static (string Name, List<PlaylistEntry> Entries, List<string> Warnings) Read(string filename)
    {
        Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
        var raw = File.ReadAllBytes(filename); string? text = null;
        foreach (var encoding in raw.Length > 1 && (raw[0] == 255 && raw[1] == 254 || raw[0] == 254 && raw[1] == 255)
            ? new[] { raw[0] == 255 ? Encoding.Unicode : Encoding.BigEndianUnicode }
            : new[] { new UTF8Encoding(false, true), Encoding.GetEncoding("gb18030", EncoderFallback.ExceptionFallback, DecoderFallback.ExceptionFallback), Encoding.GetEncoding(1252) })
            try { text = encoding.GetString(raw).TrimStart('\ufeff'); break; } catch (DecoderFallbackException) { }
        if (text is null) throw new InvalidDataException("无法识别歌单文本编码。");
        var name = Path.GetFileNameWithoutExtension(filename); var entries = new List<PlaylistEntry>(); var warnings = new List<string>();
        string title = "", virtualTrack = ""; double duration = 0;
        foreach (var rawLine in text.Split('\n'))
        {
            var line = rawLine.Trim(); if (line.Length == 0) continue;
            if (line.StartsWith("#PLAYLIST:")) name = line[10..].Trim();
            else if (line.StartsWith("#EXTINF:"))
            {
                var details = line[8..].Split(',', 2); title = details.Length > 1 ? details[1] : "";
                duration = double.TryParse(details[0], System.Globalization.CultureInfo.InvariantCulture, out var d) && double.IsFinite(d) ? Math.Max(0, d) : 0;
            }
            else if (line.StartsWith("#EXT-AM-TRACK:")) virtualTrack = line[14..].Trim();
            else if (!line.StartsWith('#'))
            {
                if (Uri.TryCreate(line, UriKind.Absolute, out var uri) && uri.IsFile) line = uri.LocalPath;
                if (Regex.IsMatch(line, @"^[a-zA-Z][\w+.-]*://")) warnings.Add("跳过网络地址：" + line);
                else
                {
                    var source = Path.GetFullPath(line, Path.GetDirectoryName(Path.GetFullPath(filename))!);
                    var logical = source + (Regex.IsMatch(virtualTrack, @"^(\d+|(stereo|multichannel)-\d+)$") ? "#amtrack=" + virtualTrack : "");
                    if (Formats.Importable(source)) entries.Add(new(logical, title.Length > 0 ? title : Path.GetFileNameWithoutExtension(source), "", duration));
                    else warnings.Add("跳过不支持的文件：" + line);
                }
                title = virtualTrack = ""; duration = 0;
            }
        }
        return (name, entries, warnings);
    }
    public static void Write(string filename, string name, IEnumerable<PlaylistEntry> entries)
    {
        static string Clean(string s) => s.Replace('\r', ' ').Replace('\n', ' ');
        if (Path.GetExtension(filename).ToLowerInvariant() is not (".m3u" or ".m3u8")) throw new ArgumentException("请选择 .m3u 或 .m3u8 文件。");
        var lines = new List<string> { "#EXTM3U", "#PLAYLIST:" + Clean(name) };
        var parent = Path.GetDirectoryName(Path.GetFullPath(filename))!;
        foreach (var entry in entries)
        {
            var source = Paths.Source(entry.Path);
            lines.Add($"#EXTINF:{Math.Round(entry.Duration)},{Clean(string.Join(" - ", new[] { entry.Artist, entry.Title }.Where(x => x.Length > 0)))}");
            if (source != entry.Path) lines.Add("#EXT-AM-TRACK:" + entry.Path[(source.Length + 9)..]);
            var relative = Path.GetRelativePath(parent, source); if (relative.StartsWith('#')) relative = "." + Path.DirectorySeparatorChar + relative;
            lines.Add(relative);
        }
        File.WriteAllText(filename + ".tmp", string.Join('\n', lines) + "\n", new UTF8Encoding(true));
        File.Move(filename + ".tmp", filename, true);
    }
}
