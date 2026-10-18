using AMDownloader.WinUI.Views;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Rectangle = Microsoft.UI.Xaml.Shapes.Rectangle;

namespace AMDownloader.WinUI;

public sealed partial class MainWindow
{
    private async Task<object> VerifyThemeUiAsync(string folder)
    {
        var adding = AddMusicAsync();
        try
        {
            await Until(() => activeDialog is not null, 3000); await Task.Delay(150);
            var links = Descendants<TextBox>(activeDialog!).Single(x => x.AcceptsReturn); links.Text = ""; links.Focus(FocusState.Programmatic); await Task.Delay(120);
            await CaptureAsync(activeDialog!, "add-music-theme");
            await CheckButtonAsync(FindElement<Button>(activeDialog!, "PrimaryButton")!);
            CheckFocus(links); Require(IsRose(links.SelectionHighlightColor), "下载链接文本选中仍使用系统色");
        }
        finally { activeDialog?.Hide(); await adding; }

        var check = new CheckBox { Content = "记住我的选择", IsChecked = true };
        var password = new PasswordBox { Password = "fixture", PlaceholderText = "密码" };
        var combo = Ui.Combo(new[] { ("ALAC · 无损", (object)"alac"), ("AAC", (object)"aac") }, "alac");
        var button = Ui.Button("保存设置", () => { }, true);
        var panel = Ui.Stack(12); panel.Width = 410;
        foreach (var control in new FrameworkElement[] { check, password, combo, button }) panel.Children.Add(control);
        var showing = ShowDialogAsync("主题验收", panel);
        try
        {
            await Until(() => activeDialog is not null, 3000); await Task.Delay(180);
            var box = FindElement<Rectangle>(check, "NormalRectangle") ?? throw new InvalidOperationException("复选框模板缺失");
            Require(IsRose(box.Fill), "记住密码/记住选择复选框仍使用系统色");
            password.Focus(FocusState.Programmatic); await Task.Delay(100); CheckFocus(password);
            await CheckButtonAsync(button); await CaptureAsync(activeDialog!, "native-control-theme");
            combo.IsDropDownOpen = true; await Task.Delay(200);
            var items = VisualTreeHelper.GetOpenPopupsForXamlRoot(root.XamlRoot).SelectMany(x => Descendants<ComboBoxItem>(x.Child)).Where(x => x.IsSelected).ToList();
            Require(items.Count > 0 && items.All(x => IsRose(FindElement<Rectangle>(x, "Pill")?.Fill)), "下拉选中指示仍使用系统色");
            combo.IsDropDownOpen = false;
        }
        finally { activeDialog?.Hide(); await showing; }

        var originalSize = AppWindow.Size; var scale = root.XamlRoot.RasterizationScale; var widths = new List<object>();
        try
        {
            foreach (var width in new[] { 1100, 1440, 1800 })
            {
                AppWindow.Resize(new Windows.Graphics.SizeInt32((int)(width * scale), (int)(720 * scale))); await Task.Delay(180);
                ShowVolume(); await Task.Delay(250); root.UpdateLayout();
                var track = FindElement<Rectangle>(volumeSlider, "HorizontalTrackRect")!;
                var left = track.TransformToVisual(volumePanel).TransformPoint(new()).X;
                var right = volumePanel.ActualWidth - track.TransformToVisual(volumePanel).TransformPoint(new(track.ActualWidth, 0)).X;
                Require(Math.Abs(left - right) < 1 && track.ActualWidth >= 25, "音量滑轨左右留白不对称或超出窄窗口");
                Require(IsRose(FindElement<Rectangle>(volumeSlider, "HorizontalDecreaseRect")!.Fill), "音量条仍使用系统色");
                widths.Add(new { width, left, right, trackWidth = track.ActualWidth }); await CaptureAsync(root, "volume-theme-" + width); HideVolume();
            }
        }
        finally { HideVolume(); AppWindow.Resize(originalSize); }
        return new { theme = "download-dialog,input-focus,text-selection,password,checkbox,combo,accent-button", volume = widths, ok = true };

        static bool IsRose(Brush? value) => value is SolidColorBrush solid && solid.Color == Ui.Accent.Color || value is GradientBrush gradient && gradient.GradientStops.Any(x => x.Color == Ui.Accent.Color);
        static void Require(bool condition, string error) { if (!condition) throw new InvalidOperationException(error); }
        void CheckFocus(Control control)
        {
            Require(control.FocusState != FocusState.Unfocused && Descendants<Border>(control).Any(x => IsRose(x.BorderBrush)), "输入框焦点下划线仍使用系统色：" + control.GetType().Name);
        }
        async Task CheckButtonAsync(Button control)
        {
            foreach (var (state, color) in new[] { ("Normal", Ui.Accent.Color), ("PointerOver", Ui.Brush(255, 227, 48, 91).Color), ("Pressed", Ui.Brush(255, 201, 42, 81).Color) })
            {
                Require(VisualStateManager.GoToState(control, state, false), "按钮状态缺失"); await Task.Delay(110);
                var face = FindElement<ContentPresenter>(control, "ContentPresenter")!;
                Require(face.Background is SolidColorBrush background && background.Color == color, "主按钮仍使用系统色：" + state);
                Require(face.Foreground is SolidColorBrush foreground && foreground.Color == Microsoft.UI.Colors.White, "主按钮文字未统一为白色");
            }
            VisualStateManager.GoToState(control, "Normal", false);
        }
        async Task CaptureAsync(UIElement control, string name) { var bitmap = new RenderTargetBitmap(); await bitmap.RenderAsync(control); await SaveScreenshotAsync(bitmap, Path.Combine(folder, name + ".png")); }
    }
}
