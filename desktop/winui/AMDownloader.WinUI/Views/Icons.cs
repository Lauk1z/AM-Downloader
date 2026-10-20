using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Data;
using Microsoft.UI.Xaml.Markup;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Shapes;

namespace AMDownloader.WinUI.Views;

internal static class Icons
{
    private static readonly IValueConverter EnabledOpacity = new IconOpacityConverter();
    // Artwork shares a 24-unit canvas, rounded 2.25-unit strokes and consistent optical insets.
    private static readonly Dictionary<string, (string Stroke, string Fill)> Paths = new()
    {
        ["play"] = ("", "M7.7 3.65C6.5 2.9 5.25 3.6 5.25 5.05V18.95C5.25 20.4 6.5 21.1 7.7 20.35L19.1 13.4C20.2 12.73 20.2 11.27 19.1 10.6Z"),
        ["pause"] = ("", "M6.35 3.5H8.65Q10 3.5 10 4.85V19.15Q10 20.5 8.65 20.5H6.35Q5 20.5 5 19.15V4.85Q5 3.5 6.35 3.5Z M15.35 3.5H17.65Q19 3.5 19 4.85V19.15Q19 20.5 17.65 20.5H15.35Q14 20.5 14 19.15V4.85Q14 3.5 15.35 3.5Z"),
        ["next"] = ("", "M3.4 5.15Q2 4.25 2 5.95V18.05Q2 19.75 3.4 18.85L12.35 13.2Q13.7 12.35 12.35 11.5Z M13.9 5.15Q12.5 4.25 12.5 5.95V18.05Q12.5 19.75 13.9 18.85L22.35 13.2Q23.7 12.35 22.35 11.5Z"),
        ["previous"] = ("", "M20.6 5.15Q22 4.25 22 5.95V18.05Q22 19.75 20.6 18.85L11.65 13.2Q10.3 12.35 11.65 11.5Z M10.1 5.15Q11.5 4.25 11.5 5.95V18.05Q11.5 19.75 10.1 18.85L1.65 13.2Q.3 12.35 1.65 11.5Z"),
        ["shuffle"] = ("M3 6.25H5C9.4 6.25 14.1 17.75 18.5 17.75H21 M3 17.75H5C7.1 17.75 8.9 15.1 10.2 13.35 M13.8 10.65C15.1 8.9 16.9 6.25 18.5 6.25H21 M18 3.25L21 6.25L18 9.25 M18 14.75L21 17.75L18 20.75", ""),
        ["repeat"] = ("M3.5 11V9.5C3.5 6.9 5.4 5.25 8 5.25H20 M17 2.25L20 5.25L17 8.25 M20.5 13V14.5C20.5 17.1 18.6 18.75 16 18.75H4 M7 15.75L4 18.75L7 21.75", ""),
        ["star"] = ("", "M11.15 3.25Q12 1.55 12.85 3.25L15.15 7.9L20.3 8.65Q22.2 8.92 20.83 10.25L17.1 13.88L17.98 19.02Q18.3 20.9 16.61 20.01L12 17.59L7.39 20.01Q5.7 20.9 6.02 19.02L6.9 13.88L3.17 10.25Q1.8 8.92 3.7 8.65L8.85 7.9Z"),
        ["lossless"] = ("M2 12C3.35 4.2 5.15 4.2 7 12C8.85 19.8 10.65 19.8 12 12 M7 12C8.35 4.2 10.15 4.2 12 12C13.85 19.8 15.65 19.8 17 12 M12 12C13.35 4.2 15.15 4.2 17 12C18.85 19.8 20.65 19.8 22 12", ""),
        ["lyrics"] = ("M7.5 17.75L4.5 21V17.45C3.1 17 2.5 15.85 2.5 14.25V6.75C2.5 4.4 3.9 3 6.25 3H17.75C20.1 3 21.5 4.4 21.5 6.75V14C21.5 16.35 20.1 17.75 17.75 17.75Z", "M7.25 7H9.5Q10.25 7 10.25 7.75V9.75C10.25 11.5 9.2 12.6 7.5 13V11.45C8.3 11.2 8.7 10.75 8.7 10H7.25Q6.5 10 6.5 9.25V7.75Q6.5 7 7.25 7Z M13.75 7H16Q16.75 7 16.75 7.75V9.75C16.75 11.5 15.7 12.6 14 13V11.45C14.8 11.2 15.2 10.75 15.2 10H13.75Q13 10 13 9.25V7.75Q13 7 13.75 7Z"),
        ["queue"] = ("M8.25 5.5H20.5 M8.25 12H20.5 M8.25 18.5H20.5", "M4.75 5.5A1.5 1.5 0 1 1 1.75 5.5A1.5 1.5 0 1 1 4.75 5.5 M4.75 12A1.5 1.5 0 1 1 1.75 12A1.5 1.5 0 1 1 4.75 12 M4.75 18.5A1.5 1.5 0 1 1 1.75 18.5A1.5 1.5 0 1 1 4.75 18.5"),
        ["volume"] = ("M16 8.25C18.1 10.3 18.1 13.7 16 15.75 M19 5.25C22.8 8.95 22.8 15.05 19 18.75", "M4 8.25H6.5L10.9 4.65Q12.5 3.35 12.5 5.4V18.6Q12.5 20.65 10.9 19.35L6.5 15.75H4Q2.5 15.75 2.5 14.25V9.75Q2.5 8.25 4 8.25Z"),
        ["volume-low"] = ("", "M4 8.25H6.5L10.9 4.65Q12.5 3.35 12.5 5.4V18.6Q12.5 20.65 10.9 19.35L6.5 15.75H4Q2.5 15.75 2.5 14.25V9.75Q2.5 8.25 4 8.25Z"),
        ["refresh"] = ("M20 10.5C19.35 6.6 16.15 3.75 12 3.75A8.25 8.25 0 1 0 20.05 14 M20.25 3.5V10.5H13.25", ""),
        ["home"] = ("M3 10.25L10.1 4.15Q12 2.5 13.9 4.15L21 10.25 M5 9.25V18.25Q5 20.5 7.25 20.5H16.75Q19 20.5 19 18.25V9.25 M9.25 20.5V14Q9.25 12.75 10.5 12.75H13.5Q14.75 12.75 14.75 14V20.5", ""),
        ["album"] = ("M7.5 3H16.5 M5.5 6.5H18.5 M6.25 10H17.75Q20.5 10 20.5 12.75V18.25Q20.5 21 17.75 21H6.25Q3.5 21 3.5 18.25V12.75Q3.5 10 6.25 10Z", ""),
        ["recent"] = ("M20.5 12A8.5 8.5 0 1 1 3.5 12A8.5 8.5 0 1 1 20.5 12 M12 6.75V12H8.5", ""),
        ["artist"] = ("M5.5 10.5V11.5C5.5 15.1 8.4 17.75 12 17.75C15.6 17.75 18.5 15.1 18.5 11.5V10.5 M12 17.75V21 M8.5 21H15.5", "M12 2.25C9.8 2.25 8.25 3.85 8.25 6V10.5C8.25 12.65 9.8 14.25 12 14.25C14.2 14.25 15.75 12.65 15.75 10.5V6C15.75 3.85 14.2 2.25 12 2.25Z"),
        ["songs"] = ("", "M10.25 5.75Q10.25 4.4 11.55 4.05L18.3 2.25Q19.5 1.93 19.5 3.2V6.2Q19.5 7.1 18.6 7.35L12.75 8.9V17.25C12.75 20.1 9.7 21.5 7.25 21.5C5.1 21.5 3.75 20.25 3.75 18.65C3.75 16.1 7.25 14.9 10.25 15.5Z"),
        ["favourites"] = ("M6.5 3.5H17.5Q20.5 3.5 20.5 6.5V17.5Q20.5 20.5 17.5 20.5H6.5Q3.5 20.5 3.5 17.5V6.5Q3.5 3.5 6.5 3.5Z", "M11.5 6.9Q12 5.9 12.5 6.9L13.75 9.45L16.55 9.85Q17.65 10 16.85 10.78L14.82 12.75L15.3 15.55Q15.5 16.65 14.5 16.13L12 14.8L9.5 16.13Q8.5 16.65 8.7 15.55L9.18 12.75L7.15 10.78Q6.35 10 7.45 9.85L10.25 9.45Z"),
        ["download"] = ("M12 3.5V15 M7.5 10.5L12 15L16.5 10.5 M4 16.25V18Q4 20.5 6.5 20.5H17.5Q20 20.5 20 18V16.25", ""),
        ["playlist"] = ("M3.5 5.25H11 M3.5 9.75H11 M3.5 14.25H8", "M15 6.7Q15 5.7 16 5.4L20.75 4.05Q21.75 3.75 21.75 4.8V7.15Q21.75 7.9 21 8.1L17.25 9.2V17.5C17.25 19.9 14.75 21 12.85 21C11.15 21 10 20 10 18.65C10 16.6 12.75 15.6 15 16.1Z"),
        ["library"] = ("M7 4H17.5Q20 4 20 6.5V16.5Q20 19 17.5 19H7Q4.5 19 4.5 16.5V6.5Q4.5 4 7 4Z M8.5 8.5H16 M8.5 12.5H16 M1.75 7.5V18Q1.75 21.75 5.5 21.75H16.5", ""),
        ["settings"] = ("M9.5 4.5L10 2.75H14L14.5 4.5L17 5.95L18.75 5.5L20.75 8.95L19.5 10.25V13.75L20.75 15.05L18.75 18.5L17 18.05L14.5 19.5L14 21.25H10L9.5 19.5L7 18.05L5.25 18.5L3.25 15.05L4.5 13.75V10.25L3.25 8.95L5.25 5.5L7 5.95Z M15.25 12A3.25 3.25 0 1 1 8.75 12A3.25 3.25 0 1 1 15.25 12", ""),
        ["add"] = ("M12 4.5V19.5 M4.5 12H19.5", ""),
        ["close"] = ("M6 6L18 18 M18 6L6 18", ""),
        ["chevron-left"] = ("M14.75 5.25L8 12L14.75 18.75", ""),
        ["chevron-right"] = ("M9.25 5.25L16 12L9.25 18.75", ""),
        ["more"] = ("", "M5.25 12A1.75 1.75 0 1 1 1.75 12A1.75 1.75 0 1 1 5.25 12 M13.75 12A1.75 1.75 0 1 1 10.25 12A1.75 1.75 0 1 1 13.75 12 M22.25 12A1.75 1.75 0 1 1 18.75 12A1.75 1.75 0 1 1 22.25 12")
    };
    internal static IReadOnlyCollection<string> Names => Paths.Keys;
    internal static string StarData => Paths["star"].Fill;
    internal static UIElement Create(string name, double size, Control? owner = null, Brush? ink = null)
    {
        name = name switch { "\uE768" => "play", "\uE769" => "pause", "\uE892" => "previous", "\uE893" => "next", "\uE8B1" => "shuffle", "\uE8EE" => "repeat", "\uE734" => "star", "\uE767" => "volume", "\uE8F2" => "lyrics", "\uE8FD" => "queue", "\uE72C" => "refresh", "\uE710" => "add", "\uE711" => "close", "\uE712" => "more", "\uE76B" => "chevron-left", "\uE76C" => "chevron-right", _ => name };
        if (!Paths.TryGetValue(name, out var spec)) return new FontIcon { Glyph = name, FontFamily = new("Segoe Fluent Icons"), FontSize = size };
        var canvas = new Canvas { Width = 24, Height = 24 };
        foreach (var (data, filled) in new[] { (spec.Fill, true), (spec.Stroke, false) })
        {
            if (data.Length == 0) continue;
            var shape = (Microsoft.UI.Xaml.Shapes.Path)XamlReader.Load($"<Path xmlns='http://schemas.microsoft.com/winfx/2006/xaml/presentation' Data='F1 {data}' />");
            shape.StrokeThickness = name == "lossless" ? 1.8 : 2.25; shape.StrokeStartLineCap = shape.StrokeEndLineCap = PenLineCap.Round; shape.StrokeLineJoin = PenLineJoin.Round;
            var property = filled ? Shape.FillProperty : Shape.StrokeProperty;
            if (owner is not null) shape.SetBinding(property, new Binding { Source = owner, Path = new PropertyPath("Foreground") }); else shape.SetValue(property, ink ?? Ui.Muted);
            canvas.Children.Add(shape);
        }
        var icon = new Viewbox { Width = size, Height = size, Child = canvas };
        if (owner is not null) icon.SetBinding(UIElement.OpacityProperty, new Binding { Source = owner, Path = new PropertyPath("IsEnabled"), Converter = EnabledOpacity });
        return icon;
    }
    private sealed class IconOpacityConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, string language) => value is true ? 1d : .38d;
        public object ConvertBack(object value, Type targetType, object parameter, string language) => throw new NotSupportedException();
    }
}
