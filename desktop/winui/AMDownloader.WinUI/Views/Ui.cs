using Microsoft.UI;
using Microsoft.UI.Composition;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Hosting;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.UI;

namespace AMDownloader.WinUI.Views;

internal static class Ui
{
    public static readonly SolidColorBrush Accent = Brush(255, 255, 53, 101);
    public static readonly SolidColorBrush Muted = Brush(255, 153, 153, 164);
    public static SolidColorBrush Brush(byte a, byte r, byte g, byte b) => new(Color.FromArgb(a, r, g, b));
    public static TextBlock Text(string text, double size = 14, bool bold = false, Brush? color = null) => new()
    { Text = text, FontSize = size, FontWeight = bold ? Microsoft.UI.Text.FontWeights.Bold : Microsoft.UI.Text.FontWeights.Normal, Foreground = color ?? Brush(255, 238, 238, 242), TextWrapping = TextWrapping.Wrap, VerticalAlignment = VerticalAlignment.Center };
    public static Button Button(string text, Action action, bool accent = false, string? icon = null)
    {
        var button = new Button { Content = text, Padding = new(14, 9, 14, 9), CornerRadius = new(6), VerticalAlignment = VerticalAlignment.Center };
        if (accent) { UseAccentResources(button); button.Style = (Style)Application.Current.Resources["AccentButtonStyle"]; }
        if (icon is not null) SetButtonContent(button, text, icon);
        button.Click += (_, _) => action(); return button;
    }
    public static void SetButtonContent(Button button, string text, string icon)
    {
        if (button.Content is StackPanel previous && Equals(previous.Tag, (text, icon))) return;
        var content = Stack(6, Orientation.Horizontal); content.VerticalAlignment = VerticalAlignment.Center; content.Tag = (text, icon);
        content.Children.Add(Icons.Create(icon, 16, button)); content.Children.Add(new TextBlock { Text = text, VerticalAlignment = VerticalAlignment.Center });
        button.Content = content;
        Microsoft.UI.Xaml.Automation.AutomationProperties.SetName(button, text);
    }
    public static void UseAccentResources(FrameworkElement scope)
    {
        foreach (var key in new[] { "AccentButtonBackground", "AccentButtonBackgroundPointerOver", "AccentButtonBackgroundPressed", "AccentButtonForeground", "AccentButtonForegroundPointerOver", "AccentButtonForegroundPressed" }) scope.Resources[key] = Application.Current.Resources[key];
    }
    public static Button Icon(string glyph, string tip, Action action, double size = 21)
    {
        var button = new Button { Foreground = Muted, Background = new SolidColorBrush(Colors.Transparent), BorderThickness = new(0), Padding = new(6), CornerRadius = new(5), MinHeight = 0, MinWidth = 0 };
        SetGlyph(button, glyph, size);
        ToolTipService.SetToolTip(button, tip); Microsoft.UI.Xaml.Automation.AutomationProperties.SetName(button, tip); button.Click += (_, _) => action(); return button;
    }
    public static void SetGlyph(Button button, string glyph, double size)
    {
        if (Equals(button.Tag, glyph)) return;
        button.Tag = glyph;
        button.Content = Icons.Create(glyph, size, button);
    }
    public static Button MenuIcon(string tip, Func<MenuFlyout> factory, double size = 21)
    {
        var button = Icon("more", tip, () => { }, size);
        button.Click += (_, _) => { FlyoutBase.SetAttachedFlyout(button, factory()); FlyoutBase.ShowAttachedFlyout(button); };
        return button;
    }
    public static Image Image(string source, double size)
    {
        var image = new Image { Width = size, Height = size, Stretch = Stretch.UniformToFill };
        SetImage(image, source); return image;
    }
    public static void SetImage(Image image, string source)
    {
        if (source.Length == 0) { image.Source = null; return; }
        var uri = new Uri(source.StartsWith("http", StringComparison.OrdinalIgnoreCase) ? source : Path.GetFullPath(source));
        image.Source = source.EndsWith(".svg", StringComparison.OrdinalIgnoreCase) ? new SvgImageSource(uri) : new BitmapImage(uri) { DecodePixelWidth = double.IsFinite(image.Width) ? Math.Max(256, (int)image.Width) : 256 };
    }
    public static Border Cover(string source, double size, double radius = 8)
    {
        var grid = new Grid { Width = size, Height = size, Background = Brush(255, 72, 52, 62) };
        var note = (FrameworkElement)Icons.Create("songs", size * .35, ink: Brush(255, 235, 165, 183)); note.HorizontalAlignment = HorizontalAlignment.Center; note.VerticalAlignment = VerticalAlignment.Center;
        grid.Children.Add(note);
        grid.Children.Add(Image(source, size));
        return new Border { CornerRadius = new(radius), Child = grid, Width = size, Height = size };
    }
    public static StackPanel Stack(double spacing = 14, Orientation direction = Orientation.Vertical) => new() { Spacing = spacing, Orientation = direction };
    public static ScrollViewer Scroll(UIElement content) => new() { Content = content, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, HorizontalScrollMode = ScrollMode.Disabled };
    public static void Animate(UIElement element)
    {
        var visual = ElementCompositionPreview.GetElementVisual(element); var animation = visual.Compositor.CreateScalarKeyFrameAnimation();
        animation.InsertKeyFrame(0, 0); animation.InsertKeyFrame(1, 1); animation.Duration = TimeSpan.FromMilliseconds(220); visual.StartAnimation("Opacity", animation);
    }
    public static MenuFlyoutItem MenuItem(string text, Action action)
    { var item = new MenuFlyoutItem { Text = text }; item.Click += (_, _) => action(); return item; }
    public static void AddMenu(FrameworkElement element, Func<MenuFlyout> factory)
    {
        element.RightTapped += (_, e) => { e.Handled = true; factory().ShowAt(element, e.GetPosition(element)); };
    }
    public static ComboBox Combo(IEnumerable<(string Label, object Value)> values, object? selected = null)
    {
        var combo = new SafeComboBox { HorizontalAlignment = HorizontalAlignment.Stretch, MinWidth = 110 };
        foreach (var pair in values) combo.Items.Add(new ComboBoxItem { Content = pair.Label, Tag = pair.Value });
        combo.SelectedIndex = Math.Max(0, combo.Items.Cast<ComboBoxItem>().ToList().FindIndex(x => Equals(x.Tag, selected)));
        return combo;
    }
    public static T Selected<T>(ComboBox combo) => (T)((ComboBoxItem)combo.SelectedItem).Tag;
}
internal sealed class SafeComboBox : ComboBox
{
    protected override void OnPointerWheelChanged(Microsoft.UI.Xaml.Input.PointerRoutedEventArgs e)
    { if (IsDropDownOpen) base.OnPointerWheelChanged(e); }
}
