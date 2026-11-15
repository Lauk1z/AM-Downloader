using System.Runtime.InteropServices;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.Graphics;
using Windows.System;

namespace AMDownloader.WinUI.Views;

internal sealed class TrayMenuWindow : Window
{
    internal readonly Border Surface;
    internal readonly List<Button> Commands = [];
    private readonly MouseProc mouseCallback;
    private nint mouseHook;
    private bool closed;
    internal bool WatchingOutsideClicks => mouseHook != 0;

    internal TrayMenuWindow(string title, bool playing, bool canPlay, bool canSkip, Action<string> action)
    {
        mouseCallback = MouseInput;
        Title = "AM Dowloader";
        var items = Ui.Stack(0);
        Surface = new Border { Child = items, Padding = new(5), CornerRadius = new(8), BorderThickness = new(1),
            Background = Ui.Brush(255, 43, 43, 43), BorderBrush = Ui.Brush(255, 64, 64, 64), RequestedTheme = ElementTheme.Dark };
        Content = Surface;
        Add("show", "显示主窗口");
        var current = Ui.Text(title, 12, color: Ui.Brush(255, 160, 160, 166));
        current.TextWrapping = TextWrapping.NoWrap; current.TextTrimming = TextTrimming.CharacterEllipsis;
        current.Margin = new(14, 4, 14, 7); items.Children.Add(current);
        Add("play", playing ? "暂停" : "播放", canPlay); Add("previous", "上一首", canSkip); Add("next", "下一首", canSkip);
        Separator(); Add("queue", "正在播放队列"); Add("output", "音频输出链路"); Add("tray", "最小化到托盘"); Separator(); Add("quit", "退出");
        Surface.KeyDown += (_, e) => { if (MoveFocus(e.Key)) e.Handled = true; };
        Surface.Loaded += (_, _) => Commands[0].Focus(FocusState.Programmatic);
        Activated += (_, e) => { if (e.WindowActivationState == WindowActivationState.Deactivated && !closed) Close(); };
        Closed += (_, _) => { closed = true; if (mouseHook != 0) { UnhookWindowsHookEx(mouseHook); mouseHook = 0; } };
        AppWindow.IsShownInSwitchers = false;
        var presenter = OverlappedPresenter.CreateForContextMenu(); presenter.SetBorderAndTitleBar(false, false);
        presenter.IsAlwaysOnTop = true; AppWindow.SetPresenter(presenter);
        var handle = WinRT.Interop.WindowNative.GetWindowHandle(this); var dark = 1; var corners = 2;
        DwmSetWindowAttribute(handle, 20, ref dark, sizeof(int)); DwmSetWindowAttribute(handle, 33, ref corners, sizeof(int));

        void Add(string command, string label, bool enabled = true)
        {
            var button = new TrayCommandButton { Content = label, Tag = command, IsEnabled = enabled, Height = 30, MinHeight = 0,
                FontSize = 14, Padding = new(14, 0, 14, 0), CornerRadius = new(4), BorderThickness = new(0),
                HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Left,
                Background = new SolidColorBrush(Microsoft.UI.Colors.Transparent), Foreground = Ui.Brush(255, 242, 242, 245) };
            button.Resources["ButtonBackgroundPointerOver"] = Ui.Brush(255, 61, 61, 63);
            button.Resources["ButtonBackgroundPressed"] = Ui.Brush(255, 72, 72, 75);
            button.Resources["ButtonBackgroundDisabled"] = button.Background;
            button.Resources["ButtonForegroundPointerOver"] = button.Resources["ButtonForegroundPressed"] = button.Foreground;
            button.Click += (_, _) => { Close(); action(command); };
            Commands.Add(button); items.Children.Add(button);
        }
        void Separator() => items.Children.Add(new Border { Height = 1, Margin = new(3, 5, 3, 5), Background = Ui.Brush(255, 63, 63, 65) });
    }

