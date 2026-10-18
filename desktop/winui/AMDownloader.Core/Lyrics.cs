using System.Globalization;
using System.Text.RegularExpressions;

namespace AMDownloader.Core;

public sealed record LyricLine(long? Time, string Content);
public static class Lyrics
{
    public static List<LyricLine> Parse(string text)
    {
        var timed = new SortedDictionary<long, List<string>>(); var plain = new List<LyricLine>();
        var match = Regex.Match(text, @"\[offset:([+-]?\d+)\]", RegexOptions.IgnoreCase);
        var offset = match.Success ? long.Parse(match.Groups[1].Value) : 0;
        foreach (var line in text.Split('\n'))
        {
            var stamps = Regex.Matches(line, @"\[(\d+):(\d{2}(?:\.\d+)?)\]");
            var content = Regex.Replace(line, @"\[[^\]]*\]|<\d+:\d+(?:\.\d+)?>", "").Trim();
            if (stamps.Count == 0) { if (content.Length > 0) plain.Add(new(null, content)); continue; }
            foreach (Match stamp in stamps)
            {
                var time = Math.Max(0, (long)Math.Round((int.Parse(stamp.Groups[1].Value) * 60 + double.Parse(stamp.Groups[2].Value, CultureInfo.InvariantCulture)) * 1000) + offset);
                if (!timed.TryGetValue(time, out var lines)) timed[time] = lines = [];
                lines.Add(content.Length > 0 ? content : "•••");
            }
        }
        return timed.Count > 0 ? timed.Select(x => new LyricLine(x.Key, string.Join('\n', x.Value))).ToList() : plain;
    }
    public static int Active(IReadOnlyList<LyricLine> lines, long position)
    {
        var result = -1;
        for (var i = 0; i < lines.Count; i++) if (lines[i].Time is long time && time <= position) result = i;
        return result;
    }
}
