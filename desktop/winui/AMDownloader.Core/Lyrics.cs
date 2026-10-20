using System.Globalization;
using System.Text.RegularExpressions;

namespace AMDownloader.Core;

public sealed record LyricWord(int Index, int Length, long Start, long? End);
public sealed record LyricGlyph(int Index, int Length, long Start, long End);
public sealed record LyricLine(long? Time, string Content, IReadOnlyList<LyricWord>? Words = null);
public static class Lyrics
{
    public static List<LyricLine> Parse(string text)
    {
        var timed = new SortedDictionary<long, List<LyricLine>>(); var plain = new List<LyricLine>();
        var match = Regex.Match(text, @"\[offset:([+-]?\d+)\]", RegexOptions.IgnoreCase);
        var offset = match.Success ? long.Parse(match.Groups[1].Value) : 0;
        foreach (var line in text.Split('\n'))
        {
            var stamps = Regex.Matches(line, @"\[(\d+):(\d{2}(?:\.\d+)?)\]");
            var body = Regex.Replace(line, @"\[[^\]]*\]", "").Trim();
            var markers = Regex.Matches(body, @"<(\d+):(\d{2}(?:\.\d+)?)>");
            var content = Regex.Replace(body, @"<\d+:\d+(?:\.\d+)?>", "");
            if (stamps.Count == 0) { if (content.Length > 0) plain.Add(new(null, content)); continue; }
            foreach (Match stamp in stamps)
            {
                var time = Math.Max(0, Timestamp(stamp) + offset);
                if (!timed.TryGetValue(time, out var lines)) timed[time] = lines = [];
                var words = new List<LyricWord>(); var removed = 0;
                var shift = Timestamp(stamp) - Timestamp(stamps[0]);
                if (markers.Count > 0 && markers[0].Index > 0) words.Add(new(0, markers[0].Index, time, Math.Max(0, Timestamp(markers[0]) + offset + shift)));
                for (var i = 0; i < markers.Count; i++)
                {
                    var marker = markers[i]; removed += marker.Length;
                    var end = i + 1 < markers.Count ? markers[i + 1].Index : body.Length;
                    var length = end - marker.Index - marker.Length;
                    if (length > 0) words.Add(new(marker.Index + marker.Length - removed, length, Math.Max(0, Timestamp(marker) + offset + shift), i + 1 < markers.Count ? Math.Max(0, Timestamp(markers[i + 1]) + offset + shift) : null));
                }
                lines.Add(new(time, content.Length > 0 ? content : "•••", words));
            }
        }
        return timed.Count > 0 ? timed.Select(x =>
        {
            var words = new List<LyricWord>(); var index = 0;
            foreach (var line in x.Value)
            {
                words.AddRange((line.Words ?? []).Select(word => word with { Index = word.Index + index }));
                index += line.Content.Length + 1;
            }
            return new LyricLine(x.Key, string.Join('\n', x.Value.Select(line => line.Content)), words);
        }).ToList() : plain;
    }
    private static long Timestamp(Match stamp) => (long)Math.Round((int.Parse(stamp.Groups[1].Value) * 60 + double.Parse(stamp.Groups[2].Value, CultureInfo.InvariantCulture)) * 1000);
    public static List<LyricGlyph> Timing(LyricLine line, long end)
    {
        var result = new List<LyricGlyph>();
        if (line.Time is not long start) return result;
        end = Math.Max(start + 1, end);
        var paragraphIndex = 0;
        foreach (var paragraph in line.Content.Split('\n'))
        {
            var indices = StringInfo.ParseCombiningCharacters(paragraph);
            for (var i = 0; i < indices.Length; i++)
            {
                var index = paragraphIndex + indices[i]; var length = (i + 1 < indices.Length ? indices[i + 1] : paragraph.Length) - indices[i];
                var word = line.Words?.FirstOrDefault(x => index >= x.Index && index < x.Index + x.Length);
                var from = word is null ? 0 : Array.FindIndex(indices, x => paragraphIndex + x == word.Index);
                if (from < 0) from = 0;
                var count = word is null ? indices.Length : indices.Count(x => paragraphIndex + x >= word.Index && paragraphIndex + x < word.Index + word.Length);
                var wordStart = Math.Clamp(word?.Start ?? start, start, end); var wordEnd = Math.Clamp(word?.End ?? end, wordStart, end);
                result.Add(new(index, length, wordStart + (wordEnd - wordStart) * (i - from) / count, wordStart + (wordEnd - wordStart) * (i - from + 1) / count));
            }
            paragraphIndex += paragraph.Length + 1;
        }
        return result;
    }
    public static int Active(IReadOnlyList<LyricLine> lines, long position)
    {
        var result = -1;
        for (var i = 0; i < lines.Count; i++) if (lines[i].Time is long time && time <= position) result = i;
        return result;
    }
}
