using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Data;
using Microsoft.UI.Xaml.Markup;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Shapes;

namespace AMDownloader.WinUI.Views;

internal static class Icons
{
    private static readonly Dictionary<string, (string Data, bool Fill)> Paths = new()
    {
        ["play"] = ("M7.2 2.7 L20 10.8 Q22 12 20 13.2 L7.2 21.3 Q5.5 22 5.5 20 L5.5 4 Q5.5 2 7.2 2.7Z", true),
        ["pause"] = ("M6 4H10.5V20H6Z M14 4H18.5V20H14Z", true),
        ["next"] = ("M2 5L12.6 12L2 19Z M12 5L22.5 12L12 19Z", true),
        ["previous"] = ("M22 5L11.4 12L22 19Z M12 5L1.5 12L12 19Z", true),
        ["shuffle"] = ("M3 6H5C10 6 13 18 18 18H21 M3 18H5C7.2 18 8.8 15.7 10.2 13.7 M13.8 10.3C15.2 8.3 16.7 6 18 6H21 M18 3L21 6L18 9 M18 15L21 18L18 21", false),
        ["repeat"] = ("M3 13V10Q3 6 7 6H20 M17 3L20 6L17 9 M21 11V14Q21 18 17 18H4 M7 15L4 18L7 21", false),
        ["star"] = ("M12 3L14.7 8.6L21 9.5L16.5 14L17.6 20.4L12 17.4L6.4 20.4L7.5 14L3 9.5L9.3 8.6Z", true),
        ["lossless"] = ("M1.6 13C3 2.8 5.6 2.8 7.9 11.9C10.2 21.2 13.3 21.5 15.6 10.5 M5 13C6.4 2.8 9 2.8 11.3 11.9C13.6 21.2 16.7 21.5 19 10.5 M8.4 13C9.8 2.8 12.4 2.8 14.7 11.9C17 21.2 20.1 21.5 22.4 10.5", false),
        ["lyrics"] = ("M7.5 17.5L5.5 22L12 17.5H18.5Q21 17.5 21 15V6Q21 3.5 18.5 3.5H5.5Q3 3.5 3 6V15Q3 17.5 5.5 17.5Z M7 7H10V10Q10 12 7 13 M13 7H16V10Q16 12 13 13", false),
        ["queue"] = ("M8 6H21 M8 12H21 M8 18H21 M3 6H3.2 M3 12H3.2 M3 18H3.2", false),
        ["volume"] = ("M6 9H9L14.5 4.5V19.5L9 15H6Z M17 8Q21 12 17 16 M19 4.5Q25 12 19 19.5", false),
        ["volume-low"] = ("M6 9H9L14.5 4.5V19.5L9 15H6Z", false),
        ["refresh"] = ("M20 12A8.2 8.2 0 1 1 17.8 6.2 M20 3V8H15", false),
        ["home"] = ("M2.8 10.2L10.6 3.7Q12 2.5 13.4 3.7L21.2 10.2 M4.4 9.2V19.6Q4.4 21 5.8 21H18.2Q19.6 21 19.6 19.6V9.2 M9.2 21V13H14.8V21", false),
        ["album"] = ("M7 3H17 M5 6H19 M6 9H18Q20 9 20 11V19Q20 21 18 21H6Q4 21 4 19V11Q4 9 6 9Z", false),
        ["recent"] = ("M21 12A9 9 0 1 1 3 12A9 9 0 1 1 21 12 M12 6.2V12H8", false),
        ["artist"] = ("M15 3Q18 1 20 4Q22 7 19 10L15 14L10 9Z M10 9L5 16L4 20L8 18L15 14 M6 16L8 18", false),
        ["songs"] = ("M10 5L18 3V7.5L12 9V18C12 22 4.5 22.8 4.5 19.1C4.5 17.1 7.5 16.1 10 16.4Z", true),
        ["favourites"] = ("M5 3.2H19Q21 3.2 21 5.2V19Q21 21 19 21H5Q3.2 21 3.2 19V5.2Q3.2 3.2 5 3.2Z M12 7L13.5 10L17 10.5L14.5 13L15 16L12 14.5L9 16L9.5 13L7 10.5L10.5 10Z", false),
        ["download"] = ("M12 3V16 M7 11L12 16L17 11 M4 17V20Q4 21 5 21H19Q20 21 20 20V17", false),
        ["playlist"] = ("M2 6H10 M2 10H10 M2 14H9 M16 7L22 5V9L18 10V18C18 21 12 21 12 18.5C12 17 14 16 16 16Z", false)
    };
    internal static UIElement Create(string name, double size, Control? owner = null, Brush? ink = null)
    {
        if (!Paths.TryGetValue(name, out var spec)) return new FontIcon { Glyph = name, FontFamily = new("Segoe Fluent Icons"), FontSize = size };
        var shape = (Microsoft.UI.Xaml.Shapes.Path)XamlReader.Load($"<Path xmlns='http://schemas.microsoft.com/winfx/2006/xaml/presentation' Data='{spec.Data}' />");
        shape.StrokeThickness = name == "lossless" ? 1.35 : 1.75; shape.StrokeStartLineCap = shape.StrokeEndLineCap = PenLineCap.Round; shape.StrokeLineJoin = PenLineJoin.Round;
        var property = spec.Fill ? Shape.FillProperty : Shape.StrokeProperty;
        if (owner is not null) shape.SetBinding(property, new Binding { Source = owner, Path = new PropertyPath("Foreground") }); else shape.SetValue(property, ink ?? Ui.Muted);
        var canvas = new Canvas { Width = 24, Height = 24 }; canvas.Children.Add(shape); return new Viewbox { Width = size, Height = size, Child = canvas };
    }
}