    internal void ShowAt(PointInt32 anchor)
    {
        var work = DisplayArea.GetFromPoint(anchor, DisplayAreaFallback.Nearest).WorkArea;
        AppWindow.Move(new(work.X, work.Y));
        var scale = GetDpiForWindow(WinRT.Interop.WindowNative.GetWindowHandle(this)) / 96d;
        var width = Math.Min(240, work.Width / scale - 8);
        Surface.Measure(new(width, double.PositiveInfinity));
        var size = new SizeInt32((int)Math.Ceiling(width * scale), (int)Math.Ceiling(Surface.DesiredSize.Height * scale));
        AppWindow.MoveAndResize(new(Math.Clamp(anchor.X - size.Width, work.X, Math.Max(work.X, work.X + work.Width - size.Width)),
            Math.Clamp(anchor.Y - size.Height, work.Y, Math.Max(work.Y, work.Y + work.Height - size.Height)), size.Width, size.Height));
        Activate();
        SetForegroundWindow(WinRT.Interop.WindowNative.GetWindowHandle(this));
        if (mouseHook == 0) mouseHook = SetWindowsHookEx(14, mouseCallback, GetModuleHandle(null), 0);
    }

    internal new void Close() { if (closed) return; closed = true; base.Close(); }

    private sealed class TrayCommandButton : Button
    {
        protected override void OnApplyTemplate()
        {
            base.OnApplyTemplate();
            if (GetTemplateChild("ContentPresenter") is ContentPresenter face) face.BackgroundTransition = null;
        }
    }

    private nint MouseInput(int code, nuint message, nint data)
    {
        if (code >= 0 && message is 0x201 or 0x204 or 0x207 or 0x20B)
            DismissIfOutside(Marshal.PtrToStructure<PointInt32>(data));
        return CallNextHookEx(mouseHook, code, message, data);
    }
    internal void DismissIfOutside(PointInt32 point)
    {
        if (!closed && GetWindowRect(WinRT.Interop.WindowNative.GetWindowHandle(this), out var bounds) &&
            (point.X < bounds.Left || point.X >= bounds.Right || point.Y < bounds.Top || point.Y >= bounds.Bottom))
            DispatcherQueue.TryEnqueue(Close);
    }

    internal bool MoveFocus(VirtualKey key)
    {
        if (key == VirtualKey.Escape) { Close(); return true; }
        if (key is not (VirtualKey.Up or VirtualKey.Down or VirtualKey.Home or VirtualKey.End)) return false;
        var enabled = Commands.Where(x => x.IsEnabled).ToList();
        var index = enabled.FindIndex(x => x.FocusState != FocusState.Unfocused);
        var next = key switch { VirtualKey.Home => 0, VirtualKey.End => enabled.Count - 1, VirtualKey.Up => (index - 1 + enabled.Count) % enabled.Count, _ => (index + 1) % enabled.Count };
        enabled[next].Focus(FocusState.Keyboard); return true;
    }
    [DllImport("user32.dll")] private static extern uint GetDpiForWindow(nint window);
    [DllImport("user32.dll")] private static extern bool SetForegroundWindow(nint window);
    [StructLayout(LayoutKind.Sequential)] private struct NativeRect { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] private static extern bool GetWindowRect(nint window, out NativeRect bounds);
    private delegate nint MouseProc(int code, nuint message, nint data);
    [DllImport("user32.dll", EntryPoint = "SetWindowsHookExW")] private static extern nint SetWindowsHookEx(int id, MouseProc callback, nint module, uint thread);
    [DllImport("user32.dll")] private static extern bool UnhookWindowsHookEx(nint hook);
    [DllImport("user32.dll")] private static extern nint CallNextHookEx(nint hook, int code, nuint message, nint data);
    [DllImport("kernel32.dll", EntryPoint = "GetModuleHandleW", CharSet = CharSet.Unicode)] private static extern nint GetModuleHandle(string? name);
    [DllImport("dwmapi.dll")] private static extern int DwmSetWindowAttribute(nint window, uint attribute, ref int value, int size);
}
