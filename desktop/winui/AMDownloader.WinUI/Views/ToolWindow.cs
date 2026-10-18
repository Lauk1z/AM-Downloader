using System.Runtime.InteropServices;
using Microsoft.UI;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Windows.Graphics;

namespace AMDownloader.WinUI.Views;

internal sealed class ToolWindow : Window
{
    private readonly TaskCompletionSource closed = new(TaskCreationOptions.RunContinuationsAsynchronously);
    internal Task Completion => closed.Task;
    internal UIElement Body { get; }
    internal ToolWindow(Window owner, string title, UIElement content, int width, int height, string close = "关闭", Action? settings = null)
    {
        Title = title; Body = content;
        var panel = new Grid { Padding = new(24), RowSpacing = 18, Background = Ui.Brush(255, 32, 32, 34), RequestedTheme = ElementTheme.Dark };
        panel.RowDefinitions.Add(new() { Height = GridLength.Auto }); panel.RowDefinitions.Add(new() { Height = new(1, GridUnitType.Star) }); panel.RowDefinitions.Add(new() { Height = GridLength.Auto });
        panel.Children.Add(Ui.Text(title, 23, true)); var scroll = Ui.Scroll(content); Grid.SetRow(scroll, 1); panel.Children.Add(scroll);
        var buttons = Ui.Stack(12, Orientation.Horizontal); buttons.HorizontalAlignment = HorizontalAlignment.Right;
        if (settings is not null) buttons.Children.Add(Ui.Button("音频设置", () => { settings(); Close(); }));
        buttons.Children.Add(Ui.Button(close, Close)); Grid.SetRow(buttons, 2); panel.Children.Add(buttons); Content = panel;
        var escape = new KeyboardAccelerator { Key = Windows.System.VirtualKey.Escape }; escape.Invoked += (_, e) => { e.Handled = true; Close(); }; panel.KeyboardAccelerators.Add(escape);
        var handle = WinRT.Interop.WindowNative.GetWindowHandle(this); var parent = WinRT.Interop.WindowNative.GetWindowHandle(owner);
        SetWindowLongPtr(handle, -8, parent);
        var scale = GetDpiForWindow(parent) / 96d; var work = DisplayArea.GetFromWindowId(owner.AppWindow.Id, DisplayAreaFallback.Nearest).WorkArea;
        var size = new SizeInt32((int)Math.Min(width * scale, work.Width * .94), (int)Math.Min(height * scale, work.Height * .94));
        AppWindow.Resize(size); AppWindow.Move(new PointInt32(Math.Clamp(owner.AppWindow.Position.X + (owner.AppWindow.Size.Width - size.Width) / 2, work.X, Math.Max(work.X, work.X + work.Width - size.Width)), Math.Clamp(owner.AppWindow.Position.Y + (owner.AppWindow.Size.Height - size.Height) / 2, work.Y, Math.Max(work.Y, work.Y + work.Height - size.Height))));
        AppWindow.SetIcon(Path.Combine(AppContext.BaseDirectory, "Assets/app.ico"));
        if (AppWindow.Presenter is OverlappedPresenter presenter) { presenter.IsMinimizable = false; presenter.IsMaximizable = false; }
        AppWindow.TitleBar.BackgroundColor = AppWindow.TitleBar.ButtonBackgroundColor = ColorHelper.FromArgb(255, 32, 32, 34);
        AppWindow.TitleBar.ForegroundColor = AppWindow.TitleBar.ButtonForegroundColor = ColorHelper.FromArgb(255, 238, 238, 242);
        Closed += (_, _) => closed.TrySetResult();
    }
    [DllImport("user32.dll")] private static extern uint GetDpiForWindow(nint window);
    [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW")] private static extern nint SetWindowLongPtr(nint window, int index, nint value);
}
