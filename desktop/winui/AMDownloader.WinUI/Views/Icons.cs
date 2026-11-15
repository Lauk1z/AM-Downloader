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
        ["play"] = ("", "M7.9 3.9C6.65 3.14 5.25 3.84 5.25 5.32V18.68C5.25 20.16 6.65 20.86 7.9 20.1L19.25 13.36C20.43 12.66 20.43 11.34 19.25 10.64Z"),
        ["pause"] = ("", "M6.8 3.5H8.45Q10 3.5 10 5.05V18.95Q10 20.5 8.45 20.5H6.8Q5.25 20.5 5.25 18.95V5.05Q5.25 3.5 6.8 3.5Z M15.55 3.5H17.2Q18.75 3.5 18.75 5.05V18.95Q18.75 20.5 17.2 20.5H15.55Q14 20.5 14 18.95V5.05Q14 3.5 15.55 3.5Z"),
        ["next"] = ("", "M2.3 5.9Q2.3 4.5 3.42 5.34L11.18 11.16Q12.3 12 11.18 12.84L3.42 18.66Q2.3 19.5 2.3 18.1Z M12.1 5.9Q12.1 4.5 13.22 5.34L20.98 11.16Q22.1 12 20.98 12.84L13.22 18.66Q12.1 19.5 12.1 18.1Z"),
        ["previous"] = ("", "M21.7 5.9Q21.7 4.5 20.58 5.34L12.82 11.16Q11.7 12 12.82 12.84L20.58 18.66Q21.7 19.5 21.7 18.1ZM11.9 5.9Q11.9 4.5 10.78 5.34L3.02 11.16Q1.9 12 3.02 12.84L10.78 18.66Q11.9 19.5 11.9 18.1Z"),
        ["shuffle"] = ("M3.25 6.5H5.5C10.5 6.5 13.5 17.5 18.5 17.5H20.75 M3.25 17.5H5.5C7.5 17.5 9 15.6 10 14 M14 10C15 8.4 16.5 6.5 18.5 6.5H20.75 M18 3.75L20.75 6.5L18 9.25 M18 14.75L20.75 17.5L18 20.25", ""),
        ["repeat"] = ("M3.75 11.25V10C3.75 7.5 5.75 5.5 8.25 5.5H20 M17.25 2.75L20 5.5L17.25 8.25 M20.25 12.75V14C20.25 16.5 18.25 18.5 15.75 18.5H4 M6.75 15.75L4 18.5L6.75 21.25", ""),
        ["star"] = ("", "M11.15 3.25Q12 1.55 12.85 3.25L15.15 7.9L20.3 8.65Q22.2 8.92 20.83 10.25L17.1 13.88L17.98 19.02Q18.3 20.9 16.61 20.01L12 17.59L7.39 20.01Q5.7 20.9 6.02 19.02L6.9 13.88L3.17 10.25Q1.8 8.92 3.7 8.65L8.85 7.9Z"),
        ["lossless"] = ("M2 12C3.35 4.2 5.15 4.2 7 12C8.85 19.8 10.65 19.8 12 12 M7 12C8.35 4.2 10.15 4.2 12 12C13.85 19.8 15.65 19.8 17 12 M12 12C13.35 4.2 15.15 4.2 17 12C18.85 19.8 20.65 19.8 22 12", ""),
        ["lyrics"] = ("M8 17.5L5.5 20.15Q4.75 20.95 4.75 19.85V17.15C3.3 16.65 2.75 15.6 2.75 14V7C2.75 4.7 4.2 3.25 6.5 3.25H17.5C19.8 3.25 21.25 4.7 21.25 7V13.75C21.25 16.05 19.8 17.5 17.5 17.5Z", "M7.3 7H9.7Q10.5 7 10.5 7.8V9.45C10.5 11.7 9.15 13.2 7 13.55V12.1C8.3 11.85 8.95 11.15 9 10.2H7.3Q6.5 10.2 6.5 9.4V7.8Q6.5 7 7.3 7Z M13.8 7H16.2Q17 7 17 7.8V9.45C17 11.7 15.65 13.2 13.5 13.55V12.1C14.8 11.85 15.45 11.15 15.5 10.2H13.8Q13 10.2 13 9.4V7.8Q13 7 13.8 7Z"),
        ["queue"] = ("M8.25 5.5H20.5 M8.25 12H20.5 M8.25 18.5H20.5", "M4.75 5.5A1.5 1.5 0 1 1 1.75 5.5A1.5 1.5 0 1 1 4.75 5.5 M4.75 12A1.5 1.5 0 1 1 1.75 12A1.5 1.5 0 1 1 4.75 12 M4.75 18.5A1.5 1.5 0 1 1 1.75 18.5A1.5 1.5 0 1 1 4.75 18.5"),
        ["volume"] = ("M16 8.5C17.95 10.4 17.95 13.6 16 15.5 M19 5.5C22.5 9 22.5 15 19 18.5", "M4.25 8.5H6.5L10.75 4.95C11.7 4.15 12.75 4.6 12.75 5.85V18.15C12.75 19.4 11.7 19.85 10.75 19.05L6.5 15.5H4.25C3.42 15.5 2.75 14.83 2.75 14V10C2.75 9.17 3.42 8.5 4.25 8.5Z"),
        ["volume-low"] = ("", "M8.5 8.5H10.75L15 4.95C15.95 4.15 17 4.6 17 5.85V18.15C17 19.4 15.95 19.85 15 19.05L10.75 15.5H8.5C7.67 15.5 7 14.83 7 14V10C7 9.17 7.67 8.5 8.5 8.5Z"),
        ["refresh"] = ("M20 10C19.15 6.35 15.8 3.75 12 3.75A8.25 8.25 0 1 0 20 14.1 M20.25 4.75V10H15", ""),
        ["home"] = ("M3.25 10.25L10.1 4.3Q12 2.65 13.9 4.3L20.75 10.25 M5.25 8.5V18Q5.25 20.5 7.75 20.5H9.25V14.5Q9.25 13 10.75 13H13.25Q14.75 13 14.75 14.5V20.5H16.25Q18.75 20.5 18.75 18V8.5", ""),
        ["album"] = ("M7.5 3H16.5 M5.5 6.5H18.5 M6.25 10H17.75Q20.5 10 20.5 12.75V18.25Q20.5 21 17.75 21H6.25Q3.5 21 3.5 18.25V12.75Q3.5 10 6.25 10Z", ""),
        ["recent"] = ("M20.5 12A8.5 8.5 0 1 1 3.5 12A8.5 8.5 0 1 1 20.5 12 M12 6.75V12H8.5", ""),
        ["artist"] = ("M5.5 10.5V11.5C5.5 15.1 8.4 17.75 12 17.75C15.6 17.75 18.5 15.1 18.5 11.5V10.5 M12 17.75V21 M8.5 21H15.5", "M12 2.25C9.8 2.25 8.25 3.85 8.25 6V10.5C8.25 12.65 9.8 14.25 12 14.25C14.2 14.25 15.75 12.65 15.75 10.5V6C15.75 3.85 14.2 2.25 12 2.25Z"),
        ["songs"] = ("", "M10.25 5.75C10.25 4.95 10.7 4.4 11.5 4.18L18.25 2.38C19.1 2.15 19.5 2.65 19.5 3.45V6.15C19.5 6.9 19.15 7.2 18.4 7.4L12.75 8.9V17.25C12.75 20 9.95 21.5 7.3 21.5C5.05 21.5 3.5 20.3 3.5 18.65C3.5 16.2 6.8 14.8 10.25 15.35Z"),
        ["favourites"] = ("M6.5 3.5H17.5Q20.5 3.5 20.5 6.5V17.5Q20.5 20.5 17.5 20.5H6.5Q3.5 20.5 3.5 17.5V6.5Q3.5 3.5 6.5 3.5Z", "M11.55 7.362Q12 6.462 12.45 7.362L13.669 9.827L16.399 10.224Q17.406 10.368 16.68 11.072L14.703 12.996L15.169 15.721Q15.339 16.717 14.443 16.245L12 14.963L9.557 16.245Q8.661 16.717 8.831 15.721L9.297 12.996L7.32 11.072Q6.594 10.368 7.601 10.224L10.331 9.827Z"),
        ["download"] = ("M12 3.5V15 M7.5 10.5L12 15L16.5 10.5 M4 16.25V18Q4 20.5 6.5 20.5H17.5Q20 20.5 20 18V16.25", ""),
        ["playlist"] = ("M3.5 5.25H11 M3.5 9.75H10.5 M3.5 14.25H7.25", "M14.688 9.113C14.688 8.512 15.025 8.1 15.625 7.935L20.688 6.585C21.325 6.412 21.625 6.787 21.625 7.388V9.413C21.625 9.975 21.362 10.2 20.8 10.35L16.562 11.475V17.738C16.562 19.8 14.462 20.925 12.475 20.925C10.787 20.925 9.625 20.025 9.625 18.787C9.625 16.95 12.1 15.9 14.688 16.312Z"),
        ["library"] = ("M9.75 3.25H18Q20.75 3.25 20.75 6V15.75Q20.75 18.5 18 18.5H9.75Q7 18.5 7 15.75V6Q7 3.25 9.75 3.25Z M10.25 8.25H17.5 M10.25 12.25H17.5 M3.25 7.25V18.75Q3.25 21.25 5.75 21.25H16.75", ""),
        ["settings"] = ("M9.067 4.751Q9.5 4.5 9.637 4.019L9.863 3.231Q10 2.75 10.5 2.75L13.5 2.75Q14 2.75 14.137 3.231L14.363 4.019Q14.5 4.5 14.933 4.751L16.567 5.699Q17 5.95 17.484 5.825L18.266 5.625Q18.75 5.5 19.001 5.933L20.499 8.517Q20.75 8.95 20.403 9.31L19.847 9.89Q19.5 10.25 19.5 10.75L19.5 13.25Q19.5 13.75 19.847 14.11L20.403 14.69Q20.75 15.05 20.499 15.483L19.001 18.067Q18.75 18.5 18.266 18.375L17.484 18.175Q17 18.05 16.567 18.301L14.933 19.249Q14.5 19.5 14.363 19.981L14.137 20.769Q14 21.25 13.5 21.25L10.5 21.25Q10 21.25 9.863 20.769L9.637 19.981Q9.5 19.5 9.067 19.249L7.433 18.301Q7 18.05 6.516 18.175L5.734 18.375Q5.25 18.5 4.999 18.067L3.501 15.483Q3.25 15.05 3.597 14.69L4.153 14.11Q4.5 13.75 4.5 13.25L4.5 10.75Q4.5 10.25 4.153 9.89L3.597 9.31Q3.25 8.95 3.501 8.517L4.999 5.933Q5.25 5.5 5.734 5.625L6.516 5.825Q7 5.95 7.433 5.699Z M8.55 12A3.45 3.45 0 1 1 15.45 12A3.45 3.45 0 1 1 8.55 12Z", ""),
        ["add"] = ("M12 4.5V19.5 M4.5 12H19.5", ""),
        ["close"] = ("M6 6L18 18 M18 6L6 18", ""),
        ["chevron-left"] = ("M14.75 5.25L8 12L14.75 18.75", ""),
        ["chevron-right"] = ("M9.25 5.25L16 12L9.25 18.75", ""),
        ["more"] = ("", "M3.2 12A1.8 1.8 0 1 1 6.8 12A1.8 1.8 0 1 1 3.2 12Z M10.2 12A1.8 1.8 0 1 1 13.8 12A1.8 1.8 0 1 1 10.2 12Z M17.2 12A1.8 1.8 0 1 1 20.8 12A1.8 1.8 0 1 1 17.2 12Z"),
        ["fullscreen"] = ("M4 9V4H9 M15 4H20V9 M20 15V20H15 M9 20H4V15", ""),
        ["expand-player"] = ("M4 10V4H10 M4 4L10 10 M14 14L20 20 M14 20H20V14", ""),
        ["shrink-player"] = ("M4 4L10 10 M4 10H10V4 M14 20V14H20 M14 14L20 20", ""),
        ["minimize"] = ("M4 12H20", ""),
        ["mini-player"] = ("M6 4H18Q21 4 21 7V17Q21 20 18 20H6Q3 20 3 17V7Q3 4 6 4Z", "M13 11H18Q19 11 19 12V16Q19 17 18 17H13Q12 17 12 16V12Q12 11 13 11Z"),
        ["repeat-one"] = ("M3.75 11.25V10C3.75 7.5 5.75 5.5 8.25 5.5H20 M17.25 2.75L20 5.5L17.25 8.25 M20.25 12.75V14C20.25 16.5 18.25 18.5 15.75 18.5H4 M6.75 15.75L4 18.5L6.75 21.25", "M10 9.3L12.2 7.8H13.8V16.2H11.8V10.3L10 11.5Z")
    };
    internal static IReadOnlyCollection<string> Names => Paths.Keys;
    internal static string StarData => Paths["star"].Fill;
    internal static string PlayData => Paths["play"].Fill;
    internal static string PauseData => Paths["pause"].Fill;
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
