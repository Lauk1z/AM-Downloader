using System.Reflection;
using System.Text.RegularExpressions;

namespace AMDownloader.Core;

public sealed record ReleaseVersion(int Major, int Minor, int Patch, string Preview = "") : IComparable<ReleaseVersion>
{
    public bool IsPreview => Preview.Length > 0;
    public static string Current => typeof(ReleaseVersion).Assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()!.InformationalVersion.Split('+')[0];
    public static bool TryParse(string text, out ReleaseVersion version)
    {
        version = new(0, 0, 0);
        if (text.Length > 100) return false;
        var match = Regex.Match(text, @"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$", RegexOptions.CultureInvariant);
        if (!match.Success || !int.TryParse(match.Groups[1].Value, out var major) || !int.TryParse(match.Groups[2].Value, out var minor) || !int.TryParse(match.Groups[3].Value, out var patch)) return false;
        var preview = match.Groups[4].Value;
        if (preview.Split('.').Any(x => x.Length > 1 && x[0] == '0' && x.All(char.IsAsciiDigit))) return false;
        version = new(major, minor, patch, preview); return true;
    }
    public int CompareTo(ReleaseVersion? other)
    {
        if (other is null) return 1;
        foreach (var pair in new[] { (Major, other.Major), (Minor, other.Minor), (Patch, other.Patch) })
            if (pair.Item1 != pair.Item2) return pair.Item1.CompareTo(pair.Item2);
        if (Preview == other.Preview) return 0;
        if (!IsPreview) return 1; if (!other.IsPreview) return -1;
        var left = Preview.Split('.'); var right = other.Preview.Split('.');
        for (var i = 0; i < Math.Min(left.Length, right.Length); ++i)
        {
            var a = left[i]; var b = right[i]; if (a == b) continue;
            var an = a.All(char.IsAsciiDigit); var bn = b.All(char.IsAsciiDigit);
            if (an && bn && a.Length != b.Length) return a.Length.CompareTo(b.Length);
            if (an != bn) return an ? -1 : 1;
            return StringComparer.Ordinal.Compare(a, b);
        }
        return left.Length.CompareTo(right.Length);
    }
    public override string ToString() => $"{Major}.{Minor}.{Patch}" + (IsPreview ? "-" + Preview : "");
}
