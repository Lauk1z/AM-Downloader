using AMDownloader.WinUI.Views;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;

namespace AMDownloader.WinUI;

public sealed partial class MainWindow
{
    private async Task<object> VerifyIconsUiAsync(string folder)
    {
        var previous = pageHost.Content;
        var gallery = new Grid { Width = 800, Padding = new(12), ColumnSpacing = 12, RowSpacing = 12, Background = Ui.Brush(255, 32, 32, 34), HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center };
        for (var column = 0; column < 4; ++column) gallery.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) });
        var index = 0; var buttons = new List<Button>();
        foreach (var name in Icons.Names)
        {
            if (index % 4 == 0) gallery.RowDefinitions.Add(new() { Height = GridLength.Auto });
            var content = Ui.Stack(6); content.Children.Add(Ui.Text(name, 11, color: Ui.Muted));
            var sizes = Ui.Stack(12, Orientation.Horizontal); sizes.VerticalAlignment = VerticalAlignment.Center;
            foreach (var size in new[] { 16, 24, 32 })
            {
                var button = Ui.Icon(name, name, () => { }, size); button.Padding = new(0); button.Foreground = size == 32 ? Ui.Accent : Ui.Muted;
                if (button.Content is not Viewbox { Child: Canvas canvas } || canvas.Children.Count == 0) throw new InvalidOperationException("图标未使用矢量绘制：" + name);
                foreach (var shape in canvas.Children.OfType<Microsoft.UI.Xaml.Shapes.Path>())
                {
                    var bounds = shape.Data.Bounds; var inset = shape.Stroke is null ? 0 : shape.StrokeThickness / 2;
                    if (bounds.Left - inset < 0 || bounds.Top - inset < 0 || bounds.Right + inset > 24 || bounds.Bottom + inset > 24) throw new InvalidOperationException("图标超出画布：" + name);
                }
                sizes.Children.Add(button); buttons.Add(button);
            }
            content.Children.Add(sizes); var card = new Border { Child = content, Padding = new(12), CornerRadius = new(8), Background = Ui.Brush(255, 46, 45, 50) };
            Grid.SetColumn(card, index % 4); Grid.SetRow(card, index / 4); gallery.Children.Add(card); ++index;
        }
        try
        {
            pageHost.Content = gallery; root.UpdateLayout(); await Task.Delay(100);
            await CaptureAsync("icons-rounded");
            foreach (var state in new[] { "PointerOver", "Pressed", "Disabled" })
            {
                foreach (var button in buttons)
                {
                    button.IsEnabled = state != "Disabled";
                    VisualStateManager.GoToState(button, state, false);
                }
                await Task.Delay(50);
                foreach (var button in buttons)
                {
                    if (state == "Disabled" && ((Viewbox)button.Content).Opacity >= 1) throw new InvalidOperationException("禁用图标没有变淡");
                    foreach (var shape in Descendants<Microsoft.UI.Xaml.Shapes.Path>(button))
                    {
                        if ((shape.Fill ?? shape.Stroke) is not SolidColorBrush ink || button.Foreground is not SolidColorBrush foreground || ink.Color != foreground.Color) throw new InvalidOperationException("图标状态颜色与按钮不一致");
                    }
                }
                await CaptureAsync("icons-" + state);
            }
            return new { icons = index, sizes = new[] { 16, 24, 32 }, states = "normal,hover,pressed,disabled", canvasBounds = true, ok = true };
        }
        finally { pageHost.Content = previous; }
        async Task CaptureAsync(string name) { var bitmap = new RenderTargetBitmap(); await bitmap.RenderAsync(gallery); await SaveScreenshotAsync(bitmap, System.IO.Path.Combine(folder, name + ".png")); }
    }
}
